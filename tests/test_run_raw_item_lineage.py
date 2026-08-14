"""v1.3 lineage: save_raw_item_with_action, run_raw_items, and the migration."""

import sqlite3

import pytest

from hardstop.database.migrate import ensure_run_raw_items_table
from hardstop.database.raw_item_repo import (
    save_raw_item,
    save_raw_item_with_action,
)
from hardstop.database.run_raw_item_repo import list_run_raw_items, record_run_raw_item
from hardstop.database.schema import RawItem
from hardstop.database.sqlite_client import session_context


def _candidate(title="Port closure", url="https://example.test/a"):
    return {
        "title": title,
        "url": url,
        "published_at_utc": "2025-01-01T00:00:00Z",
        "payload": {"title": title},
    }


# --- save_raw_item_with_action -------------------------------------------------


def test_save_raw_item_with_action_reports_new(session):
    _row, action = save_raw_item_with_action(
        session, source_id="src-1", tier="global", candidate=_candidate()
    )
    assert action == "NEW"


def test_save_raw_item_with_action_reports_duplicate(session):
    candidate = _candidate()
    save_raw_item_with_action(session, source_id="src-1", tier="global", candidate=candidate)
    session.commit()

    _row, action = save_raw_item_with_action(
        session, source_id="src-1", tier="global", candidate=candidate
    )
    assert action == "DUPLICATE"


def test_save_raw_item_with_action_reports_retry(session):
    candidate = _candidate()
    row, _ = save_raw_item_with_action(
        session, source_id="src-1", tier="global", candidate=candidate
    )
    session.commit()

    row.status = "FAILED"
    session.commit()

    refreshed, action = save_raw_item_with_action(
        session, source_id="src-1", tier="global", candidate=candidate
    )
    assert action == "RETRY"
    assert refreshed.status == "NEW"


def test_save_raw_item_still_returns_row_only(session):
    """The pre-v1.3 wrapper contract is preserved for existing callers."""
    row = save_raw_item(session, source_id="src-1", tier="global", candidate=_candidate())
    assert isinstance(row, RawItem)
    assert row.raw_id


# --- run_raw_item_repo ---------------------------------------------------------


def test_list_run_raw_items_is_scoped_and_ordered(session):
    for source_id, raw_id in (("src-b", "RAW-2"), ("src-a", "RAW-1"), ("src-a", "RAW-0")):
        record_run_raw_item(
            session,
            run_group_id="rg-1",
            raw_id=raw_id,
            source_id=source_id,
            content_hash="h",
            fetch_action="NEW",
        )
    record_run_raw_item(
        session,
        run_group_id="rg-2",
        raw_id="RAW-OTHER",
        source_id="src-a",
        content_hash="h",
        fetch_action="NEW",
    )
    session.commit()

    rows = list_run_raw_items(session, "rg-1")
    assert [(r.source_id, r.raw_id) for r in rows] == [
        ("src-a", "RAW-0"),
        ("src-a", "RAW-1"),
        ("src-b", "RAW-2"),
    ]


def test_run_raw_items_primary_key_rejects_duplicate_in_run_group(session):
    """Composite PK is what makes the caller-side dedupe set load-bearing."""
    for _ in range(2):
        record_run_raw_item(
            session,
            run_group_id="rg-1",
            raw_id="RAW-1",
            source_id="src-a",
            content_hash="h",
            fetch_action="NEW",
        )
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


# --- migration -----------------------------------------------------------------


def _table_names(sqlite_path):
    conn = sqlite3.connect(str(sqlite_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def test_ensure_run_raw_items_table_creates_on_legacy_db(tmp_path):
    sqlite_path = tmp_path / "legacy.db"
    # A pre-v1.3 database: some other table exists, run_raw_items does not.
    conn = sqlite3.connect(str(sqlite_path))
    conn.execute("CREATE TABLE alerts (alert_id TEXT PRIMARY KEY);")
    conn.commit()
    conn.close()

    assert "run_raw_items" not in _table_names(sqlite_path)
    ensure_run_raw_items_table(str(sqlite_path))
    assert "run_raw_items" in _table_names(sqlite_path)


def test_ensure_run_raw_items_table_is_idempotent(tmp_path):
    sqlite_path = tmp_path / "legacy.db"
    ensure_run_raw_items_table(str(sqlite_path))
    ensure_run_raw_items_table(str(sqlite_path))
    assert "run_raw_items" in _table_names(sqlite_path)


def test_ensure_run_raw_items_table_adds_missing_column(tmp_path):
    """An install created before recorded_at_utc existed gets the column added."""
    sqlite_path = tmp_path / "partial.db"
    conn = sqlite3.connect(str(sqlite_path))
    conn.execute("""
        CREATE TABLE run_raw_items (
            run_group_id TEXT NOT NULL,
            raw_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            content_hash TEXT,
            fetch_action TEXT NOT NULL,
            PRIMARY KEY (run_group_id, raw_id)
        );
    """)
    conn.commit()
    conn.close()

    ensure_run_raw_items_table(str(sqlite_path))

    conn = sqlite3.connect(str(sqlite_path))
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(run_raw_items);")}
    finally:
        conn.close()
    assert "recorded_at_utc" in columns


def test_cmd_fetch_records_lineage_end_to_end(tmp_path):
    """Lineage written during fetch drives the RawItemBatch digest."""
    from hardstop.ops.artifacts import compute_raw_item_batch_digest

    sqlite_path = tmp_path / "hardstop.db"
    with session_context(str(sqlite_path)) as session:
        row, action = save_raw_item_with_action(
            session, source_id="src-1", tier="global", candidate=_candidate()
        )
        record_run_raw_item(
            session,
            run_group_id="rg-1",
            raw_id=row.raw_id,
            source_id="src-1",
            content_hash=row.content_hash,
            fetch_action=action,
        )
        session.commit()

    before = compute_raw_item_batch_digest(str(sqlite_path), "rg-1")

    # Mutating the recorded content hash must move the digest -- the property
    # the pre-v1.3 counts-based digest could not provide.
    with session_context(str(sqlite_path)) as session:
        lineage = list_run_raw_items(session, "rg-1")[0]
        lineage.content_hash = "tampered"
        session.commit()

    assert compute_raw_item_batch_digest(str(sqlite_path), "rg-1") != before
