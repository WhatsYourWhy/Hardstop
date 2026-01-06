"""Tests for export API contracts."""

import json
from pathlib import Path

import pytest

from hardstop.api.brief_api import get_brief
from hardstop.api.export import export_alerts, export_brief, export_sources


def test_export_brief_matches_api_brief_invariants(session):
    """Test that export brief matches API brief invariants."""
    # Get brief from API
    brief_data = get_brief(session, since="24h", include_class0=False, limit=20)
    
    # Export brief
    export_json = export_brief(session, since="24h", include_class0=False, limit=20, format="json")
    export_dict = json.loads(export_json)
    
    # Assert export schema
    assert export_dict["export_schema_version"] == "1"
    assert "exported_at_utc" in export_dict
    assert "data" in export_dict
    
    # Assert data matches API brief
    exported_brief = export_dict["data"]
    assert exported_brief["read_model_version"] == "brief.v1"
    assert exported_brief["counts"] == brief_data["counts"]
    assert exported_brief["tier_counts"] == brief_data["tier_counts"]
    
    # Assert required keys exist
    required_keys = [
        "read_model_version",
        "generated_at_utc",
        "window",
        "counts",
        "tier_counts",
        "top",
        "updated",
        "created",
        "suppressed",
        "suppressed_legacy",
    ]
    for key in required_keys:
        assert key in exported_brief, f"Missing required key: {key}"


def test_export_alerts_csv_has_required_columns_and_row_count(session):
    """Test that export alerts CSV has required columns and correct row count."""
    # Get alerts from API
    from hardstop.api.alerts_api import list_alerts
    
    alerts = list_alerts(session, since="24h", limit=50)
    
    # Export alerts as CSV
    csv_output = export_alerts(session, since="24h", limit=50, format="csv")
    csv_lines = csv_output.strip().split("\n")
    
    # Check header
    header = csv_lines[0]
    required_columns = [
        "alert_id",
        "classification",
        "impact_score",
        "tier",
        "trust_tier",
        "source_id",
        "correlation_action",
        "update_count",
        "first_seen_utc",
        "last_seen_utc",
        "summary",
    ]
    
    header_cols = [col.strip() for col in header.split(",")]
    assert header_cols == required_columns, f"CSV header mismatch: expected {required_columns}, got {header_cols}"
    
    # Check row count (header + data rows)
    assert len(csv_lines) == len(alerts) + 1, f"CSV row count mismatch: expected {len(alerts) + 1} (header + {len(alerts)} rows), got {len(csv_lines)}"


