import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema

from hardstop import cli
import hardstop.ops.run_record as run_record_module
from hardstop.output.incidents import build_incident_evidence_artifact
from hardstop.ops.run_record import (
    ArtifactRef,
    Diagnostic,
    canonicalize_time_factory,
    emit_run_record,
    fingerprint_config,
    resolve_config_snapshot,
)


def test_fingerprint_config_stable():
    snapshot = {
        "runtime": {
            "version": "1.2.3",
            "flags": {"strict": True, "batch_size": 50},
        },
        "sources": {
            "tiers": {
                "global": [
                    {"id": "source-a", "enabled": True},
                    {"enabled": False, "id": "source-b"},
                ]
            }
        },
    }
    expected = "820342a4ce6727751edc1507f62bf997a4bd74fc51cb5dea9163c060ed61d58b"
    assert fingerprint_config(snapshot) == expected


def test_emit_run_record_matches_schema(tmp_path: Path):
    input_ref = ArtifactRef(
        id="run-group-123",
        hash="d2b2ce9d8c9e4fd6958be1c179c3f5f9d7cc696ef7e0f0cc8f71bb5c8a0697ec",
        kind="RunGroup",
    )
    output_ref = ArtifactRef(
        id="run-status-123",
        hash="4f0a9399a1820ca128f61a9bc3dfc1390dca8f700c3687342a1cd87f5f9f8b1d",
        kind="RunStatus",
    )
    warning = Diagnostic(code="WARN001", message="Example warning")
    record = emit_run_record(
        operator_id="hardstop.run@1.0.0",
        mode="strict",
        config_snapshot={"runtime": {"version": "1.0.0"}},
        input_refs=[input_ref],
        output_refs=[output_ref],
        warnings=[warning],
        dest_dir=tmp_path,
    )
    files = list(tmp_path.glob("*.json"))
    assert files, "expected run record file to be created"
    data = json.loads(files[0].read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/specs/run-record.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)
    assert record.config_hash == fingerprint_config({"runtime": {"version": "1.0.0"}})


def test_emit_run_record_replay_mode_fixed_identifiers(tmp_path: Path):
    fixed_run_id = "11111111-1111-1111-1111-111111111111"
    canonicalize_time = canonicalize_time_factory(precision=0)
    input_ref = ArtifactRef(
        id="run-group-fixed",
        hash="c55a2811006f7c3725b0416330d9a261528560aab54d4f23e97114fead92d9f0",
        kind="RunGroup",
    )
    output_ref = ArtifactRef(
        id="brief:fixed",
        hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        kind="Brief",
    )
    started_at = "2024-01-01T00:00:00.123456Z"
    ended_at = "2024-01-01T00:05:00.987654Z"
    record = emit_run_record(
        operator_id="hardstop.brief@1.0.0",
        mode="strict",
        run_id=fixed_run_id,
        started_at=started_at,
        ended_at=ended_at,
        canonicalize_time=canonicalize_time,
        config_snapshot={"runtime": {"version": "1.2.3"}, "sources": {"a": 1}},
        input_refs=[input_ref],
        output_refs=[output_ref],
        filename_basename="replay_run",
        dest_dir=tmp_path,
    )

    target = tmp_path / "replay_run.json"
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["run_id"] == fixed_run_id
    assert data["started_at"] == "2024-01-01T00:00:00Z"
    assert data["ended_at"] == "2024-01-01T00:05:00Z"
    assert data["output_refs"][0]["hash"] == output_ref.hash
    assert record.config_hash == fingerprint_config({"runtime": {"version": "1.2.3"}, "sources": {"a": 1}})


def test_emit_run_record_failure_includes_errors_and_schema_valid(tmp_path: Path):
    run_group_id = "rg-123"
    config_snapshot = {
        "runtime": {"mode": "strict", "run_group_id": run_group_id, "version": "9.9.9"},
        "sources": {
            "version": 1,
            "tiers": {
                "global": [{"id": "source-a", "tier": "global", "type": "http", "url": "https://example.com"}]
            },
        },
    }
    canonicalize_time = canonicalize_time_factory(precision=0)
    record = emit_run_record(
        operator_id="hardstop.failure@1.0.0",
        mode="strict",
        run_id="00000000-0000-0000-0000-000000000999",
        started_at="2024-02-01T05:06:07.123456Z",
        ended_at="2024-02-01T05:16:07.654321Z",
        canonicalize_time=canonicalize_time,
        config_snapshot=config_snapshot,
        input_refs=[
            ArtifactRef(
                id=f"run-group:{run_group_id}",
                hash=hashlib.sha256(run_group_id.encode("utf-8")).hexdigest(),
                kind="RunGroup",
            )
        ],
        output_refs=[
            ArtifactRef(id="failed-output", hash="f" * 64, kind="RunStatus"),
        ],
        warnings=[Diagnostic(code="WARN999", message="Heads up")],
        errors=[Diagnostic(code="ERR500", message="failed downstream", details={"phase": "ingest"})],
        dest_dir=tmp_path,
    )
    files = sorted(tmp_path.glob("*.json"))
    assert files, "expected run record file to be created"
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/specs/run-record.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)
    expected_hash = fingerprint_config(config_snapshot)
    assert data["errors"][0]["code"] == "ERR500"
    assert data["errors"][0]["details"]["phase"] == "ingest"
    assert data["warnings"][0]["code"] == "WARN999"
    assert data["mode"] == "strict"
    assert data["config_hash"] == expected_hash == record.config_hash
    assert data["input_refs"][0]["id"] == f"run-group:{run_group_id}"


