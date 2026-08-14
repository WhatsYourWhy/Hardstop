import argparse
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from hardstop.cli import pipeline as pipeline_mod
from hardstop.cli import output as output_mod
from hardstop.ops import run_record
from hardstop.retrieval.fetcher import FetchResult


def _instrument_run_record(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"

    def _emit(**kwargs):
        kwargs["dest_dir"] = records_dir
        return run_record.emit_run_record(**kwargs)

    monkeypatch.setattr(pipeline_mod, "emit_run_record", _emit)
    monkeypatch.setattr(output_mod, "emit_run_record", _emit)
    return records_dir


def _load_validated_record(records_dir: Path) -> dict:
    files = sorted(records_dir.glob("*.json"))
    assert files, "expected run record to be written"
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/specs/run-record.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)
    return data


@contextmanager
def _fake_session_context(_path):
    session = SimpleNamespace(new=set(), commit=lambda: None, rollback=lambda: None)
    yield session


def _stub_config(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_mod, "load_config", lambda: {"storage": {"sqlite_path": str(tmp_path / "hardstop.db")}})
    monkeypatch.setattr(pipeline_mod, "resolve_config_snapshot", lambda: {"runtime": {"mode": "test"}})
    monkeypatch.setattr(output_mod, "load_config", lambda: {"storage": {"sqlite_path": str(tmp_path / "hardstop.db")}})
    monkeypatch.setattr(output_mod, "resolve_config_snapshot", lambda: {"runtime": {"mode": "test"}})


def _stub_noops(monkeypatch):
    for mod in (pipeline_mod, output_mod):
        for name in ("ensure_raw_items_table", "ensure_run_raw_items_table",
                      "ensure_event_external_fields",
                      "ensure_alert_correlation_columns", "ensure_trust_tier_columns",
                      "ensure_source_runs_table", "ensure_suppression_columns"):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, lambda *_, **__: None)