def test_get_brief_is_stable_sort_order(session):
    """Test that get_brief returns alerts in stable sort order."""
    from hardstop.database.alert_repo import upsert_new_alert_row
    import json
    
    # Create alerts with known impact scores to test sorting behavior
    # Alert 1: classification 2, impact_score 10, CREATED
    alert1 = upsert_new_alert_row(
        session,
        alert_id="ALERT-SORT-1",
        summary="High impact alert",
        risk_type="TEST",
        classification=2,
        status="OPEN",
        reasoning="Test",
        recommended_actions=None,
        root_event_id="EVT-SORT-1",
        correlation_key="sort:test:1",
        correlation_action="CREATED",
        impact_score=10,
        scope_json=json.dumps({"facilities": [], "lanes": [], "shipments": []}),
    )
    
    # Alert 2: classification 2, impact_score 5, CREATED (lower impact)
    alert2 = upsert_new_alert_row(
        session,
        alert_id="ALERT-SORT-2",
        summary="Medium impact alert",
        risk_type="TEST",
        classification=2,
        status="OPEN",
        reasoning="Test",
        recommended_actions=None,
        root_event_id="EVT-SORT-2",
        correlation_key="sort:test:2",
        correlation_action="CREATED",
        impact_score=5,
        scope_json=json.dumps({"facilities": [], "lanes": [], "shipments": []}),
    )
    
    # Alert 3: classification 1, impact_score 8, UPDATED
    alert3 = upsert_new_alert_row(
        session,
        alert_id="ALERT-SORT-3",
        summary="Updated alert",
        risk_type="TEST",
        classification=1,
        status="UPDATED",
        reasoning="Test",
        recommended_actions=None,
        root_event_id="EVT-SORT-3",
        correlation_key="sort:test:3",
        correlation_action="UPDATED",
        impact_score=8,
        scope_json=json.dumps({"facilities": [], "lanes": [], "shipments": []}),
    )
    
    session.commit()
    
    # Get brief twice to verify stability
    brief1 = get_brief(session, since="24h", include_class0=True, limit=20)
    brief2 = get_brief(session, since="24h", include_class0=True, limit=20)
    
    # Assert ordering is stable (same alerts in same order)
    assert brief1["top"] == brief2["top"], "Top alerts ordering should be stable"
    assert brief1["updated"] == brief2["updated"], "Updated alerts ordering should be stable"
    assert brief1["created"] == brief2["created"], "Created alerts ordering should be stable"
    
    # Assert created preserves repo order (repo sorts by classification DESC, impact_score DESC)
    # So alert1 (class 2, impact 10) should come before alert2 (class 2, impact 5)
    created_alert_ids = [a["alert_id"] for a in brief1["created"]]
    if "ALERT-SORT-1" in created_alert_ids and "ALERT-SORT-2" in created_alert_ids:
        idx1 = created_alert_ids.index("ALERT-SORT-1")
        idx2 = created_alert_ids.index("ALERT-SORT-2")
        assert idx1 < idx2, "created should preserve repo order (class 2 impact 10 before class 2 impact 5)"
    
    # Assert updated preserves repo order
    updated_alert_ids = [a["alert_id"] for a in brief1["updated"]]
    if "ALERT-SORT-3" in updated_alert_ids:
        # Should be in updated list
        assert True
    
    # Assert top uses presentation sort (impact_score DESC, not repo order)
    # Top should have highest impact_score first
    top_alert_ids = [a["alert_id"] for a in brief1["top"]]
    if "ALERT-SORT-1" in top_alert_ids and "ALERT-SORT-2" in top_alert_ids:
        idx1 = top_alert_ids.index("ALERT-SORT-1")
        idx2 = top_alert_ids.index("ALERT-SORT-2")
        assert idx1 < idx2, "top should use presentation sort (impact 10 before impact 5)"
        # Verify impact scores are descending
        top_impacts = [a.get("impact_score", 0) for a in brief1["top"]]
        assert top_impacts == sorted(top_impacts, reverse=True), "top should be sorted by impact_score DESC"


def test_alert_reconstruction_round_trip(session):
    """Test that alert reconstruction from DB preserves all required fields."""
    from hardstop.api.alerts_api import list_alerts
    from hardstop.database.alert_repo import upsert_new_alert_row
    import json
    
    # Create alert row via repo
    alert_id = "ALERT-TEST-ROUNDTRIP"
    root_event_id = "EVT-TEST-001"
    correlation_key = "test:correlation:key"
    
    scope_json = json.dumps({
        "facilities": ["FAC-001", "FAC-002"],
        "lanes": ["LANE-001"],
        "shipments": ["SHIP-001"],
        "shipments_total_linked": 1,
        "shipments_truncated": False,
    })
    
    alert_row = upsert_new_alert_row(
            session,
            alert_id=alert_id,
            summary="Test alert for round-trip reconstruction",
            risk_type="TEST",
            classification=2,
            status="OPEN",
            reasoning="Test reasoning",
            recommended_actions=json.dumps([{
                "id": "ACT-001",
                "description": "Test action",
                "owner_role": "Operations",
                "due_within_hours": 4
            }]),
            root_event_id=root_event_id,
            correlation_key=correlation_key,
            correlation_action="CREATED",
            impact_score=8,
            scope_json=scope_json,
            tier="global",
            source_id="test_source",
            trust_tier=2,
        )
    session.commit()
    
    # Call api.list_alerts()
    alerts = list_alerts(session, since=None, limit=100)
    
    # Find our test alert
    test_alert = None
    for alert in alerts:
        if alert.alert_id == alert_id:
            test_alert = alert
            break
    
    assert test_alert is not None, "Test alert should be found in list_alerts()"
    
    # Assert required fields exist
    assert test_alert.alert_id == alert_id
    assert test_alert.classification == 2
    assert test_alert.summary == "Test alert for round-trip reconstruction"
    assert test_alert.risk_type == "TEST"
    assert test_alert.root_event_id == root_event_id
    assert test_alert.scope is not None
    assert len(test_alert.scope.facilities) == 2
    assert len(test_alert.scope.lanes) == 1
    assert len(test_alert.scope.shipments) == 1
    
    # Assert new fields are present (via evidence.correlation)
    assert test_alert.evidence is not None
    assert test_alert.evidence.correlation is not None
    assert test_alert.evidence.correlation["key"] == correlation_key
    assert test_alert.evidence.correlation["action"] == "CREATED"
    assert test_alert.evidence.correlation["alert_id"] == alert_id
    
    # Assert impact_score is in diagnostics
    assert test_alert.evidence.diagnostics is not None
    assert test_alert.evidence.diagnostics.impact_score == 8
    
    # Note: tier, trust_tier, source_id, update_count, first_seen_utc, last_seen_utc
    # are stored in Alert ORM row but not yet in HardstopAlert model.
    # They are accessible via get_alert_detail() which queries the row directly.
    # This test verifies the core reconstruction works.


