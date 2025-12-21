"""Tests for export API contracts."""

import json
from pathlib import Path

import pytest

from sentinel.api.brief_api import get_brief
from sentinel.api.export import export_alerts, export_brief, export_sources


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
    from sentinel.api.alerts_api import list_alerts
    
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
    # Get brief twice
    brief1 = get_brief(session, since="24h", include_class0=False, limit=20)
    brief2 = get_brief(session, since="24h", include_class0=False, limit=20)
    
    # Assert ordering is stable (same alerts in same order)
    assert brief1["top"] == brief2["top"], "Top alerts ordering should be stable"
    assert brief1["updated"] == brief2["updated"], "Updated alerts ordering should be stable"
    assert brief1["created"] == brief2["created"], "Created alerts ordering should be stable"

