import json
import re
from typing import Dict, Optional, Tuple

from hardstop.ops.run_record import (
    ArtifactRef,
    artifact_hash,
    canonical_dumps,
    emit_run_record,
    resolve_config_snapshot,
)
from hardstop.utils.time import utc_now_z
from hardstop.utils.id_generator import new_event_id


def extract_event_type(text: str, title: Optional[str] = None) -> str:
    """
    Extract event type from text using deterministic heuristics.
    
    Args:
        text: Event text content
        title: Optional title (searched first)
        
    Returns:
        Event type: WEATHER, SPILL, STRIKE, CLOSURE, REG, RECALL, OTHER
    """
    combined_text = ""
    if title:
        combined_text += title.lower() + " "
    if text:
        combined_text += text.lower()
    
    combined_text = combined_text.lower()
    
    # Weather keywords
    weather_keywords = [
        "hurricane", "tornado", "flood", "storm", "blizzard", "snow", "ice",
        "warning", "watch", "alert", "severe weather", "thunderstorm",
        "wind", "hail", "freeze", "frost", "heat", "drought"
    ]
    if any(kw in combined_text for kw in weather_keywords):
        return "WEATHER"
    
    # Spill keywords
    spill_keywords = [
        "spill", "leak", "contamination", "chemical release", "hazardous material",
        "oil spill", "toxic", "pollution"
    ]
    if any(kw in combined_text for kw in spill_keywords):
        return "SPILL"
    
    # Strike keywords
    strike_keywords = [
        "strike", "labor dispute", "work stoppage", "union", "walkout",
        "picketing", "lockout"
    ]
    if any(kw in combined_text for kw in strike_keywords):
        return "STRIKE"
    
    # Closure keywords
    closure_keywords = [
        "closure", "closed", "shutdown", "shut down", "suspended", "halted",
        "blocked", "barricade", "evacuation", "emergency closure"
    ]
    if any(kw in combined_text for kw in closure_keywords):
        return "CLOSURE"
    
    # Regulatory keywords
    reg_keywords = [
        "regulation", "regulatory", "compliance", "violation", "fine", "penalty",
        "inspection", "audit", "sanction", "ban", "prohibition"
    ]
    if any(kw in combined_text for kw in reg_keywords):
        return "REG"
    
    # Recall keywords
    recall_keywords = [
        "recall", "recalled", "withdrawal", "removed from market", "voluntary recall"
    ]
    if any(kw in combined_text for kw in recall_keywords):
        return "RECALL"
    
    return "OTHER"


