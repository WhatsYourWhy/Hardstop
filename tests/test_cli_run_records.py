import argparse
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from sentinel import cli
from sentinel.ops import run_record
from sentinel.retrieval.fetcher import FetchResult


def _instrument_run_record(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"

    def _emit(**kwargs):
        kwargs["dest_dir"] = records_dir
        return run_record.emit_run_record(**kwargs)

    monkeypatch.setattr(cli, "emit_run_record", _emit)
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
    monkeypatch.setattr(cli, "load_config", lambda: {"storage": {"sqlite_path": str(tmp_path / "sentinel.db")}})
    monkeypatch.setattr(cli, "resolve_config_snapshot", lambda: {"runtime": {"mode": "test"}})


def _stub_noops(monkeypatch):
    monkeypatch.setattr(cli, "ensure_raw_items_table", lambda *_, **__: None)
    monkeypatch.setattr(cli, "ensure_event_external_fields", lambda *_, **__: None)
    monkeypatch.setattr(cli, "ensure_alert_correlation_columns", lambda *_, **__: None)
    monkeypatch.setattr(cli, "ensure_trust_tier_columns", lambda *_, **__: None)
    monkeypatch.setattr(cli, "ensure_source_runs_table", lambda *_, **__: None)
    monkeypatch.setattr(cli, "ensure_suppression_columns", lambda *_, **__: None)


def test_cmd_fetch_emits_run_record_success(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(cli, "session_context", _fake_session_context)
    monkeypatch.setattr(cli, "get_all_sources", lambda _cfg: [{"id": "source-1", "tier": "global", "enabled": True}])
    monkeypatch.setattr(cli, "load_sources_config", lambda: {"sources": []})
    monkeypatch.setattr(cli, "get_source_with_defaults", lambda src, _cfg: src)

    def _save_raw_item(session, **_kwargs):
        item = SimpleNamespace(status="NEW")
        session.new.add(item)
        return item

    monkeypatch.setattr(cli, "save_raw_item", _save_raw_item)
    monkeypatch.setattr(cli, "create_source_run", lambda *_, **__: None)
    monkeypatch.setattr(cli, "SourceFetcher", lambda: SimpleNamespace(fetch_all=lambda **__: [
        FetchResult(
            source_id="source-1",
            fetched_at_utc="2024-01-01T00:00:00Z",
            status="SUCCESS",
            status_code=200,
            duration_seconds=0.1,
            items=[],
            bytes_downloaded=10,
        )
    ]))

    args = argparse.Namespace(
        tier=None,
        enabled_only=True,
        max_items_per_source=5,
        since="24h",
        dry_run=False,
        fail_fast=False,
        strict=False,
    )
    cli.cmd_fetch(args, run_group_id="group-fetch")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "sentinel.fetch@1.0.0"
    assert not data["errors"]
    assert any(ref["id"] == "run-group:group-fetch" for ref in data["input_refs"])
    assert any(ref["kind"] == "RawItemBatch" for ref in data["output_refs"])


def test_cmd_fetch_emits_run_record_on_failure(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(cli, "session_context", _fake_session_context)

    class _FailingFetcher:
        def fetch_all(self, **_kwargs):
            raise RuntimeError("fetch boom")

    monkeypatch.setattr(cli, "SourceFetcher", lambda: _FailingFetcher())
    monkeypatch.setattr(cli, "load_sources_config", lambda: {"sources": []})
    monkeypatch.setattr(cli, "get_all_sources", lambda _cfg: [])

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
        cli.cmd_fetch(args, run_group_id="group-fetch-fail")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "sentinel.fetch@1.0.0"
    assert data["errors"]


def test_cmd_ingest_emits_run_record_success(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(cli, "session_context", _fake_session_context)
    monkeypatch.setattr(cli, "ingest_external_main", lambda **__: {
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
    cli.cmd_ingest_external(args, run_group_id="group-ingest")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "sentinel.ingest@1.0.0"
    assert data["mode"] == "strict"
    assert any(ref["kind"] == "SourceRun" for ref in data["output_refs"])


def test_cmd_ingest_emits_run_record_on_failure(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(cli, "session_context", _fake_session_context)

    def _fail_ingest(**_kwargs):
        raise RuntimeError("ingest boom")

    monkeypatch.setattr(cli, "ingest_external_main", _fail_ingest)

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
        cli.cmd_ingest_external(args, run_group_id="group-ingest-fail")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "sentinel.ingest@1.0.0"
    assert data["errors"]


def test_cmd_brief_emits_run_record_success(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(cli, "session_context", _fake_session_context)
    monkeypatch.setattr(cli, "generate_brief", lambda *_, **__: {"alerts": []})
    monkeypatch.setattr(cli, "render_markdown", lambda *_: "brief-md")

    args = argparse.Namespace(
        today=True,
        since="24h",
        format="md",
        limit=5,
        include_class0=False,
        strict=False,
    )
    cli.cmd_brief(args, run_group_id="group-brief")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "sentinel.brief@1.0.0"
    assert not data["errors"]
    assert any(ref["kind"] == "Brief" for ref in data["output_refs"])


def test_cmd_brief_emits_run_record_on_failure(monkeypatch, tmp_path):
    records_dir = _instrument_run_record(tmp_path, monkeypatch)
    _stub_config(monkeypatch, tmp_path)
    _stub_noops(monkeypatch)
    monkeypatch.setattr(cli, "session_context", _fake_session_context)

    def _fail_brief(*_args, **_kwargs):
        raise RuntimeError("brief boom")

    monkeypatch.setattr(cli, "generate_brief", _fail_brief)
    monkeypatch.setattr(cli, "render_markdown", lambda *_: "brief-md")

    args = argparse.Namespace(
        today=True,
        since="24h",
        format="md",
        limit=5,
        include_class0=False,
        strict=True,
    )
    with pytest.raises(RuntimeError):
        cli.cmd_brief(args, run_group_id="group-brief-fail")

    data = _load_validated_record(records_dir)
    assert data["operator_id"] == "sentinel.brief@1.0.0"
    assert data["errors"]
