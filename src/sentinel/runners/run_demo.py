import json
from pathlib import Path

from sentinel.alerts.alert_builder import build_basic_alert
from sentinel.parsing.entity_extractor import attach_dummy_entities
from sentinel.parsing.normalizer import normalize_event
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


def main() -> None:
    """
    Demo pipeline:

    - load a sample JSON event
    - normalize it
    - attach dummy entities
    - build a basic alert
    - print JSON + markdown representations
    """
    event_path = Path("tests/fixtures/event_spill.json")
    if not event_path.exists():
        raise FileNotFoundError(f"Fixture not found: {event_path}")

    raw = json.loads(event_path.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-DEMO-0001"

    event = normalize_event(raw)
    event = attach_dummy_entities(event)

    alert = build_basic_alert(event)

    logger.info("Built alert:")
    print(alert.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

