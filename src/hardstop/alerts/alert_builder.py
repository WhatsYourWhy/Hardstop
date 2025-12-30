import json
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..utils.id_generator import new_alert_id
from .alert_models import (
    AlertAction,
    AlertDiagnostics,
    AlertEvidence,
    AlertImpactAssessment,
    AlertScope,
    HardstopAlert,
)
from .correlation import build_correlation_key
from .impact_scorer import calculate_network_impact_score, map_score_to_classification
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


def build_basic_alert(event: Dict, session: Optional[Session] = None) -> HardstopAlert:
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
    classification_floor = event.get("classification_floor", 0)  # Default 0 if absent
    tier = event.get("tier")
    source_id = event.get("source_id")
    
    # Calculate classification based on network impact
    evidence = None
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
        
        # Enforce classification floor (v0.7)
        original_classification = classification
        classification = max(classification, classification_floor)
        if classification != original_classification:
            reasoning.append(f"Classification floor: {classification_floor} (source policy) - raised from {original_classification}")
        
        classification_source = f"network_impact_score={impact_score}"
        
        # Build evidence object (non-decisional)
        diagnostics = AlertDiagnostics(
            link_confidence=event.get("link_confidence", {}),
            link_provenance=event.get("link_provenance", {}),
            shipments_total_linked=event.get("shipments_total_linked", len(event.get("shipments", []))),
            shipments_truncated=event.get("shipments_truncated", False),
            impact_score=impact_score,
            impact_score_breakdown=breakdown,
            impact_score_rationale=rationale,
        )
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

    reasoning = [
        f"Event type: {risk_type}",
        f"Classification: {classification} (from {classification_source})",
        "Scope derived from network entity matching.",
    ]

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
    
    # Correlation persistence: only when session is available
    # Note: Correlation key is always computed for debugging/replay,
    # but persistence and deduplication require database session
    if session is not None:
        existing = find_recent_alert_by_key(session, correlation_key, within_days=7)
        
        if existing:
            # Update existing alert (v0.7: store tier/source_id/trust_tier from latest event)
            merged_scope_payload = _merge_scope(existing.scope_json, scope_payload)
            scope.facilities = merged_scope_payload.get("facilities", scope.facilities)
            scope.lanes = merged_scope_payload.get("lanes", scope.lanes)
            scope.shipments = merged_scope_payload.get("shipments", scope.shipments)
            scope_payload = merged_scope_payload
            scope_json = json.dumps(scope_payload)
            
            update_existing_alert_row(
                session,
                existing,
                new_summary=summary,
                new_classification=classification,
                root_event_id=root_event_id,
                correlation_action="UPDATED",
                impact_score=impact_score if session else None,
                scope_json=scope_json,  # Update scope with latest event data
                tier=tier,  # v0.7: update tier from latest event
                source_id=source_id,  # v0.7: update source_id from latest event
                trust_tier=trust_tier,  # v0.7: update trust_tier from latest event
            )
            session.commit()
            
            # Use existing alert ID and add structured correlation info
            alert_id = existing.alert_id
            if evidence:
                evidence.correlation = {
                    "key": correlation_key,
                    "action": "UPDATED",
                    "alert_id": existing.alert_id,
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
                    f"Correlated to existing alert_id={existing.alert_id} via key={correlation_key}"
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
    )
