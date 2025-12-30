import json
import uuid
from pathlib import Path

from hardstop.database.schema import SourceRun
from hardstop.database.sqlite_client import session_context
from hardstop.ops.artifacts import (
    compute_raw_item_batch_digest,
    compute_source_runs_digest,
)


def _insert_source_run(
    sqlite_path: Path,
    *,
    run_group_id: str,
    source_id: str,
    phase: str,
    status: str = "SUCCESS",
    status_code: int | None = 200,
    items_fetched: int = 0,
    items_new: int = 0,
    items_processed: int = 0,
    items_suppressed: int = 0,
    items_events_created: int = 0,
    items_alerts_touched: int = 0,
    diagnostics: dict | None = None,
    error: str | None = None,
) -> None:
    diagnostics_json = json.dumps(diagnostics) if diagnostics is not None else None
    with session_context(str(sqlite_path)) as session:
        row = SourceRun(
            run_id=str(uuid.uuid4()),
            run_group_id=run_group_id,
            source_id=source_id,
            phase=phase,
            run_at_utc="2025-01-01T00:00:00Z",
            status=status,
            status_code=status_code,
            error=error,
            duration_seconds=1.0,
            items_fetched=items_fetched,
            items_new=items_new,
            items_processed=items_processed,
            items_suppressed=items_suppressed,
            items_events_created=items_events_created,
            items_alerts_touched=items_alerts_touched,
            diagnostics_json=diagnostics_json,
        )
        session.add(row)
        session.commit()


def test_source_runs_digest_ignores_run_group(tmp_path):
    sqlite_path = tmp_path / "hardstop.db"
    for run_group in ("rg-a", "rg-b"):
        _insert_source_run(
            sqlite_path,
            run_group_id=run_group,
            source_id="source-1",
            phase="FETCH",
            status="SUCCESS",
            items_fetched=3,
            items_new=2,
            diagnostics={"items_seen": 3},
        )
    digest_a = compute_source_runs_digest(str(sqlite_path), "rg-a", "FETCH")
    digest_b = compute_source_runs_digest(str(sqlite_path), "rg-b", "FETCH")
    assert digest_a == digest_b


def test_raw_item_batch_digest_tracks_fetch_counts(tmp_path):
    sqlite_path = tmp_path / "hardstop.db"
    run_group = "rg-raw"
    _insert_source_run(
        sqlite_path,
        run_group_id=run_group,
        source_id="source-1",
        phase="FETCH",
        status="SUCCESS",
        items_fetched=5,
        items_new=4,
        diagnostics={"items_seen": 5},
    )
    first = compute_raw_item_batch_digest(str(sqlite_path), run_group)
    _insert_source_run(
        sqlite_path,
        run_group_id=run_group,
        source_id="source-2",
        phase="FETCH",
        status="SUCCESS",
        items_fetched=2,
        items_new=1,
        diagnostics={"items_seen": 2},
    )
    second = compute_raw_item_batch_digest(str(sqlite_path), run_group)
    assert first != second
