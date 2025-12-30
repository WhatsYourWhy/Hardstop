import argparse
from pathlib import Path

import pytest

from hardstop import cli
from hardstop.output.incidents import build_incident_evidence_artifact


def test_incident_replay_best_effort_warns_on_missing_run_record(monkeypatch, tmp_path: Path):
    artifacts_dir = tmp_path / "incidents"
    records_dir = tmp_path / "records"
    snapshot = {"runtime": {"mode": "best-effort"}}

    build_incident_evidence_artifact(
        alert_id="ALERT-ABC",
        event={"event_id": "EVT-1", "event_type": "SPILL", "title": "spill"},
        correlation_key="SPILL|X|Y",
        existing_alert=type("Obj", (), {"alert_id": "ALERT-ABC", "last_seen_utc": None, "scope_json": "{}", "root_event_ids_json": "[]"})(),
        window_hours=12,
        dest_dir=artifacts_dir,
        generated_at="2024-06-01T00:00:00Z",
        filename_basename="ALERT-ABC__EVT-1__SPILL_X_Y",
    )

    monkeypatch.setattr(cli, "resolve_config_snapshot", lambda: snapshot)

    args = argparse.Namespace(
        incident_id="ALERT-ABC",
        correlation_key=None,
        artifacts_dir=artifacts_dir,
        records_dir=records_dir,
        strict=False,
        format="json",
    )

    result = cli.cmd_incidents_replay(args)
    assert result["artifact_hash"]
    assert result["run_record_id"] is None
    assert result["warnings"]


def test_incident_replay_strict_missing_artifact(monkeypatch, tmp_path: Path):
    artifacts_dir = tmp_path / "incidents"
    records_dir = tmp_path / "records"
    snapshot = {"runtime": {"mode": "strict"}}
    monkeypatch.setattr(cli, "resolve_config_snapshot", lambda: snapshot)

    args = argparse.Namespace(
        incident_id="ALERT-NONE",
        correlation_key=None,
        artifacts_dir=artifacts_dir,
        records_dir=records_dir,
        strict=True,
        format="json",
    )

    with pytest.raises(FileNotFoundError):
        cli.cmd_incidents_replay(args)
