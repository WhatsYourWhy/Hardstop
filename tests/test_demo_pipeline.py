import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hardstop.alerts.alert_builder import build_basic_alert
from hardstop.cli import setup as setup_mod
from hardstop.database.sqlite_client import session_context
from hardstop.ingestion.file_ingestor import ingest_all_csvs
from hardstop.parsing.entity_extractor import attach_dummy_entities
from hardstop.parsing.network_linker import link_event_to_network
from hardstop.parsing.normalizer import normalize_event
from hardstop.runners import run_demo as run_demo_mod
from hardstop.runners.run_demo import (
    DEFAULT_PINNED_RUN_ID,
    DEFAULT_PINNED_SEED,
    DEFAULT_PINNED_TIMESTAMP,
    DemoDeterminismConfig,
    _run_demo,
    demo_event_id_for_path,
    demo_pinned_seed_for_path,
)
from hardstop.utils.id_generator import deterministic_id_context

FACILITIES = Path("tests/fixtures/facilities.csv")
LANES = Path("tests/fixtures/lanes.csv")
SHIPMENTS = Path("tests/fixtures/shipments_snapshot.csv")
SPILL_FIXTURE = Path("tests/fixtures/event_spill.json")
WEATHER_FIXTURE = Path("tests/fixtures/event_weather.json")

# Stable hashes for the in-process pinned builder path (EVT-DEMO-0001 + base seed).
PINNED_SPILL_HASH = "8ab0c3c00fbd4e65164c8fed8e193452e8109b029958d38c41756d41c0968f0f"
PINNED_WEATHER_HASH = "e7a61c0bc07242aec3db14d4ba998d688207925d0a97dfb27a37508d351ecd3e"
PINNED_ALERT_ID = "ALERT-20251229-d31a370b"


