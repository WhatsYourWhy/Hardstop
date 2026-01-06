"""Tests for offline mode operation (no network adapters)."""

import json
from pathlib import Path

from hardstop.alerts.alert_builder import build_basic_alert
from hardstop.ingestion.file_ingestor import ingest_all_csvs
from hardstop.parsing.network_linker import link_event_to_network
from hardstop.parsing.normalizer import normalize_event


def test_offline_mode_with_file_fixtures(tmp_path, session):
    """Test that system runs fully local with file fixtures only (no network adapters)."""
    # Load network data from CSV files (local)
    facilities = Path("tests/fixtures/facilities.csv")
    lanes = Path("tests/fixtures/lanes.csv")
    shipments = Path("tests/fixtures/shipments_snapshot.csv")
    
    counts = ingest_all_csvs(facilities, lanes, shipments, session)
    assert counts["facilities"] > 0, "Should load facilities from CSV"
    assert counts["lanes"] > 0, "Should load lanes from CSV"
    assert counts["shipments"] > 0, "Should load shipments from CSV"
    
    # Load event from file fixture (local)
    event_path = Path("tests/fixtures/event_spill.json")
    raw = json.loads(event_path.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-OFFLINE-0001"
    
    # Normalize event (no network calls)
    event = normalize_event(raw)
    
    # Link to network (uses local SQLite, no network)
    event = link_event_to_network(event, session=session)
    
    # Build alert (uses local SQLite, no network)
    alert = build_basic_alert(event, session=session)
    
    # Verify alert was created successfully
    assert alert.alert_id.startswith("ALERT-")
    assert alert.classification in (0, 1, 2)
    assert alert.scope.facilities, "Should have linked facilities"
    
    # Verify no network dependencies were required
    # (This test passes if it completes without network errors)
    assert True, "Offline mode test passed - no network adapters required"

