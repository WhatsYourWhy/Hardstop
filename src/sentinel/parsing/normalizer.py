import json
import re
from typing import Dict, Optional

from sentinel.utils.id_generator import new_event_id


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
    text_fields = ["description", "summary", "content", "title"]
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
) -> Dict:
    """
    Normalize external RawItemCandidate to internal event dict.
    
    Args:
        raw_item_candidate: RawItemCandidate dict (from adapter)
        source_id: Source ID
        tier: Tier (global, regional, local)
        raw_id: Raw item ID
        source_config: Optional source config (for geo metadata and v0.7 trust fields)
        
    Returns:
        Normalized event dict compatible with existing pipeline
        Includes v0.7 fields: tier, trust_tier, classification_floor, weighting_bias
    """
    payload = raw_item_candidate.get("payload", {})
    title = raw_item_candidate.get("title") or payload.get("title") or ""
    
    # Extract text content
    text_parts = []
    if title:
        text_parts.append(title)
    for field in ["summary", "description", "content"]:
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
    
    # Build event dict
    event = {
        "event_id": new_event_id(),
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
    
    return event

