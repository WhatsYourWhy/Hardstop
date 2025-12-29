"""Unit tests for run status evaluation (v1.0)."""

import json
import pytest
from datetime import datetime, timezone

from sentinel.database.schema import SourceRun
from sentinel.ops.run_status import evaluate_run_status
from sentinel.retrieval.fetcher import FetchResult, RawItemCandidate


def test_broken_config_error():
    """Test that config parse error results in exit code 2."""
    exit_code, messages = evaluate_run_status(
        fetch_results=None,
        ingest_runs=None,
        doctor_findings={"config_error": "sources.yaml parse error"},
        stale_sources=None,
    )
    assert exit_code == 2
    assert any("config error" in msg.lower() for msg in messages)


def test_broken_schema_drift():
    """Test that schema drift results in exit code 2."""
    exit_code, messages = evaluate_run_status(
        fetch_results=None,
        ingest_runs=None,
        doctor_findings={"schema_drift": ["table: source_runs", "alerts.classification"]},
        stale_sources=None,
    )
    assert exit_code == 2
    assert any("schema drift" in msg.lower() for msg in messages)


def test_broken_zero_sources():
    """Test that zero enabled sources results in exit code 2."""
    exit_code, messages = evaluate_run_status(
        fetch_results=None,
        ingest_runs=None,
        doctor_findings={"enabled_sources_count": 0},
        stale_sources=None,
    )
    assert exit_code == 2
    assert any("no enabled" in msg.lower() or "zero" in msg.lower() for msg in messages)


def test_fetch_result_items_default_is_independent():
    """Ensure each FetchResult gets its own empty items list."""
    result1 = FetchResult(
        source_id="source1",
        fetched_at_utc=datetime.now(timezone.utc).isoformat(),
        status="SUCCESS",
    )
    result2 = FetchResult(
        source_id="source2",
        fetched_at_utc=datetime.now(timezone.utc).isoformat(),
        status="SUCCESS",
    )

    result1.items.append(
        RawItemCandidate(canonical_id="id1", title="Item 1", payload={"id": "id1"})
    )

    assert result2.items == []


def test_broken_all_sources_failed():
    """Test that all sources failing fetch results in exit code 2."""
    fetch_results = [
        FetchResult(
            source_id="source1",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="FAILURE",
            status_code=404,
            error="Not Found",
            items=[],
        ),
        FetchResult(
            source_id="source2",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="FAILURE",
            status_code=500,
            error="Server Error",
            items=[],
        ),
    ]
    exit_code, messages = evaluate_run_status(
        fetch_results=fetch_results,
        ingest_runs=None,
        doctor_findings={"enabled_sources_count": 2},
        stale_sources=None,
    )
    assert exit_code == 2
    assert any("all" in msg.lower() and "failed" in msg.lower() for msg in messages)


def test_broken_ingest_crashed():
    """Test that ingest crash before processing any source results in exit code 2."""
    fetch_results = [
        FetchResult(
            source_id="source1",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            status_code=200,
            items=[RawItemCandidate(canonical_id="id1", title="Test", payload={})],
        ),
    ]
    # No ingest runs despite successful fetch with items
    exit_code, messages = evaluate_run_status(
        fetch_results=fetch_results,
        ingest_runs=[],
        doctor_findings={"enabled_sources_count": 1},
        stale_sources=None,
    )
    assert exit_code == 2
    assert any("ingest crashed" in msg.lower() for msg in messages)


def test_warning_some_sources_failed():
    """Test that some sources failing results in exit code 1."""
    fetch_results = [
        FetchResult(
            source_id="source1",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            status_code=200,
            items=[RawItemCandidate(canonical_id="id1", title="Test", payload={})],
        ),
        FetchResult(
            source_id="source2",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="FAILURE",
            status_code=404,
            error="Not Found",
            items=[],
        ),
    ]
    exit_code, messages = evaluate_run_status(
        fetch_results=fetch_results,
        ingest_runs=None,
        doctor_findings={"enabled_sources_count": 2},
        stale_sources=None,
    )
    assert exit_code == 1
    assert any("failed" in msg.lower() for msg in messages)


def test_warning_stale_sources():
    """Test that stale sources result in exit code 1."""
    fetch_results = [
        FetchResult(
            source_id="source1",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            status_code=200,
            items=[RawItemCandidate(canonical_id="id1", title="Test", payload={})],
        ),
    ]
    exit_code, messages = evaluate_run_status(
        fetch_results=fetch_results,
        ingest_runs=None,
        doctor_findings={"enabled_sources_count": 2},
        stale_sources=["source2"],
    )
    assert exit_code == 1
    assert any("stale" in msg.lower() for msg in messages)


