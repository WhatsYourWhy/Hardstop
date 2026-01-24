import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..utils.id_generator import new_alert_id
from .alert_models import (
    AlertAction,
    AlertDiagnostics,
    AlertEvidence,
    AlertImpactAssessment,
    AlertScope,
    IncidentEvidenceSummary,
    HardstopAlert,
)
from .correlation import build_correlation_key
from .impact_scorer import calculate_network_impact_score, map_score_to_classification
from ..output.incidents.evidence import build_incident_evidence_artifact
from ..config.loader import load_alert_quality_config
from ..database.alert_repo import (
    find_recent_alert_by_key,
    update_existing_alert_row,
    upsert_new_alert_row,
)


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen or item is None:
            continue
        seen.add(item)
        result.append(item)
    return result


def _detect_high_impact_keywords(text: str) -> Tuple[bool, List[str]]:
    """
    Detect high-impact keywords with context awareness.
    
    Uses phrase patterns to avoid false positives like "fire sale" or "strike price".
    Requires operational context (facility names, locations) or location/time signals.
    
    Args:
        text: Event text to analyze (title + raw_text)
    
    Returns:
        Tuple of (has_high_impact, matched_patterns)
    """
    text_upper = text.upper()
    
    # Operational context words that indicate real incidents
    operational_nouns = ["PLANT", "FACILITY", "WAREHOUSE", "PORT", "TERMINAL", 
                        "REFINERY", "DC", "DISTRIBUTION", "LOGISTICS", "SHIPMENT",
                        "LANE", "RAIL", "TRUCK", "CARRIER"]
    
    # High-impact patterns (keyword + operational context or location/time)
    patterns = [
        # Spill patterns
        (r"\b(SPILL|LEAK)\b.*\b(PLANT|FACILITY|WAREHOUSE|PORT|TERMINAL|REFINERY|DC)\b", ["SPILL"]),
        (r"\b(PLANT|FACILITY|WAREHOUSE|PORT|TERMINAL|REFINERY|DC)\b.*\b(SPILL|LEAK)\b", ["SPILL"]),
        
        # Strike patterns
        (r"\b(STRIKE|WALKOUT)\b.*\b(PLANT|FACILITY|WAREHOUSE|PORT|TERMINAL|REFINERY|DC|RAIL|TRUCK|CARRIER)\b", ["STRIKE"]),
        (r"\b(PLANT|FACILITY|WAREHOUSE|PORT|TERMINAL|REFINERY|DC|RAIL|TRUCK|CARRIER)\b.*\b(STRIKE|WALKOUT)\b", ["STRIKE"]),
        
        # Closure patterns
        (r"\b(CLOSURE|CLOSED|SHUTDOWN|SHUT\s+DOWN)\b.*\b(PLANT|FACILITY|WAREHOUSE|PORT|TERMINAL|REFINERY|DC)\b", ["CLOSURE"]),
        (r"\b(PLANT|FACILITY|WAREHOUSE|PORT|TERMINAL|REFINERY|DC)\b.*\b(CLOSURE|CLOSED|SHUTDOWN|SHUT\s+DOWN)\b", ["CLOSURE"]),
        
        # Fire/explosion patterns
        (r"\b(FIRE|EXPLOSION)\b.*\b(PLANT|FACILITY|WAREHOUSE|PORT|TERMINAL|REFINERY|DC)\b", ["FIRE"]),
        (r"\b(PLANT|FACILITY|WAREHOUSE|PORT|TERMINAL|REFINERY|DC)\b.*\b(FIRE|EXPLOSION)\b", ["FIRE"]),
    ]
    
    matched_patterns = []
    for pattern, keywords in patterns:
        if re.search(pattern, text_upper):
            matched_patterns.extend(keywords)
    
    # Also check for standalone high-impact keywords if we have location/time signals
    # (city/state in text, or facility IDs, or dates)
    has_location_signal = bool(
        re.search(r"\b([A-Z][a-z]+),\s*([A-Z]{2}|[A-Z][a-z]+)\b", text) or  # City, State
        re.search(r"\b(PLANT-|DC-|FACILITY-)\w+\b", text_upper) or  # Facility IDs
        re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text)  # Dates
    )
    
    standalone_keywords = ["SPILL", "STRIKE", "CLOSURE", "SHUTDOWN", "FIRE", "EXPLOSION"]
    for keyword in standalone_keywords:
        if keyword in text_upper and has_location_signal:
            if keyword not in matched_patterns:
                matched_patterns.append(keyword)
    
    return len(matched_patterns) > 0, matched_patterns