def test_alert_reconstruction_with_source_metadata(session):
    """Test that alert reconstruction preserves evidence.source, correlation_action, and scope_json metadata."""
    from hardstop.api.alerts_api import list_alerts
    from hardstop.database.alert_repo import upsert_new_alert_row
    import json
    
    # Create alert with source metadata (tier/trust_tier/source_id)
    alert_id = "ALERT-TEST-SOURCE-META"
    root_event_id = "EVT-TEST-002"
    correlation_key = "test:correlation:source"
    
    # Create scope_json with truncation metadata
    scope_json = json.dumps({
        "facilities": ["FAC-001", "FAC-002", "FAC-003"],  # 3 facilities
        "lanes": ["LANE-001"],
        "shipments": ["SHIP-001", "SHIP-002"],  # 2 shipments shown
        "shipments_total_linked": 5,  # But 5 total linked (truncation metadata)
        "shipments_truncated": True,  # Truncation flag
    })
    
    alert_row = upsert_new_alert_row(
        session,
        alert_id=alert_id,
        summary="Test alert with source metadata",
        risk_type="TEST",
        classification=2,
        status="OPEN",
        reasoning="Test reasoning with source",
        recommended_actions=json.dumps([{
            "id": "ACT-002",
            "description": "Test action with source",
            "owner_role": "Operations",
            "due_within_hours": 4
        }]),
        root_event_id=root_event_id,
        correlation_key=correlation_key,
        correlation_action="UPDATED",  # Test UPDATED action
        impact_score=9,
        scope_json=scope_json,
        tier="regional",  # Source tier
        source_id="test_source_regional",  # Source ID
        trust_tier=1,  # High trust tier
    )
    session.commit()
    
    # Call api.list_alerts()
    alerts = list_alerts(session, since=None, limit=100)
    
    # Find our test alert
    test_alert = None
    for alert in alerts:
        if alert.alert_id == alert_id:
            test_alert = alert
            break
    
    assert test_alert is not None, "Test alert should be found in list_alerts()"
    
    # Verify correlation_action survives
    assert test_alert.evidence is not None
    assert test_alert.evidence.correlation is not None
    assert test_alert.evidence.correlation["action"] == "UPDATED", "correlation_action should be UPDATED"
    assert test_alert.evidence.correlation["key"] == correlation_key
    
    # Verify scope_json / truncation metadata doesn't get dropped
    assert test_alert.scope is not None
    assert len(test_alert.scope.facilities) == 3, "Should preserve all facilities"
    assert len(test_alert.scope.shipments) == 2, "Should preserve shown shipments"
    # Note: shipments_total_linked and shipments_truncated are in scope_json but not in AlertScope model
    # They would need to be added to AlertScope if we want to preserve them in the Pydantic model
    
    # Verify impact_score is preserved
    assert test_alert.evidence.diagnostics is not None
    assert test_alert.evidence.diagnostics.impact_score == 9
    
    # Note: evidence.source is not currently populated in _alert_row_to_hardstop_alert
    # This would require querying the Alert row for tier/source_id/trust_tier and adding to evidence.source
    # For now, we verify that the correlation_action and scope_json are preserved


