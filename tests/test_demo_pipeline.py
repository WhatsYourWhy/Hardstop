import json
from pathlib import Path

from sentinel.alerts.alert_builder import build_basic_alert
from sentinel.parsing.entity_extractor import attach_dummy_entities
from sentinel.parsing.normalizer import normalize_event


def test_demo_pipeline():
    event_path = Path("tests/fixtures/event_spill.json")
    raw = json.loads(event_path.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-TEST-0001"

    event = normalize_event(raw)
    event = attach_dummy_entities(event)

    alert = build_basic_alert(event)
    assert alert.alert_id.startswith("ALERT-")
    assert alert.root_event_id == "EVT-TEST-0001"
    assert alert.classification in (0, 1, 2)
    assert alert.scope.facilities

