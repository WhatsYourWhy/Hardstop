import json
from pathlib import Path

from hardstop.alerts.alert_builder import build_basic_alert
from hardstop.config.loader import load_config
from hardstop.database.migrate import ensure_alert_correlation_columns
from hardstop.database.sqlite_client import session_context
from hardstop.parsing.network_linker import link_event_to_network
from hardstop.parsing.normalizer import normalize_event
from hardstop.utils.logging import get_logger

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
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
    
    # Ensure correlation columns exist (migration)
    ensure_alert_correlation_columns(sqlite_path)
    
    # Use context manager for proper session lifecycle
    with session_context(sqlite_path) as session:
        event = link_event_to_network(event, session=session)
        
        # Build alert with network impact scoring and correlation
        # Note: alert_builder handles its own commits
        alert = build_basic_alert(event, session=session)

    logger.info("Built alert:")
    print(alert.model_dump_json(indent=2))
    
    # Print correlation and linking notes
    if alert.evidence and alert.evidence.linking_notes:
        logger.info("Linking and correlation notes:")
        for n in alert.evidence.linking_notes:
            logger.info(f"- {n}")
    
    # Also print event-level linking notes for debugging
    notes = event.get("linking_notes", [])
    if notes:
        logger.info("Event linking notes:")
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

