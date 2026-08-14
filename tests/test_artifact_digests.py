import json
import uuid
from pathlib import Path

from hardstop.database.run_raw_item_repo import record_run_raw_item
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


def _insert_run_raw_item(
    sqlite_path: Path,
    *,
    run_group_id: str,
    raw_id: str,
    source_id: str = "source-1",
    content_hash: str | None = "content-1",
    fetch_action: str = "NEW",
) -> None:
    with session_context(str(sqlite_path)) as session:
        record_run_raw_item(
            session,
            run_group_id=run_group_id,
            raw_id=raw_id,
            source_id=source_id,
            content_hash=content_hash,
            fetch_action=fetch_action,
            recorded_at_utc="2025-01-01T00:00:00Z",
        )
        session.commit()


def test_raw_item_batch_digest_uses_lineage_when_present(tmp_path):
    """Lineage rows take precedence over the legacy counts digest."""
    sqlite_path = tmp_path / "hardstop.db"
    run_group = "rg-lineage"
    _insert_source_run(
        sqlite_path,
        run_group_id=run_group,
        source_id="source-1",
        phase="FETCH",
        items_fetched=1,
        items_new=1,
        diagnostics={"items_seen": 1},
    )
    legacy_digest = compute_raw_item_batch_digest(str(sqlite_path), run_group)

    _insert_run_raw_item(sqlite_path, run_group_id=run_group, raw_id="RAW-1")
    lineage_digest = compute_raw_item_batch_digest(str(sqlite_path), run_group)

    assert lineage_digest != legacy_digest


def test_raw_item_batch_digest_falls_back_without_lineage_rows(tmp_path):
    """
    A run group with no lineage rows keeps the pre-v1.3 counts digest.

    Both databases hold the same FETCH SourceRun; only one also holds lineage
    for an unrelated run group. Equal digests prove the fallback is keyed off
    this run group's row count, and that another run group's lineage cannot
    leak into it.
    """
    bare_path = tmp_path / "bare.db"
    with_other_path = tmp_path / "with_other.db"
    for sqlite_path in (bare_path, with_other_path):
        _insert_source_run(
            sqlite_path,
            run_group_id="rg-legacy",
            source_id="source-1",
            phase="FETCH",
            items_fetched=5,
            items_new=4,
            diagnostics={"items_seen": 5},
        )
    _insert_run_raw_item(with_other_path, run_group_id="rg-other", raw_id="RAW-9")

    assert compute_raw_item_batch_digest(str(bare_path), "rg-legacy") == (
        compute_raw_item_batch_digest(str(with_other_path), "rg-legacy")
    )


def test_raw_item_batch_digest_changes_when_content_hash_changes(tmp_path):
    """The acceptance property: mutating one item's content moves the digest."""
    sqlite_path_a = tmp_path / "a.db"
    sqlite_path_b = tmp_path / "b.db"
    _insert_run_raw_item(
        sqlite_path_a, run_group_id="rg", raw_id="RAW-1", content_hash="aaa"
    )
    _insert_run_raw_item(
        sqlite_path_b, run_group_id="rg", raw_id="RAW-1", content_hash="bbb"
    )
    assert compute_raw_item_batch_digest(str(sqlite_path_a), "rg") != (
        compute_raw_item_batch_digest(str(sqlite_path_b), "rg")
    )


def test_raw_item_batch_digest_ignores_raw_id_and_fetch_action(tmp_path):
    """Identical content refetched under a new raw_id/action digests the same."""
    sqlite_path_a = tmp_path / "a.db"
    sqlite_path_b = tmp_path / "b.db"
    _insert_run_raw_item(
        sqlite_path_a,
        run_group_id="rg",
        raw_id="RAW-20250101-aaaa",
        content_hash="same",
        fetch_action="NEW",
    )
    _insert_run_raw_item(
        sqlite_path_b,
        run_group_id="rg",
        raw_id="RAW-20260202-zzzz",
        content_hash="same",
        fetch_action="DUPLICATE",
    )
    assert compute_raw_item_batch_digest(str(sqlite_path_a), "rg") == (
        compute_raw_item_batch_digest(str(sqlite_path_b), "rg")
    )
