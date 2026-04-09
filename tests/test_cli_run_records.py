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
        for name in ("ensure_raw_items_table", "ensure_event_external_fields",
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
        item = SimpleNamespace(status="NEW")
        session.new.add(item)
        return item

    monkeypatch.setattr(pipeline_mod, "save_raw_item", _save_raw_item)
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


def test_cmd_run_respects_readme_fetch_defaults(monkeypatch, tmp_path):
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
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

    def _capture_brief(args, run_group_id):
        captures["brief_args"] = args
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
    assert exit_codes == [0]
