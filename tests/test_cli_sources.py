"""CLI behavior tests."""

from contextlib import contextmanager
from types import SimpleNamespace

import argparse

from hardstop.cli import sources as sources_mod


def test_sources_test_skips_ingest_when_flag_false(monkeypatch, tmp_path):
    """Ensure cmd_sources_test does not ingest unless explicitly requested."""

    ingest_called = {"value": False}

    def fake_ingest(_args, _run_group_id=None):
        ingest_called["value"] = True

    monkeypatch.setattr("hardstop.cli.pipeline.cmd_ingest_external", fake_ingest)
    monkeypatch.setattr(sources_mod, "load_config", lambda: {"storage": {"sqlite_path": str(tmp_path / "db.sqlite")}})
    monkeypatch.setattr(sources_mod, "ensure_raw_items_table", lambda *_: None)
    monkeypatch.setattr(sources_mod, "ensure_event_external_fields", lambda *_: None)
    monkeypatch.setattr(sources_mod, "ensure_alert_correlation_columns", lambda *_: None)
    monkeypatch.setattr(sources_mod, "ensure_trust_tier_columns", lambda *_: None)
    monkeypatch.setattr(sources_mod, "ensure_source_runs_table", lambda *_: None)
    monkeypatch.setattr(sources_mod, "load_sources_config", lambda: {})
    monkeypatch.setattr(sources_mod, "get_all_sources", lambda _cfg: [{"id": "source-1", "tier": "regional", "trust_tier": 2}])
    monkeypatch.setattr(sources_mod, "_resolve_source_defaults", lambda cfg, _sc: cfg)
    monkeypatch.setattr(sources_mod, "create_source_run", lambda *_args, **_kwargs: None)

    @contextmanager
    def fake_session_context(_sqlite_path):
        session = SimpleNamespace(new=set(), commit=lambda: None)
        yield session

    monkeypatch.setattr(sources_mod, "session_context", fake_session_context)

    def fake_save_raw_item(session, **_kwargs):
        obj = SimpleNamespace(status="NEW")
        session.new.add(obj)
        return obj

    monkeypatch.setattr(sources_mod, "save_raw_item", fake_save_raw_item)

    class FakeFetcher:
        def fetch_one(self, source_id, since, max_items):
            item = SimpleNamespace(title="Example item")
            return SimpleNamespace(
                status="SUCCESS",
                status_code=None,
                duration_seconds=0.1,
                items=[item],
                fetched_at_utc="2024-01-01T00:00:00Z",
                error=None,
            )

    monkeypatch.setattr(sources_mod, "SourceFetcher", lambda: FakeFetcher())

    args = argparse.Namespace(
        source_id="source-1",
        since=None,
        max_items=None,
        ingest=False,
        fail_fast=False,
    )

    sources_mod.cmd_sources_test(args)

    assert ingest_called["value"] is False
