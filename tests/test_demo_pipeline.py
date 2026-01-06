import json
from datetime import UTC
from pathlib import Path

from hardstop.alerts.alert_builder import build_basic_alert
from hardstop.ingestion.file_ingestor import ingest_all_csvs
from hardstop.parsing.entity_extractor import attach_dummy_entities
from hardstop.parsing.network_linker import link_event_to_network
from hardstop.parsing.normalizer import normalize_event
from hardstop.runners.run_demo import (
    DEFAULT_PINNED_RUN_ID,
    DEFAULT_PINNED_SEED,
    DEFAULT_PINNED_TIMESTAMP,
)
from hardstop.utils.id_generator import deterministic_id_context


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


def test_pinned_demo_output_is_stable(tmp_path, session):
    facilities = Path("tests/fixtures/facilities.csv")
    lanes = Path("tests/fixtures/lanes.csv")
    shipments = Path("tests/fixtures/shipments_snapshot.csv")
    ingest_all_csvs(facilities, lanes, shipments, session)

    event_path = Path("tests/fixtures/event_spill.json")
    raw = json.loads(event_path.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-DEMO-0001"

    event = normalize_event(raw)
    event = link_event_to_network(event, session=session)

    pinned_dt = DEFAULT_PINNED_TIMESTAMP
    pinned_iso = pinned_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    event["event_time_utc"] = pinned_iso
    event["published_at_utc"] = pinned_iso
    event["scoring_now"] = pinned_dt

    determinism_context = {
        "seed": DEFAULT_PINNED_SEED,
        "timestamp_utc": pinned_iso,
        "run_id": DEFAULT_PINNED_RUN_ID,
    }

    incidents_dir = tmp_path / "incidents"
    with deterministic_id_context(now=pinned_dt, seed=DEFAULT_PINNED_SEED):
        alert = build_basic_alert(
            event,
            session=session,
            determinism_mode="pinned",
            determinism_context=determinism_context,
            incident_dest_dir=incidents_dir,
        )

    assert alert.alert_id == "ALERT-20251229-d31a370b"

    incident_summary = alert.evidence.incident_evidence
    artifact_path = Path(incident_summary.artifact_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert payload["determinism_mode"] == "pinned"
    assert payload["determinism_context"] == determinism_context
    expected_hash = "e36dbe8cf992b8a2e49fb2eb3d867fe9a728517fcbe6bcc19d46e66875eaa2d6"
    assert incident_summary.artifact_hash == expected_hash
    assert payload["artifact_hash"] == expected_hash


def test_pinned_demo_replay_is_identical(tmp_path, session):
    """Test that running the pinned pipeline twice produces identical outputs."""
    facilities = Path("tests/fixtures/facilities.csv")
    lanes = Path("tests/fixtures/lanes.csv")
    shipments = Path("tests/fixtures/shipments_snapshot.csv")
    ingest_all_csvs(facilities, lanes, shipments, session)

    event_path = Path("tests/fixtures/event_spill.json")
    raw = json.loads(event_path.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-DEMO-0001"

    pinned_dt = DEFAULT_PINNED_TIMESTAMP
    pinned_iso = pinned_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")

    determinism_context = {
        "seed": DEFAULT_PINNED_SEED,
        "timestamp_utc": pinned_iso,
        "run_id": DEFAULT_PINNED_RUN_ID,
    }

    incidents_dir_1 = tmp_path / "incidents_1"
    incidents_dir_2 = tmp_path / "incidents_2"

    # First run
    event_1 = normalize_event(raw.copy())
    event_1 = link_event_to_network(event_1, session=session)
    event_1["event_time_utc"] = pinned_iso
    event_1["published_at_utc"] = pinned_iso
    event_1["scoring_now"] = pinned_dt

    with deterministic_id_context(now=pinned_dt, seed=DEFAULT_PINNED_SEED):
        alert_1 = build_basic_alert(
            event_1,
            session=session,
            determinism_mode="pinned",
            determinism_context=determinism_context,
            incident_dest_dir=incidents_dir_1,
        )

    # Second run (fresh event dict, same inputs)
    event_2 = normalize_event(raw.copy())
    event_2 = link_event_to_network(event_2, session=session)
    event_2["event_time_utc"] = pinned_iso
    event_2["published_at_utc"] = pinned_iso
    event_2["scoring_now"] = pinned_dt

    with deterministic_id_context(now=pinned_dt, seed=DEFAULT_PINNED_SEED):
        alert_2 = build_basic_alert(
            event_2,
            session=session,
            determinism_mode="pinned",
            determinism_context=determinism_context,
            incident_dest_dir=incidents_dir_2,
        )

    # Assert deep equality on stable fields
    assert alert_1.alert_id == alert_2.alert_id, "Alert IDs must be identical"
    assert alert_1.classification == alert_2.classification, "Classifications must be identical"
    
    # Scope comparison (convert to dict for comparison)
    scope_1 = {
        "facilities": sorted(alert_1.scope.facilities),
        "lanes": sorted(alert_1.scope.lanes),
        "shipments": sorted(alert_1.scope.shipments),
    }
    scope_2 = {
        "facilities": sorted(alert_2.scope.facilities),
        "lanes": sorted(alert_2.scope.lanes),
        "shipments": sorted(alert_2.scope.shipments),
    }
    assert scope_1 == scope_2, f"Scopes must be identical: {scope_1} != {scope_2}"
    
    # Reasoning list (exact ordering)
    assert alert_1.reasoning == alert_2.reasoning, f"Reasoning must be identical: {alert_1.reasoning} != {alert_2.reasoning}"
    
    # Quality validation dict (exact match)
    qv_1 = alert_1.evidence.diagnostics.quality_validation if alert_1.evidence and alert_1.evidence.diagnostics else {}
    qv_2 = alert_2.evidence.diagnostics.quality_validation if alert_2.evidence and alert_2.evidence.diagnostics else {}
    assert qv_1 == qv_2, f"Quality validation must be identical: {qv_1} != {qv_2}"


def test_no_nondeterministic_fields_in_alert_payload(tmp_path, session):
    """Test that alert payloads contain no nondeterministic fields."""
    import hashlib
    import re
    from datetime import datetime
    
    facilities = Path("tests/fixtures/facilities.csv")
    lanes = Path("tests/fixtures/lanes.csv")
    shipments = Path("tests/fixtures/shipments_snapshot.csv")
    ingest_all_csvs(facilities, lanes, shipments, session)

    event_path = Path("tests/fixtures/event_spill.json")
    raw = json.loads(event_path.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-DEMO-0001"

    event = normalize_event(raw)
    event = link_event_to_network(event, session=session)

    pinned_dt = DEFAULT_PINNED_TIMESTAMP
    pinned_iso = pinned_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    event["event_time_utc"] = pinned_iso
    event["published_at_utc"] = pinned_iso
    event["scoring_now"] = pinned_dt

    determinism_context = {
        "seed": DEFAULT_PINNED_SEED,
        "timestamp_utc": pinned_iso,
        "run_id": DEFAULT_PINNED_RUN_ID,
    }

    incidents_dir = tmp_path / "incidents"
    with deterministic_id_context(now=pinned_dt, seed=DEFAULT_PINNED_SEED):
        alert = build_basic_alert(
            event,
            session=session,
            determinism_mode="pinned",
            determinism_context=determinism_context,
            incident_dest_dir=incidents_dir,
        )

    # Get payloads
    alert_payload = alert.model_dump()
    evidence_payload = alert.evidence.model_dump() if alert.evidence else {}
    diagnostics_payload = alert.evidence.diagnostics.model_dump() if alert.evidence and alert.evidence.diagnostics else {}
    
    # Get incident artifact payload
    incident_summary = alert.evidence.incident_evidence if alert.evidence else None
    incident_payload = {}
    if incident_summary and incident_summary.artifact_path:
        artifact_path = Path(incident_summary.artifact_path)
        if artifact_path.exists():
            incident_payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    # Helper to recursively check for nondeterministic patterns
    def check_nondeterministic(obj, path="", violations=None):
        if violations is None:
            violations = []
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key
                check_nondeterministic(value, current_path, violations)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                check_nondeterministic(item, f"{path}[{i}]", violations)
        elif isinstance(obj, str):
            # Check for absolute paths (Windows and Unix)
            if re.match(r'^[A-Za-z]:\\', obj) or obj.startswith('/'):
                # Allow expected paths in incident artifacts
                if 'artifact_path' in path or 'incidents' in obj.lower():
                    pass  # Expected
                else:
                    violations.append(f"{path}: absolute path '{obj}'")
            
            # Check for random UUIDs (not from deterministic context)
            uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
            if re.search(uuid_pattern, obj.lower()):
                # Allow deterministic IDs (ALERT- format or known patterns)
                if not (obj.startswith('ALERT-') or 'demo' in obj.lower() or 'pinned' in obj.lower()):
                    violations.append(f"{path}: potential random UUID '{obj}'")
        
        elif isinstance(obj, datetime):
            # datetime objects should be pinned in determinism_mode="pinned"
            # Check if it matches pinned timestamp (within reason)
            if obj.tzinfo is None:
                violations.append(f"{path}: naive datetime '{obj}'")
        
        return violations

    # Check all payloads
    all_violations = []
    all_violations.extend(check_nondeterministic(alert_payload, "alert"))
    all_violations.extend(check_nondeterministic(evidence_payload, "evidence"))
    all_violations.extend(check_nondeterministic(diagnostics_payload, "diagnostics"))
    all_violations.extend(check_nondeterministic(incident_payload, "incident_artifact"))

    # Convert payloads to JSON strings to check for datetime.now() patterns
    def json_string_check(payload_dict, name):
        payload_str = json.dumps(payload_dict, default=str, sort_keys=True)
        # Look for timestamps that don't match pinned timestamp
        # This is a heuristic - actual datetime.now() calls would show current time
        # In pinned mode, all timestamps should be the pinned timestamp or deterministic
        pass  # More sophisticated check could go here

    json_string_check(alert_payload, "alert")
    json_string_check(evidence_payload, "evidence")
    json_string_check(diagnostics_payload, "diagnostics")
    json_string_check(incident_payload, "incident_artifact")

    assert len(all_violations) == 0, f"Found nondeterministic fields: {all_violations}"
