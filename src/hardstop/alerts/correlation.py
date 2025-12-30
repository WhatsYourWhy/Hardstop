"""Correlation key building for alert deduplication."""

from typing import Dict, List


def _risk_bucket(event: Dict) -> str:
    """
    Deterministic risk bucket for correlation.
    Prefer normalized event_type; fall back to keyword inference (already used elsewhere).
    """
    et = (event.get("event_type") or "").upper()

    # Keep buckets stable; don't explode taxonomy.
    if "SPILL" in et:
        return "SPILL"
    if "STRIKE" in et:
        return "STRIKE"
    if "CLOSURE" in et:
        return "CLOSURE"
    if "WEATHER" in et:
        return "WEATHER"
    if "REG" in et or "REGULATION" in et:
        return "REG"
    if "SAFETY" in et:
        return "SAFETY"
    if et:
        return et[:24]

    # fallback: keyword scan
    text = f"{event.get('title','')} {event.get('raw_text','')}".lower()
    if "spill" in text:
        return "SPILL"
    if "strike" in text:
        return "STRIKE"
    if "closure" in text or "shut down" in text or "shutdown" in text:
        return "CLOSURE"
    if "storm" in text or "hurricane" in text or "tornado" in text:
        return "WEATHER"
    if "regulation" in text or "rule" in text:
        return "REG"
    return "OTHER"


def _top_or_none(xs: List[str]) -> str:
    """Return first item from sorted set, or 'NONE' if empty."""
    if not xs:
        return "NONE"
    # stable: sorted then first
    return sorted(set(xs))[0]


def build_correlation_key(event: Dict) -> str:
    """
    Create a stable correlation key:
      BUCKET|FACILITY|LANE

    - facility/lane are pulled from event context (post-linking)
    
    Args:
        event: Event dict with facilities, lanes populated (after linking)
        
    Returns:
        Correlation key string in format "BUCKET|FACILITY|LANE"
    """
    bucket = _risk_bucket(event)
    facility = _top_or_none(event.get("facilities", []) or [])
    lane = _top_or_none(event.get("lanes", []) or [])
    return f"{bucket}|{facility}|{lane}"

