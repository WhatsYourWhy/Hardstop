"""Helpers for computing deterministic artifact digests."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Sequence

from sentinel.database.schema import SourceRun
from sentinel.database.sqlite_client import session_context


def _canonical_dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_source_run_snapshots(sqlite_path: str, run_group_id: str, phase: str) -> List[Dict[str, Any]]:
    """Load SourceRun rows for a run_group_id/phase pair, normalized to primitive dicts."""
    with session_context(sqlite_path) as session:
        rows: List[SourceRun] = (
            session.query(SourceRun)
            .filter(SourceRun.run_group_id == run_group_id, SourceRun.phase == phase)
            .order_by(SourceRun.source_id.asc())
            .all()
        )

    snapshots: List[Dict[str, Any]] = []
    for row in rows:
        diagnostics: Dict[str, Any] = {}
        if row.diagnostics_json:
            try:
                diagnostics = json.loads(row.diagnostics_json)
            except (json.JSONDecodeError, TypeError):
                diagnostics = {}
        snapshots.append(
            {
                "source_id": row.source_id,
                "status": row.status,
                "status_code": row.status_code,
                "error": row.error or "",
                "items_fetched": row.items_fetched,
                "items_new": row.items_new,
                "items_processed": row.items_processed,
                "items_suppressed": row.items_suppressed,
                "items_events_created": row.items_events_created,
                "items_alerts_touched": row.items_alerts_touched,
                "diagnostics": diagnostics,
            }
        )
    return snapshots


def _digest_from_snapshots(
    snapshots: Sequence[Dict[str, Any]],
    *,
    include_fields: Iterable[str],
) -> str:
    normalized: List[Dict[str, Any]] = []
    include = tuple(include_fields)
    for snapshot in snapshots:
        normalized.append({field: snapshot[field] for field in include})
    payload = _canonical_dumps(normalized).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_source_runs_digest(sqlite_path: str, run_group_id: str, phase: str) -> str:
    """
    Compute a deterministic digest for SourceRun artifacts.

    The digest intentionally ignores nondeterministic fields (timestamps, run IDs)
    and instead summarizes per-source status, counts, and diagnostics.
    """
    snapshots = _load_source_run_snapshots(sqlite_path, run_group_id, phase)
    include_fields = (
        "source_id",
        "status",
        "status_code",
        "error",
        "items_fetched",
        "items_new",
        "items_processed",
        "items_suppressed",
        "items_events_created",
        "items_alerts_touched",
        "diagnostics",
    )
    return _digest_from_snapshots(snapshots, include_fields=include_fields)


def compute_raw_item_batch_digest(sqlite_path: str, run_group_id: str) -> str:
    """
    Compute a digest for the logical raw-item batch associated with a run group.

    We approximate the batch content by hashing the FETCH SourceRun metrics
    (source IDs, item counts, and diagnostics) which are recorded during fetch.
    """
    snapshots = _load_source_run_snapshots(sqlite_path, run_group_id, phase="FETCH")
    include_fields = (
        "source_id",
        "status",
        "status_code",
        "items_fetched",
        "items_new",
        "diagnostics",
    )
    return _digest_from_snapshots(snapshots, include_fields=include_fields)


__all__ = ["compute_raw_item_batch_digest", "compute_source_runs_digest"]
