"""Minimal SQLite migration helpers for additive schema changes."""

import sqlite3
from typing import List, Tuple


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cur = conn.execute(f"PRAGMA table_info({table});")
    cols = [row[1] for row in cur.fetchall()]
    return column in cols


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
        (table,)
    )
    return cur.fetchone() is not None


def ensure_alert_correlation_columns(sqlite_path: str) -> None:
    """
    Minimal additive migration: adds new columns if missing.
    Safe for local-first SQLite.
    
    Adds correlation fields for v0.4:
    - correlation_key
    - first_seen_utc
    - last_seen_utc
    - update_count
    - root_event_ids_json
    
    Also ensures classification column exists (v0.3+).
    
    Args:
        sqlite_path: Path to SQLite database file
    """
    conn = sqlite3.connect(sqlite_path)
    try:
        additions: List[Tuple[str, str]] = [
            ("classification", "INTEGER"),  # v0.3: Classification field (0=Interesting, 1=Relevant, 2=Impactful)
            ("correlation_key", "TEXT"),
            ("correlation_action", "TEXT"),  # v0.5: "CREATED" or "UPDATED"
            ("first_seen_utc", "TEXT"),  # ISO 8601 string for consistent storage
            ("last_seen_utc", "TEXT"),  # ISO 8601 string for consistent storage
            ("update_count", "INTEGER"),
            ("root_event_ids_json", "TEXT"),
            ("impact_score", "INTEGER"),  # v0.5: Network impact score
            ("scope_json", "TEXT"),  # v0.5: Scope as JSON
        ]
        for col, coltype in additions:
            if not _column_exists(conn, "alerts", col):
                conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} {coltype};")
        conn.commit()
    finally:
        conn.close()


def ensure_raw_items_table(sqlite_path: str) -> None:
    """
    Create raw_items table if it doesn't exist (v0.6).
    
    Args:
        sqlite_path: Path to SQLite database file
    """
    conn = sqlite3.connect(sqlite_path)
    try:
        if not _table_exists(conn, "raw_items"):
            conn.execute("""
                CREATE TABLE raw_items (
                    raw_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    fetched_at_utc TEXT NOT NULL,
                    published_at_utc TEXT,
                    canonical_id TEXT,
                    url TEXT,
                    title TEXT,
                    raw_payload_json TEXT NOT NULL,
                    content_hash TEXT,
                    status TEXT NOT NULL DEFAULT 'NEW',
                    error TEXT
                );
            """)
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_items_source_id ON raw_items(source_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_items_canonical_id ON raw_items(canonical_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_items_content_hash ON raw_items(content_hash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_items_status ON raw_items(status);")
            conn.commit()
    finally:
        conn.close()


def ensure_event_external_fields(sqlite_path: str) -> None:
    """
    Add external source fields to events table if missing (v0.6).
    
    Adds:
    - source_id
    - raw_id
    - event_time_utc
    - location_hint
    - entities_json
    - event_payload_json
    
    Args:
        sqlite_path: Path to SQLite database file
    """
    conn = sqlite3.connect(sqlite_path)
    try:
        additions: List[Tuple[str, str]] = [
            ("source_id", "TEXT"),
            ("raw_id", "TEXT"),
            ("event_time_utc", "TEXT"),
            ("location_hint", "TEXT"),
            ("entities_json", "TEXT"),
            ("event_payload_json", "TEXT"),
        ]
        for col, coltype in additions:
            if not _column_exists(conn, "events", col):
                conn.execute(f"ALTER TABLE events ADD COLUMN {col} {coltype};")
        # Create indexes for new fields
        if not _column_exists(conn, "events", "source_id"):
            # Index will be created by ALTER TABLE above, but we check to avoid errors
            pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_source_id ON events(source_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_raw_id ON events(raw_id);")
        conn.commit()
    finally:
        conn.close()

