"""v1.3 pre-publication readiness evaluation."""

from contextlib import contextmanager

import pytest

from hardstop.ops.readiness import BROKEN, DEGRADED, READY, evaluate_readiness
from hardstop.ops.run_status import evaluate_run_status


@contextmanager
def _fake_session_context(*_args, **_kwargs):
    yield object()


def _evaluate(tmp_path, **overrides):
    """Evaluate readiness against a real (empty) sqlite file with stubs."""
    sqlite_path = overrides.pop("sqlite_path", None) or str(tmp_path / "hardstop.db")
    kwargs = {
        "load_sources_config": lambda: {"version": 1},
        "get_all_sources": lambda _cfg: [{"id": "source-1", "enabled": True}],
        "load_suppression_config": lambda: {"enabled": True, "rules": []},
        "get_all_source_health": lambda *_a, **_k: [],
        "session_context": _fake_session_context,
        "parse_since": lambda _value: 48,
    }
    kwargs.update(overrides)
    return evaluate_readiness(sqlite_path, **kwargs)


def _schema_ok(tmp_path):
    """Create a sqlite file carrying the four required tables."""
    import sqlite3

    sqlite_path = tmp_path / "ok.db"
    conn = sqlite3.connect(str(sqlite_path))
    for table in ("raw_items", "events", "alerts", "source_runs"):
        conn.execute(f"CREATE TABLE {table} (id TEXT);")
    conn.commit()
    conn.close()
    return str(sqlite_path)


def test_ready_when_everything_healthy(tmp_path):
    result = _evaluate(tmp_path, sqlite_path=_schema_ok(tmp_path))
    assert result.state == READY
    assert result.blockers == []
    assert result.is_publishable


def test_broken_on_health_budget_blockers(tmp_path):
    result = _evaluate(
        tmp_path,
        sqlite_path=_schema_ok(tmp_path),
        get_all_source_health=lambda *_a, **_k: [
            {"source_id": "src-bad", "health_budget_state": "BLOCKED"}
        ],
    )
    assert result.state == BROKEN
    assert not result.is_publishable
    assert "src-bad" in result.blockers[0]
    assert result.findings["health_budget_blockers"] == ["src-bad"]


def test_broken_on_missing_sources_config(tmp_path):
    def _missing():
        raise FileNotFoundError("config/sources.yaml")

    result = _evaluate(
        tmp_path, sqlite_path=_schema_ok(tmp_path), load_sources_config=_missing
    )
    assert result.state == BROKEN
    assert result.findings["config_error"] == "sources.yaml not found"


def test_broken_on_no_enabled_sources(tmp_path):
    result = _evaluate(
        tmp_path,
        sqlite_path=_schema_ok(tmp_path),
        get_all_sources=lambda _cfg: [{"id": "source-1", "enabled": False}],
    )
    assert result.state == BROKEN
    assert result.findings["enabled_sources_count"] == 0


def test_broken_on_schema_drift(tmp_path):
    """An empty database is missing every required table."""
    result = _evaluate(tmp_path)
    assert result.state == BROKEN
    assert "schema_drift" in result.findings


def test_degraded_on_watch_sources(tmp_path):
    result = _evaluate(
        tmp_path,
        sqlite_path=_schema_ok(tmp_path),
        get_all_source_health=lambda *_a, **_k: [
            {"source_id": "src-watch", "health_budget_state": "WATCH"}
        ],
    )
    assert result.state == DEGRADED
    assert result.is_publishable  # DEGRADED still publishes, it is not a blocker
    assert "src-watch" in result.warnings[0]


def test_degraded_on_suppression_warnings(tmp_path):
    result = _evaluate(
        tmp_path,
        sqlite_path=_schema_ok(tmp_path),
        load_suppression_config=lambda: {"enabled": False, "rules": []},
    )
    assert result.state == DEGRADED
    assert "Suppression disabled" in result.warnings


@pytest.mark.parametrize(
    "findings",
    [
        {"config_error": "sources.yaml not found"},
        {"schema_drift": ["table: alerts"]},
        {"enabled_sources_count": 0},
        {"health_budget_blockers": ["src-bad"]},
    ],
)
def test_readiness_broken_matches_run_status_broken(findings):
    """
    Parity guard.

    readiness duplicates the doctor-driven BROKEN conditions from run_status so
    it can gate publication before run_status runs. If the two ever diverge, a
    run could publish an authoritative brief and then exit 2 -- exactly the
    failure this work removes.
    """
    from hardstop.ops.readiness import _classify

    readiness_state = _classify(dict(findings)).state

    exit_code, _messages = evaluate_run_status(
        fetch_results=[type("R", (), {"status": "SUCCESS", "source_id": "s"})()],
        ingest_runs=[type("I", (), {"status": "SUCCESS", "source_id": "s", "diagnostics_json": None})()],
        doctor_findings=dict(findings),
        stale_sources=[],
        stale_threshold_hours=48,
        strict=False,
    )

    assert (readiness_state == BROKEN) == (exit_code == 2), (
        f"readiness={readiness_state} but run_status exit={exit_code} for {findings}"
    )
