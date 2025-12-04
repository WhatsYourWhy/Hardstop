from typing import Dict


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

