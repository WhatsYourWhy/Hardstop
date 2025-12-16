"""Minimal SQLite migration helpers for additive schema changes."""

import sqlite3
from typing import List, Tuple


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cur = conn.execute(f"PRAGMA table_info({table});")
    cols = [row[1] for row in cur.fetchall()]
    return column in cols


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
    
    Args:
        sqlite_path: Path to SQLite database file
    """
    conn = sqlite3.connect(sqlite_path)
    try:
        additions: List[Tuple[str, str]] = [
            ("correlation_key", "TEXT"),
            ("correlation_action", "TEXT"),  # v0.5: "CREATED" or "UPDATED"
            ("first_seen_utc", "TEXT"),  # SQLite stores datetime as TEXT
            ("last_seen_utc", "TEXT"),
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