def test_cmd_fetch_emits_run_record_success(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(pipeline_mod, "session_context", _fake_session_context)
    monkeypatch.setattr(pipeline_mod, "get_all_sources", lambda _cfg: [{"id": "source-1", "tier": "global", "enabled": True}])
    monkeypatch.setattr(pipeline_mod, "load_sources_config", lambda: {"sources": []})
    monkeypatch.setattr(pipeline_mod, "_resolve_source_defaults", lambda src, _cfg: src)

    def _save_raw_item(session, **_kwargs):
        item = SimpleNamespace(status="NEW", raw_id="RAW-1", content_hash="hash-1")
        session.new.add(item)
        return item, "NEW"

    monkeypatch.setattr(pipeline_mod, "save_raw_item_with_action", _save_raw_item)
    monkeypatch.setattr(pipeline_mod, "record_run_raw_item", lambda *_, **__: None)
    monkeypatch.setattr(pipeline_mod, "create_source_run", lambda *_, **__: None)
    class _StubFetcher:
        def __init__(self, **_kwargs):
            self._meta = {"seed": 7, "inputs_version": "stub@1", "notes": "jitter_seconds=0"}

        def fetch_all(self, **_kwargs):
            return [
                FetchResult(
                    source_id="source-1",
                    fetched_at_utc="2024-01-01T00:00:00Z",
                    status="SUCCESS",
                    status_code=200,
                    duration_seconds=0.1,
                    items=[],
                    bytes_downloaded=10,
                )
            ]

        def best_effort_metadata(self):
            return self._meta

    monkeypatch.setattr(pipeline_mod, "SourceFetcher", _StubFetcher)

    args = argparse.Namespace(
        tier=None,
        enabled_only=True,
        max_items_per_source=5,
        since="24h",
        dry_run=False,
        fail_fast=False,
        strict=False,
    )
    pipeline_mod.cmd_fetch(args, run_group_id="group-fetch")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "hardstop.fetch@1.0.0"
    assert not data["errors"]
    assert any(ref["id"] == "run-group:group-fetch" for ref in data["input_refs"])
    assert any(ref["kind"] == "RawItemBatch" for ref in data["output_refs"])
    assert data["best_effort"]["seed"] == 7


def test_cmd_fetch_emits_run_record_on_failure(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(pipeline_mod, "session_context", _fake_session_context)

    class _FailingFetcher:
        def __init__(self, **_kwargs):
            self._meta = {}

        def fetch_all(self, **_kwargs):
            raise RuntimeError("fetch boom")

        def best_effort_metadata(self):
            return self._meta

    monkeypatch.setattr(pipeline_mod, "SourceFetcher", _FailingFetcher)
    monkeypatch.setattr(pipeline_mod, "load_sources_config", lambda: {"sources": []})
    monkeypatch.setattr(pipeline_mod, "get_all_sources", lambda _cfg: [])

    args = argparse.Namespace(
        tier=None,
        enabled_only=True,
        max_items_per_source=5,
        since="24h",
        dry_run=False,
        fail_fast=False,
        strict=True,
    )
    with pytest.raises(RuntimeError):
        pipeline_mod.cmd_fetch(args, run_group_id="group-fetch-fail")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "hardstop.fetch@1.0.0"
    assert data["errors"]


def test_cmd_ingest_emits_run_record_success(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(pipeline_mod, "session_context", _fake_session_context)
    monkeypatch.setattr(pipeline_mod, "ingest_external_main", lambda **__: {
        "processed": 2,
        "events": 1,
        "alerts": 1,
        "errors": 0,
        "suppressed": 0,
    })

    args = argparse.Namespace(
        limit=5,
        min_tier=None,
        source_id=None,
        since=None,
        no_suppress=False,
        explain_suppress=False,
        fail_fast=False,
        strict=True,
    )
    pipeline_mod.cmd_ingest_external(args, run_group_id="group-ingest")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "hardstop.ingest@1.0.0"
    assert data["mode"] == "strict"
    assert any(ref["kind"] == "SourceRun" for ref in data["output_refs"])


def test_cmd_ingest_emits_run_record_on_failure(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(pipeline_mod, "session_context", _fake_session_context)

    def _fail_ingest(**_kwargs):
        raise RuntimeError("ingest boom")

    monkeypatch.setattr(pipeline_mod, "ingest_external_main", _fail_ingest)

    args = argparse.Namespace(
        limit=5,
        min_tier=None,
        source_id=None,
        since=None,
        no_suppress=False,
        explain_suppress=False,
        fail_fast=False,
        strict=False,
    )
    with pytest.raises(RuntimeError):
        pipeline_mod.cmd_ingest_external(args, run_group_id="group-ingest-fail")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "hardstop.ingest@1.0.0"
    assert data["errors"]


def test_cmd_brief_emits_run_record_success(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(output_mod, "session_context", _fake_session_context)
    monkeypatch.setattr(output_mod, "generate_brief", lambda *_, **__: {"alerts": []})
    monkeypatch.setattr(output_mod, "render_markdown", lambda *_: "brief-md")

    args = argparse.Namespace(
        today=True,
        since="24h",
        format="md",
        limit=5,
        include_class0=False,
        strict=False,
    )
    output_mod.cmd_brief(args, run_group_id="group-brief")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "hardstop.brief@1.0.0"
    assert not data["errors"]
    assert any(ref["kind"] == "Brief" for ref in data["output_refs"])
    expected_hash = hashlib.sha256("brief-md".encode("utf-8")).hexdigest()
    assert any(ref["hash"] == expected_hash for ref in data["output_refs"])


def test_cmd_brief_emits_run_record_on_failure(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(output_mod, "session_context", _fake_session_context)

    def _fail_brief(*_args, **_kwargs):
        raise RuntimeError("brief boom")

    monkeypatch.setattr(output_mod, "generate_brief", _fail_brief)
    monkeypatch.setattr(output_mod, "render_markdown", lambda *_: "brief-md")

    args = argparse.Namespace(
        today=True,
        since="24h",
        format="md",
        limit=5,
        include_class0=False,
        strict=True,
    )
    with pytest.raises(RuntimeError):
        output_mod.cmd_brief(args, run_group_id="group-brief-fail")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "hardstop.brief@1.0.0"
    assert data["errors"]


def _create_required_tables(tmp_path):
    """
    Give the run a database that passes the readiness schema check.

    cmd_run's readiness gate (v1.3) reads the real sqlite file, so a test that
    expects an authoritative brief needs the four required tables present.
    """
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "hardstop.db"))
    for table in ("raw_items", "events", "alerts", "source_runs"):
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT);")
    conn.commit()
    conn.close()


def test_cmd_run_respects_readme_fetch_defaults(monkeypatch, tmp_path):
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    _create_required_tables(tmp_path)
    monkeypatch.setattr(pipeline_mod, "session_context", _fake_session_context)
    monkeypatch.setattr(pipeline_mod, "list_recent_runs", lambda *_, **__: [])
    monkeypatch.setattr(pipeline_mod, "get_all_source_health", lambda *_, **__: [])
    monkeypatch.setattr(pipeline_mod, "load_sources_config", lambda: {"version": 1, "tiers": {}, "defaults": {}})
    monkeypatch.setattr(pipeline_mod, "get_all_sources", lambda _cfg: [{"id": "source-1", "enabled": True}])
    monkeypatch.setattr(pipeline_mod, "load_suppression_config", lambda: {"version": 1, "enabled": True, "rules": []})
    monkeypatch.setattr(pipeline_mod, "emit_run_record", lambda **__: None)
    monkeypatch.setattr(pipeline_mod, "evaluate_run_status", lambda **__: (0, ["All systems healthy"]))

    import sys
    exit_codes: list[int] = []
    monkeypatch.setattr(sys, "exit", lambda code: exit_codes.append(code))

    captures = {}

    def _capture_fetch(args, run_group_id):
        captures["fetch_args"] = args
        captures["run_group_id"] = run_group_id

    def _capture_ingest(args, run_group_id):
        captures["ingest_args"] = args
        assert run_group_id == captures["run_group_id"]

    def _capture_brief(args, run_group_id, publication=None):
        captures["brief_args"] = args
        captures["publication"] = publication
        assert run_group_id == captures["run_group_id"]

    monkeypatch.setattr(pipeline_mod, "cmd_fetch", _capture_fetch)
    monkeypatch.setattr(pipeline_mod, "cmd_ingest_external", _capture_ingest)
    monkeypatch.setattr("hardstop.cli.output.cmd_brief", _capture_brief)

    args = argparse.Namespace(
        since="24h",
        stale="48h",
        strict=False,
        no_suppress=False,
        fail_fast=False,
        allow_ingest_errors=False,
    )

    pipeline_mod.cmd_run(args)

    assert captures["fetch_args"].max_items_per_source == 10
    # The brief stub must actually have run. cmd_run wraps the brief call in a
    # broad `except Exception`, so a signature mismatch here would otherwise be
    # swallowed and this test would pass while asserting nothing.
    assert "brief_args" in captures
    # Healthy readiness publishes an authoritative brief (no publication block).
    assert captures["publication"] is None
    assert exit_codes == [0]


def _run_gate_scenario(monkeypatch, tmp_path, *, strict, blocked_sources=()):
    """Drive cmd_run with stubs, returning what the brief step received."""
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    _create_required_tables(tmp_path)
    monkeypatch.setattr(pipeline_mod, "session_context", _fake_session_context)
    monkeypatch.setattr(pipeline_mod, "list_recent_runs", lambda *_, **__: [])
    monkeypatch.setattr(
        pipeline_mod,
        "get_all_source_health",
        lambda *_, **__: [
            {"source_id": sid, "health_budget_state": "BLOCKED"} for sid in blocked_sources
        ],
    )
    monkeypatch.setattr(pipeline_mod, "load_sources_config", lambda: {"version": 1})
    monkeypatch.setattr(pipeline_mod, "get_all_sources", lambda _cfg: [{"id": "source-1", "enabled": True}])
    monkeypatch.setattr(pipeline_mod, "load_suppression_config", lambda: {"enabled": True, "rules": []})
    monkeypatch.setattr(pipeline_mod, "emit_run_record", lambda **__: None)
    monkeypatch.setattr(pipeline_mod, "evaluate_run_status", lambda **kw: (0, []))

    import sys

    exit_codes: list[int] = []
    monkeypatch.setattr(sys, "exit", lambda code: exit_codes.append(code))

    captures = {"called": False}

    def _capture_brief(args, run_group_id, publication=None):
        captures["called"] = True
        captures["publication"] = publication

    monkeypatch.setattr(pipeline_mod, "cmd_fetch", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline_mod, "cmd_ingest_external", lambda *_a, **_k: None)
    monkeypatch.setattr("hardstop.cli.output.cmd_brief", _capture_brief)

    args = argparse.Namespace(
        since="24h",
        stale="48h",
        strict=strict,
        no_suppress=False,
        fail_fast=False,
        allow_ingest_errors=False,
    )
    pipeline_mod.cmd_run(args)
    captures["exit_codes"] = exit_codes
    return captures


def test_cmd_run_marks_brief_draft_only_when_readiness_broken(monkeypatch, tmp_path):
    """Best-effort: the brief still renders, but is flagged non-authoritative."""
    captures = _run_gate_scenario(
        monkeypatch, tmp_path, strict=False, blocked_sources=("src-bad",)
    )
    assert captures["called"] is True
    assert captures["publication"]["state"] == "DRAFT_ONLY"
    assert captures["publication"]["readiness_state"] == "BROKEN"
    assert any("src-bad" in reason for reason in captures["publication"]["reasons"])


def test_cmd_run_skips_brief_when_readiness_broken_in_strict(monkeypatch, tmp_path):
    """Strict: no authoritative brief is produced at all."""
    captures = _run_gate_scenario(
        monkeypatch, tmp_path, strict=True, blocked_sources=("src-bad",)
    )
    assert captures["called"] is False


def test_cmd_run_publishes_normally_when_ready(monkeypatch, tmp_path):
    for strict in (False, True):
        captures = _run_gate_scenario(monkeypatch, tmp_path, strict=strict)
        assert captures["called"] is True
        assert captures["publication"] is None


def test_cmd_run_still_evaluates_status_when_subcommand_exits(monkeypatch, tmp_path):
    """
    SystemExit from a sub-command must not skip Step 4.

    SystemExit is a BaseException, so it escapes cmd_run's `except Exception`
    guards. If it were not caught explicitly, run status would never be
    evaluated and the run's exit code would come from the sub-command alone.
    """
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    _create_required_tables(tmp_path)
    monkeypatch.setattr(pipeline_mod, "session_context", _fake_session_context)
    monkeypatch.setattr(pipeline_mod, "list_recent_runs", lambda *_, **__: [])
    monkeypatch.setattr(pipeline_mod, "get_all_source_health", lambda *_, **__: [])
    monkeypatch.setattr(pipeline_mod, "load_sources_config", lambda: {"version": 1})
    monkeypatch.setattr(pipeline_mod, "get_all_sources", lambda _cfg: [{"id": "s", "enabled": True}])
    monkeypatch.setattr(pipeline_mod, "load_suppression_config", lambda: {"enabled": True, "rules": []})
    monkeypatch.setattr(pipeline_mod, "emit_run_record", lambda **__: None)

    evaluated = {"called": False}

    def _evaluate(**_kwargs):
        evaluated["called"] = True
        return (0, [])

    monkeypatch.setattr(pipeline_mod, "evaluate_run_status", _evaluate)

    def _exiting_fetch(*_a, **_k):
        raise SystemExit(2)

    monkeypatch.setattr(pipeline_mod, "cmd_fetch", _exiting_fetch)
    monkeypatch.setattr(pipeline_mod, "cmd_ingest_external", lambda *_a, **_k: None)
    monkeypatch.setattr("hardstop.cli.output.cmd_brief", lambda *_a, **_k: None)

    import sys

    exit_codes: list[int] = []
    monkeypatch.setattr(sys, "exit", lambda code: exit_codes.append(code))

    args = argparse.Namespace(
        since="24h", stale="48h", strict=False,
        no_suppress=False, fail_fast=False, allow_ingest_errors=False,
    )
    pipeline_mod.cmd_run(args)

    assert evaluated["called"] is True, "Step 4 was skipped by a sub-command SystemExit"
    # The sub-command's exit code survives even though run status was healthy.
    assert exit_codes == [2]


# --- v1.3 export provenance and strict escalation -----------------------------


def _export_args(tmp_path, **overrides):
    args = argparse.Namespace(
        export_type="alerts",
        since=None,
        classification=None,
        tier=None,
        source_id=None,
        limit=10,
        format="json",
        out=None,
        strict=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _stub_export(monkeypatch, result="{}"):
    monkeypatch.setattr(output_mod, "session_context", _fake_session_context)
    import hardstop.api.export as export_mod

    monkeypatch.setattr(export_mod, "export_alerts", lambda *_a, **_k: result)


def test_cmd_export_emits_run_record(monkeypatch, tmp_path):
    """Export was previously the only artifact-producing command with no RunRecord."""
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    _stub_export(monkeypatch, result='{"data": []}')

    output_mod.cmd_export(_export_args(tmp_path), run_group_id="group-export")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "hardstop.export@1.0.0"
    assert not data["errors"]
    assert any(ref["id"] == "run-group:group-export" for ref in data["input_refs"])
    assert any(ref["kind"] == "ExportFilter" for ref in data["input_refs"])
    assert any(ref["kind"] == "Export" for ref in data["output_refs"])


def test_cmd_export_hashes_file_bytes_when_writing_to_disk(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)

    out = tmp_path / "alerts.json"

    def _export(*_a, **kwargs):
        kwargs["out"].write_text('{"data": []}', encoding="utf-8", newline="")
        return f"Exported to {kwargs['out']}"

    monkeypatch.setattr(output_mod, "session_context", _fake_session_context)
    import hardstop.api.export as export_mod

    monkeypatch.setattr(export_mod, "export_alerts", _export)

    output_mod.cmd_export(_export_args(tmp_path, out=out), run_group_id="group-export-file")

    data = _load_validated_record(records_dir)
    export_ref = next(ref for ref in data["output_refs"] if ref["kind"] == "Export")
    assert export_ref["hash"] == hashlib.sha256(out.read_bytes()).hexdigest()


def test_cmd_export_strict_run_record_failure_exits_2(monkeypatch, tmp_path):
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    _stub_export(monkeypatch)

    def _boom(**_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(output_mod, "emit_run_record", _boom)

    with pytest.raises(SystemExit) as excinfo:
        output_mod.cmd_export(_export_args(tmp_path, strict=True))
    assert excinfo.value.code == 2


def test_cmd_export_best_effort_run_record_failure_is_tolerated(monkeypatch, tmp_path):
    """Best-effort keeps pre-v1.3 behavior: warn and continue."""
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    _stub_export(monkeypatch)

    monkeypatch.setattr(output_mod, "emit_run_record", lambda **_k: (_ for _ in ()).throw(OSError("disk full")))

    output_mod.cmd_export(_export_args(tmp_path, strict=False))  # must not raise


def test_cmd_brief_strict_run_record_failure_exits_2(monkeypatch, tmp_path):
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(output_mod, "session_context", _fake_session_context)
    monkeypatch.setattr(output_mod, "generate_brief", lambda *_, **__: {"alerts": []})
    monkeypatch.setattr(output_mod, "render_markdown", lambda *_: "brief-md")
    monkeypatch.setattr(
        output_mod, "emit_run_record", lambda **_k: (_ for _ in ()).throw(OSError("disk full"))
    )

    args = argparse.Namespace(
        today=True, since="24h", format="md", limit=5, include_class0=False, strict=True
    )
    with pytest.raises(SystemExit) as excinfo:
        output_mod.cmd_brief(args)
    assert excinfo.value.code == 2


def test_run_record_failure_does_not_mask_command_error(monkeypatch, tmp_path):
    """
    Precedence guard.

    When the command body fails *and* RunRecord emission fails, the caller must
    see the real error, not a provenance SystemExit. Escalating from inside the
    finally block would invert this.
    """
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(output_mod, "session_context", _fake_session_context)

    def _explode(*_a, **_k):
        raise RuntimeError("brief generation blew up")

    monkeypatch.setattr(output_mod, "generate_brief", _explode)
    monkeypatch.setattr(
        output_mod, "emit_run_record", lambda **_k: (_ for _ in ()).throw(OSError("disk full"))
    )

    args = argparse.Namespace(
        today=True, since="24h", format="md", limit=5, include_class0=False, strict=True
    )
    with pytest.raises(RuntimeError, match="brief generation blew up"):
        output_mod.cmd_brief(args)


def test_cmd_brief_marks_draft_only_in_run_record(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(output_mod, "session_context", _fake_session_context)
    monkeypatch.setattr(output_mod, "generate_brief", lambda *_, **__: {"alerts": []})
    monkeypatch.setattr(output_mod, "render_markdown", lambda *_: "brief-md")

    args = argparse.Namespace(
        today=True, since="24h", format="md", limit=5, include_class0=False, strict=False
    )
    output_mod.cmd_brief(
        args,
        run_group_id="group-draft",
        publication={"state": "DRAFT_ONLY", "readiness_state": "BROKEN", "reasons": ["src-bad blocked"]},
    )

    data = _load_validated_record(records_dir)
    assert any(w["code"] == "BRIEF_DRAFT_ONLY" for w in data["warnings"])