def extract_location_hint(payload: Dict, geo: Optional[Dict] = None) -> Optional[str]:
    """
    Extract location hint from payload or geo metadata.
    
    Args:
        payload: Raw payload dict
        geo: Optional geo metadata from source config
        
    Returns:
        Location hint string or None
    """
    # Try geo metadata first
    if geo:
        parts = []
        if geo.get("city"):
            parts.append(geo["city"])
        if geo.get("state"):
            parts.append(geo["state"])
        if geo.get("country"):
            parts.append(geo["country"])
        if parts:
            return ", ".join(parts)
    
    # Try payload fields
    location_fields = ["areaDesc", "location", "area", "region", "city", "state"]
    for field in location_fields:
        if field in payload and payload[field]:
            return str(payload[field])
    
    # Try to extract from text
    text_fields = ["description", "summary", "content", "title", "body"]
    for field in text_fields:
        if field in payload and payload[field]:
            text = str(payload[field])
            # Look for "City, State" pattern
            match = re.search(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s+([A-Z]{2}|[A-Z][a-z]+)\b', text)
            if match:
                return f"{match.group(1)}, {match.group(2)}"
    
    return None


def normalize_event(raw: Dict) -> Dict:
    """
    Turn a raw JSON event into a canonical internal event dict.

    This is intentionally simple for v1.
    """
    return {
        "event_id": raw.get("event_id") or raw.get("id") or "EVT-DEMO",
        "source_type": raw.get("type", "NEWS"),
        "source_name": raw.get("source", "UNKNOWN"),
        "title": raw.get("title", ""),
        "raw_text": raw.get("body", ""),
        "event_type": raw.get("event_type", "UNKNOWN"),
        "severity_guess": raw.get("severity_guess", 2),
        "facilities": raw.get("facilities", []),
        "lanes": raw.get("lanes", []),
        "shipments": raw.get("shipments", []),
    }


def normalize_external_event(
    raw_item_candidate: Dict,
    source_id: str,
    tier: str,
    raw_id: str,
    source_config: Optional[Dict] = None,
    *,
    mode: str = "strict",
    emit_record: bool = True,
    config_snapshot: Optional[Dict] = None,
    canonicalize_time=None,
    run_id: Optional[str] = None,
    dest_dir: str = "run_records",
) -> Dict:
    """
    Normalize external RawItemCandidate to internal event dict and emit a RunRecord.
    
    Args:
        raw_item_candidate: RawItemCandidate dict (from adapter)
        source_id: Source ID
        tier: Tier (global, regional, local)
        raw_id: Raw item ID
        source_config: Optional source config (for geo metadata and v0.7 trust fields)
        mode: strict/best-effort
        emit_record: If False, return the normalized event without recording provenance.
        config_snapshot: Optional config snapshot; defaults to resolved runtime config.
        canonicalize_time: Optional timestamp canonicalizer for deterministic tests.
        run_id: Optional fixed RunRecord id (for replays)
        dest_dir: Directory where RunRecord JSON is written.
        
    Returns:
        Normalized event dict compatible with existing pipeline
        Includes v0.7 fields: tier, trust_tier, classification_floor, weighting_bias
    """
    normalizer = CanonicalizeExternalEventOperator(
        mode=mode,
        config_snapshot=config_snapshot,
        canonicalize_time=canonicalize_time,
        run_id=run_id,
        dest_dir=dest_dir,
    )
    event, _ = normalizer.run(
        raw_item_candidate=raw_item_candidate,
        source_id=source_id,
        tier=tier,
        raw_id=raw_id,
        source_config=source_config,
        emit_record=emit_record,
    )
    return event


def _build_event_payload(
    raw_item_candidate: Dict,
    source_id: str,
    tier: str,
    raw_id: str,
    source_config: Optional[Dict] = None,
) -> Dict:
    payload = raw_item_candidate.get("payload", {})
    title = raw_item_candidate.get("title") or payload.get("title") or ""
    
    # Extract text content
    text_parts = []
    if title:
        text_parts.append(title)
    for field in ["summary", "description", "content", "body"]:
        if field in payload and payload[field]:
            text_parts.append(str(payload[field]))
    raw_text = " ".join(text_parts)
    
    # Extract event type
    event_type = extract_event_type(raw_text, title)
    
    # Extract location hint
    geo = source_config.get("geo") if source_config else None
    location_hint = extract_location_hint(payload, geo)
    
    # Extract entities (simple heuristic - can be enhanced later)
    entities = {}
    if location_hint:
        entities["location"] = location_hint
    
    # Extract v0.7 trust weighting fields from source_config (with defaults)
    trust_tier = source_config.get("trust_tier", 2) if source_config else 2
    classification_floor = source_config.get("classification_floor", 0) if source_config else 0
    weighting_bias = source_config.get("weighting_bias", 0) if source_config else 0
    
    event_id = (
        raw_item_candidate.get("event_id")
        or raw_item_candidate.get("canonical_id")
        or raw_item_candidate.get("raw_id")
        or new_event_id()
    )
    
    # Build event dict
    return {
        "event_id": event_id,
        "source_type": "EXTERNAL",
        "source_name": source_id,
        "source_id": source_id,
        "raw_id": raw_id,
        "tier": tier,  # v0.7: injected at normalization time
        "trust_tier": trust_tier,  # v0.7: injected at normalization time (default 2)
        "classification_floor": classification_floor,  # v0.7: injected at normalization time (default 0)
        "weighting_bias": weighting_bias,  # v0.7: injected at normalization time (default 0)
        "title": title,
        "raw_text": raw_text,
        "event_type": event_type,
        "event_time_utc": raw_item_candidate.get("published_at_utc"),
        "severity_guess": 1,  # Default to relevant
        "location_hint": location_hint,
        "entities_json": json.dumps(entities) if entities else None,
        "event_payload_json": json.dumps(payload, default=str),
        "url": raw_item_candidate.get("url"),  # Include URL for source metadata
        "facilities": [],
        "lanes": [],
        "shipments": [],
    }


def _event_bytes(payload: Dict) -> int:
    return len(canonical_dumps(payload).encode("utf-8"))


class CanonicalizeExternalEventOperator:
    """Explicit canonicalization operator with RunRecord emission."""

    operator_id = "canonicalization.normalize@1.0.0"
    input_kind = "RawItemCandidate"
    output_kind = "SignalCanonical"
    output_schema = "signals/v1"

    def __init__(
        self,
        *,
        mode: str = "strict",
        config_snapshot: Optional[Dict] = None,
        canonicalize_time=None,
        run_id: Optional[str] = None,
        dest_dir: str = "run_records",
    ) -> None:
        self.mode = mode
        self.config_snapshot = config_snapshot or resolve_config_snapshot()
        self.canonicalize_time = canonicalize_time
        self.run_id = run_id
        self.dest_dir = dest_dir

    def run(
        self,
        raw_item_candidate: Dict,
        source_id: str,
        tier: str,
        raw_id: str,
        source_config: Optional[Dict] = None,
        emit_record: bool = True,
    ) -> Tuple[Dict, Optional[object]]:
        started_at = utc_now_z()
        event = _build_event_payload(
            raw_item_candidate=raw_item_candidate,
            source_id=source_id,
            tier=tier,
            raw_id=raw_id,
            source_config=source_config,
        )

        if not emit_record:
            return event, None

        input_ref = ArtifactRef(
            id=f"raw-item:{source_id}:{raw_id}",
            hash=artifact_hash(raw_item_candidate),
            kind=self.input_kind,
            schema="raw-items/v1",
        )
        output_ref = ArtifactRef(
            id=f"event:{event['event_id']}",
            hash=artifact_hash(event),
            kind=self.output_kind,
            schema=self.output_schema,
            bytes=_event_bytes(event),
        )
        record = emit_run_record(
            operator_id=self.operator_id,
            mode=self.mode,
            run_id=self.run_id,
            started_at=started_at,
            ended_at=utc_now_z(),
            canonicalize_time=self.canonicalize_time,
            config_snapshot=self.config_snapshot,
            input_refs=[input_ref],
            output_refs=[output_ref],
            dest_dir=self.dest_dir,
        )
        return event, record