def _compute_max_allowed_classification(
    event: Dict,
    impact_score: int,
    breakdown: List[str],
    trust_tier: int,
    quality_config: Dict[str, Any],
) -> Tuple[int, List[str], int]:
    """
    Compute maximum allowed classification based on evidence quality (caps-first model).
    
    This function determines the ceiling for classification based on:
    1. Network linking confidence
    2. Facility match provenance (ambiguous vs unambiguous)
    3. Compensating factors (trust tier, keywords, impact score)
    4. High-impact factor validation
    
    Policy: Quality validation is authoritative (Policy B).
    classification_min_by_source_policy can be applied after this, but quality caps are final.
    
    Args:
        event: Event dict with link_confidence, facilities, etc.
        impact_score: Calculated impact score (0-10)
        breakdown: Impact score breakdown list
        trust_tier: Source trust tier (1-3)
        quality_config: Alert quality configuration dict
    
    Returns:
        Tuple of (max_allowed_classification, reasoning, high_impact_factors_count)
    """
    reasoning = []
    
    # Load thresholds
    MIN_CONF_CLASS_1 = quality_config["min_confidence_class_1"]
    MIN_CONF_CLASS_2 = quality_config["min_confidence_class_2"]
    MIN_CONF_AMBIG = quality_config["min_confidence_ambiguous"]
    
    # Extract confidence scores (FIXED: default to 0.0, not 1.0)
    link_confidence = event.get("link_confidence", {})
    facility_conf = link_confidence.get("facility", 0.0)  # FIXED: 0.0 default
    lane_conf = link_confidence.get("lanes", 0.0)
    shipment_conf = link_confidence.get("shipments", 0.0)
    
    # Get provenance
    link_provenance = event.get("link_provenance", {})
    facility_provenance = link_provenance.get("facility", "")
    
    # Check network links
    has_facilities = bool(event.get("facilities"))
    has_lanes = bool(event.get("lanes"))
    has_shipments = bool(event.get("shipments"))
    
    # Detect high-impact keywords (improved detection)
    text = f"{event.get('title', '')} {event.get('raw_text', '')}"
    has_high_impact_keyword, matched_keywords = _detect_high_impact_keywords(text)
    
    # Count high-impact factors for validation
    high_impact_factors = sum([
        any("criticality_score >= 7" in b for b in breakdown),
        any("volume_score >= 7" in b for b in breakdown),
        any("Priority shipments" in b for b in breakdown),
        has_high_impact_keyword,
    ])
    
    # Start with conservative cap
    max_class = 0
    
    # Strategy 1: No network links
    if not has_facilities:
        if has_high_impact_keyword and trust_tier >= 2:
            # High-impact keyword from trusted source - allow Interesting (0) only
            max_class = 0
            reasoning.append(
                f"No network links found; high-impact keyword detected "
                f"({', '.join(matched_keywords)}) but requires network match for higher classification"
            )
        else:
            max_class = 0
            reasoning.append("No network links found")
        return max_class, reasoning, high_impact_factors
    
    # Strategy 2: Ambiguous facility matches (strictest)
    if facility_provenance == "CITY_STATE_AMBIGUOUS":
        if facility_conf < MIN_CONF_AMBIG:
            # Below ambiguous threshold - cap at 0
            max_class = 0
            reasoning.append(
                f"Ambiguous facility match (confidence {facility_conf:.2f} < {MIN_CONF_AMBIG}) "
                f"without sufficient evidence"
            )
            return max_class, reasoning, high_impact_factors
        
        # At or above ambiguous threshold - need strong compensating factors
        compensating_evidence = []
        
        # Trust tier 3 is one signal
        if trust_tier == 3:
            compensating_evidence.append("high-trust source")
        
        # High-impact keyword is another signal
        if has_high_impact_keyword:
            compensating_evidence.append(f"high-impact keyword ({', '.join(matched_keywords)})")
        
        # Strong network signals (non-ambiguous lanes/shipments or multiple facilities)
        if has_lanes and lane_conf >= 0.70:
            compensating_evidence.append("strong lane links")
        if has_shipments and shipment_conf >= 0.60:
            compensating_evidence.append("strong shipment links")
        if len(event.get("facilities", [])) > 1:
            compensating_evidence.append("multiple facility references")
        
        # Very high impact score
        if impact_score >= 6:
            compensating_evidence.append("very high impact score")
        
        # Require at least 2 compensating factors for Class 1, 3+ for Class 2
        if len(compensating_evidence) >= 3:
            max_class = 1  # Cap at 1 for ambiguous
            reasoning.append(
                f"Ambiguous facility match (confidence {facility_conf:.2f}) compensated by: "
                f"{', '.join(compensating_evidence)} - capped at classification 1"
            )
        elif len(compensating_evidence) >= 2:
            max_class = 1  # Cap at 1 for ambiguous
            reasoning.append(
                f"Ambiguous facility match (confidence {facility_conf:.2f}) compensated by: "
                f"{', '.join(compensating_evidence)} - capped at classification 1"
            )
        else:
            max_class = 0
            reasoning.append(
                f"Ambiguous facility match (confidence {facility_conf:.2f}) with insufficient "
                f"compensating factors ({len(compensating_evidence)} found, requires 2+)"
            )
        return max_class, reasoning, high_impact_factors
    
    # Strategy 3: Non-ambiguous matches with confidence thresholds
    if facility_conf >= MIN_CONF_CLASS_2:
        # High confidence - can support Class 2, but validate high-impact factors
        if high_impact_factors >= 2:
            max_class = 2
            reasoning.append(
                f"High facility confidence ({facility_conf:.2f} >= {MIN_CONF_CLASS_2}) "
                f"with {high_impact_factors} high-impact factors"
            )
        elif high_impact_factors == 1 and impact_score >= 5:
            # Single factor but very high score - allow Class 2
            max_class = 2
            reasoning.append(
                f"High facility confidence ({facility_conf:.2f}) with single high-impact factor "
                f"but very high impact score ({impact_score})"
            )
        else:
            # High confidence but insufficient factors - cap at 1
            max_class = 1
            reasoning.append(
                f"High facility confidence ({facility_conf:.2f}) but insufficient high-impact factors "
                f"({high_impact_factors} found, requires 2+ for classification 2)"
            )
    elif facility_conf >= MIN_CONF_CLASS_1:
        # Medium confidence - can support Class 1
        # Trust tier can help but not fully compensate
        if trust_tier == 3 and has_high_impact_keyword:
            # High trust + keyword - allow Class 1
            max_class = 1
            reasoning.append(
                f"Medium facility confidence ({facility_conf:.2f} >= {MIN_CONF_CLASS_1}) "
                f"compensated by high-trust source and high-impact keyword"
            )
        elif trust_tier >= 2:
            # Medium trust - allow Class 1
            max_class = 1
            reasoning.append(
                f"Medium facility confidence ({facility_conf:.2f} >= {MIN_CONF_CLASS_1}) "
                f"with trust tier {trust_tier}"
            )
        else:
            # Low trust - cap at 0
            max_class = 0
            reasoning.append(
                f"Medium facility confidence ({facility_conf:.2f} >= {MIN_CONF_CLASS_1}) "
                f"but low trust tier ({trust_tier}) - insufficient for classification 1"
            )
    else:
        # Low confidence - cap at 0 unless strong compensating factors
        if trust_tier == 3 and has_high_impact_keyword and impact_score >= 4:
            # Very strong compensating factors - allow Class 0 (Interesting)
            max_class = 0
            reasoning.append(
                f"Low facility confidence ({facility_conf:.2f} < {MIN_CONF_CLASS_1}) "
                f"but strong compensating factors (tier 3, keyword, high impact) - "
                f"classification 0 only"
            )
        else:
            max_class = 0
            reasoning.append(
                f"Low facility confidence ({facility_conf:.2f} < {MIN_CONF_CLASS_1}) "
                f"without sufficient compensating factors"
            )
    
    return max_class, reasoning, high_impact_factors