def test_demo_pipeline():
    event_path = SPILL_FIXTURE
    raw = json.loads(event_path.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-TEST-0001"

    event = normalize_event(raw)
    event = attach_dummy_entities(event)

    alert = build_basic_alert(event)
    assert alert.alert_id.startswith("ALERT-")
    assert alert.root_event_id == "EVT-TEST-0001"
    assert alert.classification in (0, 1, 2)
    assert alert.scope.facilities


@pytest.mark.parametrize(
    ("fixture_path", "expected_risk", "expected_score", "expected_hash", "synthetic"),
    [
        (SPILL_FIXTURE, "SAFETY_AND_OPERATIONS", 5, PINNED_SPILL_HASH, False),
        (WEATHER_FIXTURE, "WEATHER", 4, PINNED_WEATHER_HASH, True),
    ],
    ids=["spill", "weather"],
)
def test_pinned_demo_output_is_stable(
    tmp_path,
    session,
    fixture_path,
    expected_risk,
    expected_score,
    expected_hash,
    synthetic,
):
    ingest_all_csvs(FACILITIES, LANES, SHIPMENTS, session)

    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    if synthetic:
        assert "[SYNTHETIC]" in raw["title"]
    raw["event_id"] = "EVT-DEMO-0001"

    event = normalize_event(raw)
    event = link_event_to_network(event, session=session)

    assert event["event_type"] == expected_risk
    assert event["facilities"] == ["PLANT-01"]
    assert event["link_provenance"].get("facility") == "CITY_STATE"
    assert any("Avon, IN" in note for note in event["linking_notes"])

    pinned_dt = DEFAULT_PINNED_TIMESTAMP
    pinned_iso = pinned_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
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

    assert alert.alert_id == PINNED_ALERT_ID
    assert alert.risk_type == expected_risk
    assert alert.scope.facilities == ["PLANT-01"]
    assert "LANE-001" in alert.scope.lanes
    assert alert.evidence.diagnostics.impact_score == expected_score
    breakdown = alert.evidence.diagnostics.impact_score_breakdown
    assert any("PLANT-01" in item for item in breakdown)
    assert any("Priority shipments" in item for item in breakdown)

    incident_summary = alert.evidence.incident_evidence
    artifact_path = Path(incident_summary.artifact_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert payload["determinism_mode"] == "pinned"
    assert payload["determinism_context"] == determinism_context
    assert payload["merge_reasons"] == []
    assert payload["merge_summary"] == []
    assert payload["inputs"]["event"]["event_type"] == expected_risk
    assert incident_summary.artifact_hash == expected_hash
    assert payload["artifact_hash"] == expected_hash


def test_pinned_demo_replay_is_identical(tmp_path, session):
    """Test that running the pinned pipeline twice produces identical outputs."""
    ingest_all_csvs(FACILITIES, LANES, SHIPMENTS, session)

    raw = json.loads(SPILL_FIXTURE.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-DEMO-0001"

    pinned_dt = DEFAULT_PINNED_TIMESTAMP
    pinned_iso = pinned_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

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

    assert alert_1.alert_id == alert_2.alert_id, "Alert IDs must be identical"
    assert alert_1.classification == alert_2.classification, "Classifications must be identical"

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
    assert alert_1.reasoning == alert_2.reasoning

    qv_1 = alert_1.evidence.diagnostics.quality_validation if alert_1.evidence and alert_1.evidence.diagnostics else {}
    qv_2 = alert_2.evidence.diagnostics.quality_validation if alert_2.evidence and alert_2.evidence.diagnostics else {}
    assert qv_1 == qv_2


def test_no_nondeterministic_fields_in_alert_payload(tmp_path, session):
    """Test that alert payloads contain no nondeterministic fields."""
    import re

    ingest_all_csvs(FACILITIES, LANES, SHIPMENTS, session)

    raw = json.loads(SPILL_FIXTURE.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-DEMO-0001"

    event = normalize_event(raw)
    event = link_event_to_network(event, session=session)

    pinned_dt = DEFAULT_PINNED_TIMESTAMP
    pinned_iso = pinned_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
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

    alert_payload = alert.model_dump()
    evidence_payload = alert.evidence.model_dump() if alert.evidence else {}
    diagnostics_payload = (
        alert.evidence.diagnostics.model_dump()
        if alert.evidence and alert.evidence.diagnostics
        else {}
    )

    incident_summary = alert.evidence.incident_evidence if alert.evidence else None
    incident_payload = {}
    if incident_summary and incident_summary.artifact_path:
        artifact_path = Path(incident_summary.artifact_path)
        if artifact_path.exists():
            incident_payload = json.loads(artifact_path.read_text(encoding="utf-8"))

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
            if re.match(r"^[A-Za-z]:\\", obj) or obj.startswith("/"):
                if "artifact_path" in path or "incidents" in obj.lower():
                    pass
                else:
                    violations.append(f"{path}: absolute path '{obj}'")

            uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            if re.search(uuid_pattern, obj.lower()):
                if not (obj.startswith("ALERT-") or "demo" in obj.lower() or "pinned" in obj.lower()):
                    violations.append(f"{path}: potential random UUID '{obj}'")

        elif isinstance(obj, datetime):
            if obj.tzinfo is None:
                violations.append(f"{path}: naive datetime '{obj}'")

        return violations

    all_violations = []
    all_violations.extend(check_nondeterministic(alert_payload, "alert"))
    all_violations.extend(check_nondeterministic(evidence_payload, "evidence"))
    all_violations.extend(check_nondeterministic(diagnostics_payload, "diagnostics"))
    all_violations.extend(check_nondeterministic(incident_payload, "incident_artifact"))

    assert len(all_violations) == 0, f"Found nondeterministic fields: {all_violations}"


def _demo_config(db_path: Path, event_json: Path) -> dict:
    return {
        "storage": {"sqlite_path": str(db_path)},
        "demo": {
            "facilities_csv": str(FACILITIES),
            "lanes_csv": str(LANES),
            "shipments_csv": str(SHIPMENTS),
            "event_json": str(event_json),
        },
        "logging": {"level": "WARNING"},
        "domain": {"active_pack": "supply_chain"},
        "alert_quality": {
            "min_confidence_class_1": 0.60,
            "min_confidence_class_2": 0.70,
            "min_confidence_ambiguous": 0.50,
            "allow_quality_override_floor": True,
        },
    }


def _ingest_demo_db(db_path: Path) -> None:
    with session_context(str(db_path)) as session:
        ingest_all_csvs(FACILITIES, LANES, SHIPMENTS, session)


def test_pinned_demo_different_fixtures_do_not_collide(tmp_path, monkeypatch):
    """Different fixtures on one DB must get distinct pinned alert IDs (no PK clash)."""
    db_path = tmp_path / "hardstop.db"
    incidents_dir = tmp_path / "incidents"
    _ingest_demo_db(db_path)

    monkeypatch.setattr(
        run_demo_mod,
        "load_config",
        lambda: _demo_config(db_path, WEATHER_FIXTURE),
    )

    weather_event, weather_alert = _run_demo(
        DemoDeterminismConfig(mode="pinned"),
        event_json=str(WEATHER_FIXTURE),
        incident_dest_dir=incidents_dir,
    )
    spill_event, spill_alert = _run_demo(
        DemoDeterminismConfig(mode="pinned"),
        event_json=str(SPILL_FIXTURE),
        incident_dest_dir=incidents_dir,
    )

    assert weather_event["event_id"] == demo_event_id_for_path(WEATHER_FIXTURE)
    assert spill_event["event_id"] == demo_event_id_for_path(SPILL_FIXTURE)
    assert weather_alert.alert_id != spill_alert.alert_id
    assert weather_alert.risk_type == "WEATHER"
    assert spill_alert.risk_type == "SAFETY_AND_OPERATIONS"

    # Same fixture again stays deterministic and does not collide with itself.
    _, weather_again = _run_demo(
        DemoDeterminismConfig(mode="pinned"),
        event_json=str(WEATHER_FIXTURE),
        incident_dest_dir=incidents_dir,
    )
    assert weather_again.alert_id == weather_alert.alert_id


def test_cmd_demo_event_flag_and_config_default(tmp_path, monkeypatch, capsys):
    """Exercise config default and --event through run_demo.main / cmd_demo."""
    db_path = tmp_path / "hardstop.db"
    incidents_dir = tmp_path / "incidents"
    _ingest_demo_db(db_path)

    monkeypatch.setattr(
        run_demo_mod,
        "load_config",
        lambda: _demo_config(db_path, WEATHER_FIXTURE),
    )

    real_run_demo = run_demo_mod._run_demo

    def _run_demo_tmp(determinism, event_json=None, *, incident_dest_dir=None):
        return real_run_demo(
            determinism,
            event_json=event_json,
            incident_dest_dir=incident_dest_dir or incidents_dir,
        )

    monkeypatch.setattr(run_demo_mod, "_run_demo", _run_demo_tmp)

    # Config default (weather) via runner entry point.
    run_demo_mod.main(mode="pinned")
    default_out = json.loads(capsys.readouterr().out)
    assert default_out["risk_type"] == "WEATHER"
    assert default_out["root_event_id"] == demo_event_id_for_path(WEATHER_FIXTURE)
    assert default_out["alert_id"].startswith("ALERT-20251229-")
    assert default_out["evidence"]["diagnostics"]["impact_score"] == 4

    # --event override via CLI command wiring.
    args = argparse.Namespace(
        mode="pinned",
        seed=None,
        timestamp=None,
        run_id=None,
        event=str(SPILL_FIXTURE),
    )
    setup_mod.cmd_demo(args)
    override_out = json.loads(capsys.readouterr().out)
    assert override_out["risk_type"] == "SAFETY_AND_OPERATIONS"
    assert override_out["root_event_id"] == demo_event_id_for_path(SPILL_FIXTURE)
    assert override_out["alert_id"] != default_out["alert_id"]
    assert override_out["alert_id"].startswith("ALERT-20251229-")

    # Effective seeds must include fixture identity.
    assert demo_pinned_seed_for_path(DEFAULT_PINNED_SEED, WEATHER_FIXTURE).endswith(
        "|event_weather"
    )
    assert demo_pinned_seed_for_path(DEFAULT_PINNED_SEED, SPILL_FIXTURE).endswith("|event_spill")
