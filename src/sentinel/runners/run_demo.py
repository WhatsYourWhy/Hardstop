import json
from pathlib import Path

from sentinel.alerts.alert_builder import build_basic_alert
from sentinel.config.loader import load_config
from sentinel.database.sqlite_client import get_session
from sentinel.parsing.network_linker import link_event_to_network
from sentinel.parsing.normalizer import normalize_event
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


def main() -> None:
    """
    Demo pipeline:

    - load a sample JSON event
    - normalize it
    - link to network data (facilities/shipments)
    - build a basic alert
    - print JSON + markdown representations
    """
    config = load_config()
    
    # Load event
    demo_config = config.get("demo", {})
    event_path = Path(demo_config.get("event_json", "tests/fixtures/event_spill.json"))
    if not event_path.exists():
        raise FileNotFoundError(f"Fixture not found: {event_path}")

    raw = json.loads(event_path.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-DEMO-0001"

    event = normalize_event(raw)
    
    # Link to network data using new linker
    sqlite_path = config.get("storage", {}).get("sqlite_path", "sentinel.db")
    session = get_session(sqlite_path)
    try:
        event = link_event_to_network(event, session=session)
    finally:
        session.close()

    # Build alert with network impact scoring
    alert = build_basic_alert(event, session=session)

    logger.info("Built alert:")
    print(alert.model_dump_json(indent=2))
    
    # Print linking notes for debugging
    notes = event.get("linking_notes", [])
    if notes:
        logger.info("Linking notes:")
        for n in notes:
            logger.info(f"- {n}")
    
    # Print confidence and provenance
    confidence = event.get("link_confidence", {})
    provenance = event.get("link_provenance", {})
    if confidence or provenance:
        logger.info("Link confidence and provenance:")
        if confidence:
            logger.info(f"  Confidence: {confidence}")
        if provenance:
            logger.info(f"  Provenance: {provenance}")
    
    # Print truncation metadata if present
    if event.get("shipments_truncated"):
        logger.info(f"Shipments truncated: {len(event.get('shipments', []))} shown of {event.get('shipments_total_linked', 0)} total")


if __name__ == "__main__":
    main()