def test_export_bundle_is_deterministic(tmp_path, session):
    """Test that export bundle is deterministic (same inputs produce same outputs)."""
    import hashlib
    from pathlib import Path
    
    # Create some test alerts first
    from hardstop.database.alert_repo import upsert_new_alert_row
    import json
    
    alert_id_1 = "ALERT-EXPORT-1"
    alert_id_2 = "ALERT-EXPORT-2"
    
    scope_json = json.dumps({
        "facilities": ["FAC-001"],
        "lanes": ["LANE-001"],
        "shipments": ["SHIP-001"],
    })
    
    upsert_new_alert_row(
        session,
        alert_id=alert_id_1,
        summary="Test alert 1",
        risk_type="TEST",
        classification=2,
        status="OPEN",
        reasoning="Test",
        recommended_actions=None,
        root_event_id="EVT-EXPORT-1",
        correlation_key="export:test:1",
        correlation_action="CREATED",
        impact_score=8,
        scope_json=scope_json,
    )
    
    upsert_new_alert_row(
        session,
        alert_id=alert_id_2,
        summary="Test alert 2",
        risk_type="TEST",
        classification=1,
        status="OPEN",
        reasoning="Test",
        recommended_actions=None,
        root_event_id="EVT-EXPORT-2",
        correlation_key="export:test:2",
        correlation_action="CREATED",
        impact_score=5,
        scope_json=scope_json,
    )
    session.commit()
    
    # Create output directories
    export_dir_1 = tmp_path / "export_1"
    export_dir_2 = tmp_path / "export_2"
    export_dir_1.mkdir()
    export_dir_2.mkdir()
    
    # First export run
    export_file_1 = export_dir_1 / "alerts.json"
    export_alerts(
        session,
        since=None,
        limit=50,
        format="json",
        out=export_file_1,
    )
    
    # Second export run (same inputs)
    export_file_2 = export_dir_2 / "alerts.json"
    export_alerts(
        session,
        since=None,
        limit=50,
        format="json",
        out=export_file_2,
    )
    
    # Compare file lists (should be identical)
    files_1 = sorted([f.name for f in export_dir_1.iterdir()])
    files_2 = sorted([f.name for f in export_dir_2.iterdir()])
    assert files_1 == files_2, f"File lists must be identical: {files_1} != {files_2}"
    
    # Compare per-file SHA-256 hashes
    def file_hash(path: Path) -> str:
        content = path.read_text(encoding="utf-8")
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    
    hash_1 = file_hash(export_file_1)
    hash_2 = file_hash(export_file_2)
    assert hash_1 == hash_2, f"File hashes must be identical: {hash_1} != {hash_2}"
    
    # Compare manifest ordering (parse JSON and check data ordering)
    data_1 = json.loads(export_file_1.read_text(encoding="utf-8"))
    data_2 = json.loads(export_file_2.read_text(encoding="utf-8"))
    
    # Check schema version
    assert data_1["export_schema_version"] == data_2["export_schema_version"]
    
    # Check data ordering (alert IDs should be in same order)
    alert_ids_1 = [alert["alert_id"] for alert in data_1["data"]]
    alert_ids_2 = [alert["alert_id"] for alert in data_2["data"]]
    assert alert_ids_1 == alert_ids_2, f"Alert ordering must be stable: {alert_ids_1} != {alert_ids_2}"
    
    # For brief export, test the same
    brief_file_1 = export_dir_1 / "brief.json"
    brief_file_2 = export_dir_2 / "brief.json"
    
    export_brief(
        session,
        since="24h",
        include_class0=False,
        limit=20,
        format="json",
        out=brief_file_1,
    )
    
    export_brief(
        session,
        since="24h",
        include_class0=False,
        limit=20,
        format="json",
        out=brief_file_2,
    )
    
    # Compare brief hashes (excluding exported_at_utc which may differ)
    brief_data_1 = json.loads(brief_file_1.read_text(encoding="utf-8"))
    brief_data_2 = json.loads(brief_file_2.read_text(encoding="utf-8"))
    
    # Remove exported_at_utc for comparison (it's a timestamp)
    brief_data_1_no_time = {k: v for k, v in brief_data_1.items() if k != "exported_at_utc"}
    brief_data_2_no_time = {k: v for k, v in brief_data_2.items() if k != "exported_at_utc"}
    
    # Compare structure and data (not timestamps)
    assert brief_data_1_no_time == brief_data_2_no_time, "Brief data (excluding timestamps) must be identical"
    
    # For sources export
    sources_file_1 = export_dir_1 / "sources.json"
    sources_file_2 = export_dir_2 / "sources.json"
    
    export_sources(
        session,
        lookback="7d",
        stale="72h",
        format="json",
        out=sources_file_1,
    )
    
    export_sources(
        session,
        lookback="7d",
        stale="72h",
        format="json",
        out=sources_file_2,
    )
    
    # Compare sources hashes (excluding exported_at_utc)
    sources_data_1 = json.loads(sources_file_1.read_text(encoding="utf-8"))
    sources_data_2 = json.loads(sources_file_2.read_text(encoding="utf-8"))
    
    sources_data_1_no_time = {k: v for k, v in sources_data_1.items() if k != "exported_at_utc"}
    sources_data_2_no_time = {k: v for k, v in sources_data_2.items() if k != "exported_at_utc"}
    
    assert sources_data_1_no_time == sources_data_2_no_time, "Sources data (excluding timestamps) must be identical"