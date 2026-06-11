"""Tests for alert correlation functionality."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from hardstop.alerts.alert_builder import build_basic_alert
from hardstop.alerts.correlation import build_correlation_key
from hardstop.database.schema import Alert, Facility
from hardstop.output.incidents.evidence import (
    build_incident_evidence_artifact,
    load_incident_evidence_summary,
)
from hardstop.ops.run_record import artifact_hash
from hardstop.parsing.entity_extractor import EntityLinkingOperator
from hardstop.parsing.normalizer import CanonicalizeExternalEventOperator


def test_build_correlation_key_stable():
    """Test that correlation keys are stable and deterministic."""
    event = {
        "event_type": "SAFETY_AND_OPERATIONS",
        "title": "Spill at plant",
        "raw_text": "spill happened",
        "facilities": ["PLANT-01"],
        "lanes": ["LANE-001"],
    }
    k1 = build_correlation_key(event)
    k2 = build_correlation_key(event)
    assert k1 == k2
    assert "PLANT-01" in k1
    assert "LANE-001" in k1


def test_correlation_key_risk_bucket():
    """Test that risk buckets are correctly identified."""
    # Test explicit event_type
    event1 = {"event_type": "SPILL", "facilities": ["PLANT-01"], "lanes": []}
    key1 = build_correlation_key(event1)
    assert key1.startswith("SPILL|")
    
    # Test keyword inference
    event2 = {"title": "Chemical spill", "raw_text": "spill occurred", "facilities": ["PLANT-01"], "lanes": []}
    key2 = build_correlation_key(event2)
    assert key2.startswith("SPILL|")
    
    # Test strike
    event3 = {"event_type": "STRIKE", "facilities": ["PLANT-01"], "lanes": []}
    key3 = build_correlation_key(event3)
    assert key3.startswith("STRIKE|")
    
    # Test closure
    event4 = {"title": "Facility shutdown", "facilities": ["PLANT-01"], "lanes": []}
    key4 = build_correlation_key(event4)
    assert key4.startswith("CLOSURE|")


def test_correlation_key_facility_lane():
    """Test that facilities and lanes are included in correlation key."""
    event = {
        "event_type": "GENERAL",
        "facilities": ["PLANT-01", "DC-02"],
        "lanes": ["LANE-001", "LANE-002"],
    }
    key = build_correlation_key(event)
    
    # Should include first facility (sorted)
    assert "PLANT-01" in key or "DC-02" in key
    
    # Should include first lane (sorted)
    assert "LANE-001" in key or "LANE-002" in key


def test_correlation_key_no_facilities_lanes():
    """Test correlation key when no facilities or lanes are present."""
    event = {
        "event_type": "GENERAL",
        "facilities": [],
        "lanes": [],
    }
    key = build_correlation_key(event)
    
    # Should still produce a valid key with NONE placeholders
    assert "|" in key
    parts = key.split("|")
    assert len(parts) == 3
    assert parts[1] == "NONE"  # No facilities
    assert parts[2] == "NONE"  # No lanes


def test_correlation_key_deduplicates_facilities():
    """Test that duplicate facilities are handled correctly."""
    event = {
        "event_type": "GENERAL",
        "facilities": ["PLANT-01", "PLANT-01", "DC-02"],
        "lanes": [],
    }
    key1 = build_correlation_key(event)
    
    # Same facilities in different order should produce same key
    event2 = {
        "event_type": "GENERAL",
        "facilities": ["DC-02", "PLANT-01"],
        "lanes": [],
    }
    key2 = build_correlation_key(event2)
    
    # Should use first facility after sorting (alphabetically)
    # So both should use the same first facility
    assert key1 == key2


def test_canonical_payload_hash_matches_fixture(tmp_path):
    raw = json.loads(Path("tests/fixtures/event_spill.json").read_text(encoding="utf-8"))
    fixture = json.loads(Path("tests/fixtures/normalized_event_spill.json").read_text(encoding="utf-8"))
    operator = CanonicalizeExternalEventOperator(
        mode="strict", config_snapshot={}, dest_dir=tmp_path, canonicalize_time=None
    )
    event, _ = operator.run(
        raw_item_candidate={
            "canonical_id": "EVT-CANONICAL-0001",
            "title": raw.get("title"),
            "url": "https://example.com/spill",
            "published_at_utc": "2024-05-01T00:00:00Z",
            "payload": raw,
        },
        source_id="demo-source",
        tier="global",
        raw_id="raw-0001",
        source_config={"trust_tier": 2},
        emit_record=False,
    )
    assert artifact_hash(event) == artifact_hash(fixture)


def test_entity_link_partial_data_fallback(tmp_path):
    event = {
        "event_id": "EVT-PARTIAL",
        "event_type": "SPILL",
        "facilities": [],
        "lanes": [],
        "shipments": [],
    }
    linker = EntityLinkingOperator(mode="strict", config_snapshot={}, dest_dir=tmp_path)
    enriched, _ = linker.run(event, session=None, emit_record=False)
    assert enriched["facilities"] == []
    assert enriched["lanes"] == []
    assert enriched["shipments"] == []
    assert build_correlation_key(enriched).startswith("SPILL|NONE|NONE")


def test_incident_evidence_artifact_matches_fixture(tmp_path):
    event = {
        "event_id": "EVT-TEST-001",
        "title": "Chemical spill at DC-01",
        "event_type": "SPILL",
        "facilities": ["DC-01", "PLANT-02"],
        "lanes": ["LANE-1"],
        "shipments": [],
        "event_time_utc": "2024-05-02T00:00:00Z",
    }
    existing_alert = SimpleNamespace(
        alert_id="ALERT-XYZ",
        correlation_key="SPILL|DC-01|LANE-1",
        last_seen_utc="2024-04-30T12:00:00Z",
        scope_json=json.dumps({"facilities": ["DC-01"], "lanes": ["LANE-1"], "shipments": ["SHIP-001"]}),
        root_event_ids_json=json.dumps(["EVT-OLD-1"]),
    )
    artifact, artifact_ref, artifact_path = build_incident_evidence_artifact(
        alert_id="ALERT-XYZ",
        event=event,
        correlation_key="SPILL|DC-01|LANE-1",
        existing_alert=existing_alert,
        window_hours=168,
        dest_dir=tmp_path,
        generated_at="2024-05-02T00:00:00Z",
        filename_basename="ALERT-XYZ__EVT-TEST-001__SPILL_DC-01_LANE-1",
    )

    expected = json.loads(Path("tests/fixtures/incident_evidence_spill.json").read_text(encoding="utf-8"))
    assert artifact.to_dict() == expected
    assert artifact_ref.hash == expected["artifact_hash"]
    assert artifact_path.exists()


def test_incident_evidence_sanitizes_url_like_event_ids(tmp_path):
    basename = "ALERT-URL__https://alerts.example.test/feed/item/123__SPILL_DC-01_LANE-1"
    digest = hashlib.sha256(basename.encode("utf-8")).hexdigest()[:16]

    _, _, artifact_path = build_incident_evidence_artifact(
        alert_id="ALERT-URL",
        event={
            "event_id": "https://alerts.example.test/feed/item/123",
            "title": "Chemical spill at DC-01",
            "event_type": "SPILL",
            "facilities": ["DC-01"],
            "lanes": ["LANE-1"],
            "shipments": [],
            "event_time_utc": "2024-05-02T00:00:00Z",
        },
        correlation_key="SPILL|DC-01|LANE-1",
        existing_alert=None,
        window_hours=168,
        dest_dir=tmp_path,
        generated_at="2024-05-02T00:00:00Z",
        filename_basename=basename,
    )

    assert artifact_path.exists()
    assert artifact_path.parent == tmp_path
    assert "/" not in artifact_path.name
    assert artifact_path.name == (
        f"ALERT-URL__https_alerts.example.test_feed_item_123__SPILL_DC-01_LANE-1__{digest}.json"
    )


def test_incident_evidence_sanitized_filename_collisions_keep_distinct_artifacts(tmp_path):
    unsafe_basename = "ALERT-COLLIDE__a/b__SPILL_DC-01_NONE"
    safe_basename = "ALERT-COLLIDE__a_b__SPILL_DC-01_NONE"

    _, unsafe_ref, unsafe_path = build_incident_evidence_artifact(
        alert_id="ALERT-COLLIDE",
        event={
            "event_id": "a/b",
            "title": "Unsafe id",
            "event_type": "SPILL",
            "facilities": ["DC-01"],
            "lanes": [],
            "shipments": [],
            "event_time_utc": "2024-05-02T00:00:00Z",
        },
        correlation_key="SPILL|DC-01|NONE",
        existing_alert=None,
        window_hours=168,
        dest_dir=tmp_path,
        generated_at="2024-05-02T00:00:00Z",
        filename_basename=unsafe_basename,
    )
    _, safe_ref, safe_path = build_incident_evidence_artifact(
        alert_id="ALERT-COLLIDE",
        event={
            "event_id": "a_b",
            "title": "Safe id",
            "event_type": "SPILL",
            "facilities": ["DC-01"],
            "lanes": [],
            "shipments": [],
            "event_time_utc": "2024-05-02T00:00:00Z",
        },
        correlation_key="SPILL|DC-01|NONE",
        existing_alert=None,
        window_hours=168,
        dest_dir=tmp_path,
        generated_at="2024-05-02T00:00:00Z",
        filename_basename=safe_basename,
    )

    assert unsafe_path != safe_path
    assert unsafe_path.exists()
    assert safe_path.exists()
    assert sorted(path.name for path in tmp_path.glob("*.json")) == sorted(
        [unsafe_path.name, safe_path.name]
    )
    assert unsafe_ref.hash != safe_ref.hash


def test_incident_evidence_reserves_generated_hash_suffixes(tmp_path):
    unsafe_basename = "ALERT-COLLIDE__a/b__SPILL_DC-01_NONE"
    unsafe_digest = hashlib.sha256(unsafe_basename.encode("utf-8")).hexdigest()[:16]
    generated_basename = f"ALERT-COLLIDE__a_b__SPILL_DC-01_NONE__{unsafe_digest}"
    generated_digest = hashlib.sha256(generated_basename.encode("utf-8")).hexdigest()[:16]

    _, unsafe_ref, unsafe_path = build_incident_evidence_artifact(
        alert_id="ALERT-COLLIDE",
        event={
            "event_id": "a/b",
            "title": "Unsafe id",
            "event_type": "SPILL",
            "facilities": ["DC-01"],
            "lanes": [],
            "shipments": [],
            "event_time_utc": "2024-05-02T00:00:00Z",
        },
        correlation_key="SPILL|DC-01|NONE",
        existing_alert=None,
        window_hours=168,
        dest_dir=tmp_path,
        generated_at="2024-05-02T00:00:00Z",
        filename_basename=unsafe_basename,
    )
    _, safe_ref, safe_path = build_incident_evidence_artifact(
        alert_id="ALERT-COLLIDE",
        event={
            "event_id": f"a_b__{unsafe_digest}",
            "title": "Safe generated-name lookalike",
            "event_type": "SPILL",
            "facilities": ["DC-01"],
            "lanes": [],
            "shipments": [],
            "event_time_utc": "2024-05-02T00:00:00Z",
        },
        correlation_key="SPILL|DC-01|NONE",
        existing_alert=None,
        window_hours=168,
        dest_dir=tmp_path,
        generated_at="2024-05-02T00:00:00Z",
        filename_basename=generated_basename,
    )

    assert unsafe_path.name == f"{generated_basename}.json"
    assert safe_path.name == f"{generated_basename}__{generated_digest}.json"
    assert unsafe_path != safe_path
    assert unsafe_path.exists()
    assert safe_path.exists()
    assert sorted(path.name for path in tmp_path.glob("*.json")) == sorted(
        [unsafe_path.name, safe_path.name]
    )
    assert unsafe_ref.hash != safe_ref.hash


def test_incident_evidence_truncates_overlong_sanitized_filenames(tmp_path):
    long_event_id = "https://alerts.example.test/feed/" + ("item/" * 80) + "123"
    long_basename = f"ALERT-LONG__{long_event_id}__SPILL_DC-01_LANE-1"

    _, _, artifact_path = build_incident_evidence_artifact(
        alert_id="ALERT-LONG",
        event={
            "event_id": long_event_id,
            "title": "Chemical spill at DC-01",
            "event_type": "SPILL",
            "facilities": ["DC-01"],
            "lanes": ["LANE-1"],
            "shipments": [],
            "event_time_utc": "2024-05-02T00:00:00Z",
        },
        correlation_key="SPILL|DC-01|LANE-1",
        existing_alert=None,
        window_hours=168,
        dest_dir=tmp_path,
        generated_at="2024-05-02T00:00:00Z",
        filename_basename=long_basename,
    )

    assert artifact_path.exists()
    assert artifact_path.parent == tmp_path
    assert len(artifact_path.name.encode("utf-8")) <= 255
    assert artifact_path.name.endswith(".json")
    assert "__" in artifact_path.stem

    _, _, repeat_path = build_incident_evidence_artifact(
        alert_id="ALERT-LONG",
        event={
            "event_id": long_event_id,
            "title": "Chemical spill at DC-01",
            "event_type": "SPILL",
            "facilities": ["DC-01"],
            "lanes": ["LANE-1"],
            "shipments": [],
            "event_time_utc": "2024-05-02T00:00:00Z",
        },
        correlation_key="SPILL|DC-01|LANE-1",
        existing_alert=None,
        window_hours=168,
        dest_dir=tmp_path,
        generated_at="2024-05-02T00:00:00Z",
        filename_basename=long_basename,
    )
    assert repeat_path.name == artifact_path.name


def test_incident_evidence_summary_loads_latest(tmp_path):
    event = {
        "event_id": "EVT-TEST-002",
        "title": "Follow-on spill update",
        "event_type": "SPILL",
        "facilities": ["DC-01"],
        "lanes": ["LANE-1"],
        "shipments": [],
        "event_time_utc": "2024-05-03T00:00:00Z",
    }
    existing_alert = SimpleNamespace(
        alert_id="ALERT-XYZ",
        correlation_key="SPILL|DC-01|LANE-1",
        last_seen_utc="2024-05-02T10:00:00Z",
        scope_json=json.dumps({"facilities": ["DC-01"], "lanes": ["LANE-1"], "shipments": []}),
        root_event_ids_json=json.dumps(["EVT-OLD-1"]),
    )
    build_incident_evidence_artifact(
        alert_id="ALERT-XYZ",
        event=event,
        correlation_key="SPILL|DC-01|LANE-1",
        existing_alert=existing_alert,
        window_hours=168,
        dest_dir=tmp_path,
        generated_at="2024-05-03T00:00:00Z",
        filename_basename="ALERT-XYZ__EVT-TEST-002__SPILL_DC-01_LANE-1",
    )

    summary = load_incident_evidence_summary("ALERT-XYZ", "SPILL|DC-01|LANE-1", dest_dir=tmp_path)
    assert summary is not None
    assert "merge_summary" in summary
    assert summary["inputs"]["alert_id"] == "ALERT-XYZ"
    assert summary["artifact_hash"]


def test_correlated_update_preserves_shipment_truncation_diagnostics(session, tmp_path):
    session.add(
        Facility(
            facility_id="PLANT-TRUNCATION",
            name="Truncation Plant",
            type="plant",
            city="Avon",
            state="IN",
            country="US",
            criticality_score=8,
        )
    )
    session.commit()

    def event_payload(event_id, shipments, total_linked, truncated):
        return {
            "event_id": event_id,
            "title": "Chemical spill at PLANT-TRUNCATION",
            "raw_text": "Chemical spill at PLANT-TRUNCATION facility.",
            "event_type": "SPILL",
            "facilities": ["PLANT-TRUNCATION"],
            "lanes": [],
            "shipments": shipments,
            "shipments_total_linked": total_linked,
            "shipments_truncated": truncated,
            "link_confidence": {"facility": 0.80},
            "link_provenance": {"facility": "FACILITY_ID_EXACT"},
            "trust_tier": 3,
        }

    build_basic_alert(
        event_payload(
            "EVT-TRUNCATED-FIRST",
            ["SHP-001", "SHP-002", "SHP-003", "SHP-004", "SHP-005"],
            10,
            True,
        ),
        session=session,
        incident_dest_dir=tmp_path,
    )
    build_basic_alert(
        event_payload("EVT-TRUNCATED-UPDATE", ["SHP-006"], 1, False),
        session=session,
        incident_dest_dir=tmp_path,
    )

    alert_row = session.query(Alert).one()
    scope = json.loads(alert_row.scope_json)
    diagnostics = json.loads(alert_row.diagnostics_json)
    assert scope["shipments_total_linked"] == 10
    assert scope["shipments_truncated"] is True
    assert diagnostics["shipments_total_linked"] == 10
    assert diagnostics["shipments_truncated"] is True