def test_resolve_config_snapshot_produces_stable_hash(monkeypatch):
    run_group_id = "rg-123"
    runtime_cfg = {"mode": "strict", "run_group_id": run_group_id, "version": "9.9.9"}
    sources_cfg = {
        "version": 1,
        "tiers": {
            "global": [{"id": "source-a", "tier": "global", "type": "http", "url": "https://example.com"}]
        },
    }
    suppression_cfg = {"version": 2, "rules": [{"id": "sup-1", "match": "*"}]}

    monkeypatch.setattr(run_record_module, "load_config", lambda: dict(runtime_cfg))
    monkeypatch.setattr(run_record_module, "load_sources_config", lambda: dict(sources_cfg))
    monkeypatch.setattr(run_record_module, "load_suppression_config", lambda: dict(suppression_cfg))

    expected_snapshot = {
        "runtime": runtime_cfg,
        "sources": sources_cfg,
        "suppression": suppression_cfg,
    }
    expected_hash = "830a0822c5c9ddebb603caa8f9b7e3d2cf2a448dc89e8de2101fe65a789e1e1f"

    first_snapshot = resolve_config_snapshot()
    second_snapshot = resolve_config_snapshot()

    assert first_snapshot == expected_snapshot
    assert second_snapshot == expected_snapshot
    assert fingerprint_config(first_snapshot) == expected_hash
    assert fingerprint_config(second_snapshot) == expected_hash


def test_emit_run_record_cli_smoke_deterministic_filename(tmp_path: Path):
    started_at = "2024-03-03T10:11:12Z"
    run_id = "22222222-2222-2222-2222-222222222222"
    dest_dir = tmp_path / "cli"
    dest_dir.mkdir()
    emit_run_record(
        operator_id="hardstop.cli@1.0.0",
        mode="best-effort",
        run_id=run_id,
        started_at=started_at,
        ended_at="2024-03-03T10:21:12Z",
        canonicalize_time=canonicalize_time_factory(precision=0),
        config_snapshot={"runtime": {"mode": "best-effort"}, "sources": {}, "suppression": {}},
        input_refs=[],
        output_refs=[],
        dest_dir=dest_dir,
    )
    expected_filename = (
        dest_dir / f"{started_at.replace(':', '').replace('-', '').replace('T', '_')}_{run_id}.json"
    )
    assert expected_filename.exists()
    data = json.loads(expected_filename.read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/specs/run-record.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)
    assert data["run_id"] == run_id
    assert data["mode"] == "best-effort"


def test_cmd_incidents_replay_emits_run_record(monkeypatch, tmp_path: Path):
    records_dir = tmp_path / "records"
    artifacts_dir = tmp_path / "incidents"
    snapshot = {"runtime": {"mode": "strict"}, "sources": {"version": 1}}

    # Seed baseline artifact and RunRecord to replay
    artifact, artifact_ref, _ = build_incident_evidence_artifact(
        alert_id="ALERT-XYZ",
        event={"event_id": "EVT-1", "event_type": "SPILL", "title": "test spill"},
        correlation_key="SPILL|A|B",
        existing_alert=SimpleNamespace(
            alert_id="ALERT-XYZ",
            correlation_key="SPILL|A|B",
            last_seen_utc="2024-05-01T00:00:00Z",
            scope_json=json.dumps({"facilities": ["A"], "lanes": ["B"], "shipments": []}),
            root_event_ids_json=json.dumps(["EVT-0"]),
        ),
        window_hours=24,
        dest_dir=artifacts_dir,
        generated_at="2024-05-02T00:00:00Z",
        filename_basename="ALERT-XYZ__EVT-1__SPILL_A_B",
    )
    run_record_module.emit_run_record(
        operator_id="correlation.window@1.0.0",
        mode="strict",
        config_snapshot=snapshot,
        input_refs=[],
        output_refs=[artifact_ref],
        dest_dir=records_dir,
    )

    monkeypatch.setattr(cli, "resolve_config_snapshot", lambda: snapshot)
    args = argparse.Namespace(
        incident_id="ALERT-XYZ",
        correlation_key="SPILL|A|B",
        artifacts_dir=artifacts_dir,
        records_dir=records_dir,
        strict=True,
        format="json",
    )

    result = cli.cmd_incidents_replay(args)
    assert result["artifact_hash"] == artifact.artifact_hash
    files = sorted(records_dir.glob("*.json"))
    assert len(files) >= 2  # baseline + replay
    replay_record = json.loads(files[-1].read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/specs/run-record.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=replay_record, schema=schema)
    assert replay_record["operator_id"] == "hardstop.incidents.replay@1.0.0"
    assert replay_record["config_hash"] == fingerprint_config(snapshot)