def _merge_scope(existing_scope_json: str | None, new_scope: Dict[str, object]) -> Dict[str, object]:
    if not existing_scope_json:
        return new_scope
    
    try:
        existing_scope = json.loads(existing_scope_json) or {}
    except (json.JSONDecodeError, TypeError):
        existing_scope = {}
    
    merged_scope = {}
    for key in ("facilities", "lanes", "shipments"):
        previous = existing_scope.get(key, [])
        current = new_scope.get(key, [])
        previous_list = previous if isinstance(previous, list) else []
        current_list = current if isinstance(current, list) else []
        merged_scope[key] = _dedupe_preserve_order(previous_list + current_list)
    
    merged_scope["shipments_total_linked"] = max(
        int(existing_scope.get("shipments_total_linked", len(merged_scope["shipments"])) or 0),
        int(new_scope.get("shipments_total_linked", len(new_scope.get("shipments", []))) or 0),
    )
    merged_scope["shipments_truncated"] = bool(
        existing_scope.get("shipments_truncated") or new_scope.get("shipments_truncated")
    )
    return merged_scope


def build_basic_alert(
    event: Dict,
    session: Optional[Session] = None,
    *,
    determinism_mode: str = "live",
    determinism_context: Optional[Dict[str, Any]] = None,
    incident_dest_dir: str | Path = "output/incidents",
) -> HardstopAlert:
    """
    Build a minimal alert for a single event.
    
    Classification is determined by network impact score, not just input severity_guess.
    This makes classification deterministic and testable.
    
    Note: The alert model includes deprecated fields for backward compatibility:
    - `priority` mirrors `classification` (will be removed in v0.4)
    - `diagnostics` mirrors `evidence.diagnostics` (will be removed in v0.4)
    
    New code should use `classification` and `evidence.diagnostics`.

    Args:
        event: Event dict with facilities, lanes, shipments populated
        session: Optional SQLAlchemy session for network impact scoring
                 If None, falls back to severity_guess
    """
    alert_id = new_alert_id()
    root_event_id = event["event_id"]

    summary = event.get("title", "Risk event detected")
    risk_type = event.get("event_type", "GENERAL")
    
    # Extract v0.7 fields from event (already injected by normalizer)
    trust_tier = event.get("trust_tier", 2)  # Default 2 if absent
    weighting_bias = event.get("weighting_bias", 0)  # Default 0 if absent
    classification_min_by_source_policy = event.get("classification_floor", 0)  # Renamed for clarity (Policy B)
    tier = event.get("tier")
    source_id = event.get("source_id")
    
    # Initialize reasoning list early (will be populated by validation)
    reasoning = []
    
    # Calculate classification based on network impact
    evidence = None
    diagnostics_payload = None
    if session:
        scoring_now = event.get("scoring_now")
        if not isinstance(scoring_now, datetime):
            scoring_now = None

        impact_score, breakdown, rationale = calculate_network_impact_score(
            event,
            session,
            trust_tier=trust_tier,
            weighting_bias=weighting_bias,
            now=scoring_now,
        )
        classification = map_score_to_classification(impact_score)
        
        # Load quality config
        quality_config = load_alert_quality_config()
        
        # NEW: Compute quality cap (Policy B: quality is authoritative)
        max_allowed_class, quality_reasoning, high_impact_factors = _compute_max_allowed_classification(
            event=event,
            impact_score=impact_score,
            breakdown=breakdown,
            trust_tier=trust_tier,
            quality_config=quality_config,
        )
        
        # Extract confidence for metadata
        link_confidence = event.get("link_confidence", {})
        facility_conf = link_confidence.get("facility", 0.0)
        link_provenance = event.get("link_provenance", {})
        facility_provenance = link_provenance.get("facility", "")
        
        # Store quality validation metadata for diagnostics
        quality_validation_metadata = {
            "max_allowed_classification": max_allowed_class,
            "high_impact_factors_count": high_impact_factors,
            "facility_confidence": facility_conf,
            "facility_provenance": facility_provenance,
            "applied_policy": "B" if quality_config["allow_quality_override_floor"] else "A",
        }
        
        # Apply quality cap
        original_classification = classification
        classification = min(classification, max_allowed_class)
        if classification != original_classification:
            reasoning.extend(quality_reasoning)
        
        # Apply source policy minimum (Policy B: can raise but not above quality cap)
        if quality_config["allow_quality_override_floor"]:
            # Quality cap is authoritative, but source policy can raise from 0
            original_after_quality = classification
            classification = max(classification, classification_min_by_source_policy)
            if classification == classification_min_by_source_policy and original_after_quality < classification_min_by_source_policy:
                reasoning.append(
                    f"Source policy minimum: {classification_min_by_source_policy} "
                    f"(raised from quality-capped {original_after_quality})"
                )
        else:
            # Policy A: floor is final (not recommended but configurable)
            classification = max(classification, classification_min_by_source_policy)
            if classification != original_classification:
                reasoning.append(
                    f"Source policy minimum enforced: {classification_min_by_source_policy} "
                    f"(overrides quality cap of {max_allowed_class})"
                )
        
        classification_source = f"network_impact_score={impact_score}, quality_cap={max_allowed_class}"
        
        # Build evidence object (non-decisional)
        diagnostics = AlertDiagnostics(
            link_confidence=event.get("link_confidence", {}),
            link_provenance=event.get("link_provenance", {}),
            shipments_total_linked=event.get("shipments_total_linked", len(event.get("shipments", []))),
            shipments_truncated=event.get("shipments_truncated", False),
            impact_score=impact_score,
            impact_score_breakdown=breakdown,
            impact_score_rationale=rationale,
            quality_validation=quality_validation_metadata,
        )
        diagnostics_payload = diagnostics.model_dump()
        evidence = AlertEvidence(
            diagnostics=diagnostics,
            linking_notes=event.get("linking_notes", []),
        )
    else:
        # Fallback to severity_guess if no session provided
        classification = event.get("severity_guess", 1)
        classification_source = "severity_guess (no network data)"
        # Initialize evidence for correlation notes even without session
        evidence = AlertEvidence(
            diagnostics=None,
            linking_notes=event.get("linking_notes", []),
        )

    scope = AlertScope(
        facilities=event.get("facilities", []),
        lanes=event.get("lanes", []),
        shipments=event.get("shipments", []),
    )
    
    # Prepare scope JSON for database storage
    scope_payload: Dict[str, object] = {
        "facilities": scope.facilities,
        "lanes": scope.lanes,
        "shipments": scope.shipments,
        "shipments_total_linked": event.get("shipments_total_linked", len(scope.shipments)),
        "shipments_truncated": event.get("shipments_truncated", False),
    }
    scope_json = json.dumps(scope_payload)

    impact_assessment = AlertImpactAssessment(
        qualitative_impact=[event.get("raw_text", "")[:280]],
    )

    # Add base reasoning (prepend to quality reasoning if present)
    base_reasoning = [
        f"Event type: {risk_type}",
        f"Classification: {classification} (from {classification_source})",
        "Scope derived from network entity matching.",
    ]
    reasoning = base_reasoning + reasoning

    recommended_actions = [
        AlertAction(
            id="ACT-VERIFY",
            description="Verify status with responsible operator or facility.",
            owner_role="Operations / Supply Chain",
            due_within_hours=4,
        )
    ]

    # Correlation: Build key (always - it's a property of the event)
    correlation_key = build_correlation_key(event)
    existing_alert = None
    
    # Correlation persistence: only when session is available
    # Note: Correlation key is always computed for debugging/replay,
    # but persistence and deduplication require database session
    if session is not None:
        existing_alert = find_recent_alert_by_key(session, correlation_key, within_days=7)
        
        if existing_alert:
            # Update existing alert (v0.7: store tier/source_id/trust_tier from latest event)
            merged_scope_payload = _merge_scope(existing_alert.scope_json, scope_payload)
            scope.facilities = merged_scope_payload.get("facilities", scope.facilities)
            scope.lanes = merged_scope_payload.get("lanes", scope.lanes)
            scope.shipments = merged_scope_payload.get("shipments", scope.shipments)
            scope_payload = merged_scope_payload
            scope_json = json.dumps(scope_payload)
            
            update_existing_alert_row(
                session,
                existing_alert,
                new_summary=summary,
                new_classification=classification,
                root_event_id=root_event_id,
                correlation_action="UPDATED",
                impact_score=impact_score if session else None,
                scope_json=scope_json,  # Update scope with latest event data
                diagnostics_json=json.dumps(diagnostics_payload, default=str) if diagnostics_payload else None,
                tier=tier,  # v0.7: update tier from latest event
                source_id=source_id,  # v0.7: update source_id from latest event
                trust_tier=trust_tier,  # v0.7: update trust_tier from latest event
            )
            session.commit()
            
            # Use existing alert ID and add structured correlation info
            alert_id = existing_alert.alert_id
            if evidence:
                evidence.correlation = {
                    "key": correlation_key,
                    "action": "UPDATED",
                    "alert_id": existing_alert.alert_id,
                }
                # Add source metadata if available (v0.7: includes trust_tier)
                if event.get("source_id"):
                    evidence.source = {
                        "id": event.get("source_id"),
                        "tier": event.get("tier"),
                        "raw_id": event.get("raw_id"),
                        "url": event.get("url"),
                        "trust_tier": trust_tier,
                    }
                evidence.linking_notes = (evidence.linking_notes or []) + [
                    f"Correlated to existing alert_id={existing_alert.alert_id} via key={correlation_key}"
                ]
        else:
            # Create new alert
            reasoning_text = "\n".join(reasoning) if reasoning else None
            actions_text = json.dumps([a.model_dump() for a in recommended_actions]) if recommended_actions else None
            
            upsert_new_alert_row(
                session,
                alert_id=alert_id,
                summary=summary,
                risk_type=risk_type,
                classification=classification,
                status="OPEN",
                reasoning=reasoning_text,
                recommended_actions=actions_text,
                root_event_id=root_event_id,
                correlation_key=correlation_key,
                correlation_action="CREATED",
                impact_score=impact_score if session else None,
                scope_json=scope_json,
                diagnostics_json=json.dumps(diagnostics_payload, default=str) if diagnostics_payload else None,
                tier=tier,  # v0.7: store tier for brief efficiency
                source_id=source_id,  # v0.7: store source_id for UI efficiency
                trust_tier=trust_tier,  # v0.7: store trust_tier
            )
            session.commit()
            
            if evidence:
                evidence.correlation = {
                    "key": correlation_key,
                    "action": "CREATED",
                    "alert_id": alert_id,
                }
                # Add source metadata if available (v0.7: includes trust_tier)
                if event.get("source_id"):
                    evidence.source = {
                        "id": event.get("source_id"),
                        "tier": event.get("tier"),
                        "raw_id": event.get("raw_id"),
                        "url": event.get("url"),
                        "trust_tier": trust_tier,
                    }
                evidence.linking_notes = (evidence.linking_notes or []) + [
                    f"Created new correlated alert via key={correlation_key}"
                ]
    else:
        # No session: still include key in evidence for debugging/replay
        if evidence:
            evidence.correlation = {
                "key": correlation_key,
                "action": None,  # Not persisted
                "alert_id": None,
            }
            # Add source metadata if available (v0.7: includes trust_tier)
            if event.get("source_id"):
                evidence.source = {
                    "id": event.get("source_id"),
                    "tier": event.get("tier"),
                    "raw_id": event.get("raw_id"),
                    "url": event.get("url"),
                    "trust_tier": trust_tier,
                }

    incident_artifact, incident_ref, incident_path = build_incident_evidence_artifact(
        alert_id=alert_id,
        event=event,
        correlation_key=correlation_key,
        existing_alert=existing_alert,
        window_hours=7 * 24,
        dest_dir=incident_dest_dir,
        generated_at=event.get("event_time_utc") or event.get("published_at_utc"),
        filename_basename=f"{alert_id}__{event.get('event_id', 'event')}__{correlation_key.replace('|', '_')}",
        determinism_mode=determinism_mode,
        determinism_context=determinism_context if determinism_mode == "pinned" else None,
    )
    if evidence is None:
        evidence = AlertEvidence()
    evidence.incident_evidence = IncidentEvidenceSummary(
        artifact_hash=incident_ref.hash,
        artifact_path=str(incident_path),
        merge_reasons=incident_artifact.merge_reasons,
        merge_summary=incident_artifact.merge_summary,
        inputs=incident_artifact.inputs,
    )
    evidence.linking_notes = _dedupe_preserve_order((evidence.linking_notes or []) + incident_artifact.merge_summary)

    # Calculate overall confidence score (weighted average of link confidences)
    link_confidence = event.get("link_confidence", {})
    facility_conf = link_confidence.get("facility", 0.0)  # FIXED: 0.0 default
    lane_conf = link_confidence.get("lanes", 0.0)
    shipment_conf = link_confidence.get("shipments", 0.0)
    
    # Weighted average: facility is most important
    if facility_conf > 0:
        overall_confidence = (facility_conf * 0.6 + lane_conf * 0.25 + shipment_conf * 0.15)
    elif lane_conf > 0:
        overall_confidence = lane_conf * 0.5  # Lower if no facility match
    else:
        overall_confidence = 0.0

    return HardstopAlert(
        alert_id=alert_id,
        risk_type=risk_type,
        classification=classification,
        status="OPEN",
        summary=summary,
        root_event_id=root_event_id,
        scope=scope,
        impact_assessment=impact_assessment,
        reasoning=reasoning,
        recommended_actions=recommended_actions,
        evidence=evidence,
        confidence_score=overall_confidence,
    )