def test_warning_ingest_failure():
    """Test that ingest failure for one or more sources results in exit code 1."""
    ingest_runs = [
        SourceRun(
            run_id="run1",
            run_group_id="group1",
            source_id="source1",
            phase="INGEST",
            run_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            items_processed=10,
            items_events_created=10,
            items_alerts_touched=5,
        ),
        SourceRun(
            run_id="run2",
            run_group_id="group1",
            source_id="source2",
            phase="INGEST",
            run_at_utc=datetime.now(timezone.utc).isoformat(),
            status="FAILURE",
            error="Normalization error",
            items_processed=5,
            items_events_created=0,
            items_alerts_touched=0,
        ),
    ]
    exit_code, messages = evaluate_run_status(
        fetch_results=None,
        ingest_runs=ingest_runs,
        doctor_findings={"enabled_sources_count": 2},
        stale_sources=None,
    )
    assert exit_code == 1
    assert any("failed" in msg.lower() and "ingest" in msg.lower() for msg in messages)


def test_warning_ingest_errors_from_diagnostics():
    """Diagnostics with ingest errors should surface as warnings."""
    ingest_runs = [
        SourceRun(
            run_id="run1",
            run_group_id="group1",
            source_id="source1",
            phase="INGEST",
            run_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            items_processed=3,
            items_events_created=2,
            items_alerts_touched=1,
            diagnostics_json=json.dumps({"errors": 2}),
        ),
    ]
    exit_code, messages = evaluate_run_status(
        fetch_results=None,
        ingest_runs=ingest_runs,
        doctor_findings={"enabled_sources_count": 1},
        stale_sources=None,
    )
    assert exit_code == 1
    assert any("ingest errors" in msg.lower() for msg in messages)


def test_healthy_all_good():
    """Test that healthy conditions result in exit code 0."""
    fetch_results = [
        FetchResult(
            source_id="source1",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            status_code=200,
            items=[RawItemCandidate(canonical_id="id1", title="Test", payload={})],
        ),
    ]
    ingest_runs = [
        SourceRun(
            run_id="run1",
            run_group_id="group1",
            source_id="source1",
            phase="INGEST",
            run_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            items_processed=1,
            items_events_created=1,
            items_alerts_touched=1,
        ),
    ]
    exit_code, messages = evaluate_run_status(
        fetch_results=fetch_results,
        ingest_runs=ingest_runs,
        doctor_findings={"enabled_sources_count": 1},
        stale_sources=None,
    )
    assert exit_code == 0
    assert any("healthy" in msg.lower() or "all systems" in msg.lower() for msg in messages)


def test_healthy_quiet_success():
    """Test that quiet success (0 items) still results in exit code 0."""
    fetch_results = [
        FetchResult(
            source_id="source1",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            status_code=200,
            items=[],  # Quiet success - no items but successful fetch
        ),
    ]
    exit_code, messages = evaluate_run_status(
        fetch_results=fetch_results,
        ingest_runs=None,
        doctor_findings={"enabled_sources_count": 1},
        stale_sources=None,
    )
    assert exit_code == 0


def test_strict_mode_warnings_become_broken():
    """Test that strict mode treats warnings as broken (exit code 2)."""
    fetch_results = [
        FetchResult(
            source_id="source1",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            status_code=200,
            items=[RawItemCandidate(canonical_id="id1", title="Test", payload={})],
        ),
        FetchResult(
            source_id="source2",
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            status="FAILURE",
            status_code=404,
            error="Not Found",
            items=[],
        ),
    ]
    exit_code, messages = evaluate_run_status(
        fetch_results=fetch_results,
        ingest_runs=None,
        doctor_findings={"enabled_sources_count": 2},
        stale_sources=None,
        strict=True,
    )
    assert exit_code == 2  # Warnings become broken in strict mode
    assert any("failed" in msg.lower() for msg in messages)


def test_strict_mode_treats_ingest_errors_as_broken():
    """In strict mode, ingest error warnings become broken."""
    ingest_runs = [
        SourceRun(
            run_id="run1",
            run_group_id="group1",
            source_id="source1",
            phase="INGEST",
            run_at_utc=datetime.now(timezone.utc).isoformat(),
            status="SUCCESS",
            items_processed=3,
            items_events_created=2,
            items_alerts_touched=1,
            diagnostics_json=json.dumps({"errors": 1}),
        ),
    ]
    exit_code, messages = evaluate_run_status(
        fetch_results=None,
        ingest_runs=ingest_runs,
        doctor_findings={"enabled_sources_count": 1},
        stale_sources=None,
        strict=True,
    )
    assert exit_code == 2
    assert any("ingest errors" in msg.lower() for msg in messages)


def test_failure_budget_blocker_breaks_run():
    """Health budget blockers should immediately break the run."""
    exit_code, messages = evaluate_run_status(
        fetch_results=None,
        ingest_runs=None,
        doctor_findings={
            "enabled_sources_count": 1,
            "health_budget_blockers": ["source1"],
        },
        stale_sources=None,
    )
    assert exit_code == 2
    assert any("failure budget" in msg.lower() for msg in messages)


def test_failure_budget_warning_sets_warning():
    """Health budget warnings surface as warnings."""
    exit_code, messages = evaluate_run_status(
        fetch_results=None,
        ingest_runs=None,
        doctor_findings={
            "enabled_sources_count": 1,
            "health_budget_warnings": ["source1"],
        },
        stale_sources=None,
    )
    assert exit_code == 1
    assert any("failure budget" in msg.lower() or "budget" in msg.lower() for msg in messages)
