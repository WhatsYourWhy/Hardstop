"""Helpers for computing deterministic artifact digests."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Sequence

from hardstop.database.run_raw_item_repo import list_run_raw_items
from hardstop.database.schema import RunRawItem, SourceRun
from hardstop.database.sqlite_client import session_context


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


def _load_run_raw_item_snapshots(sqlite_path: str, run_group_id: str) -> List[Dict[str, Any]]:
    """Load run_raw_items lineage rows, normalized to primitive dicts."""
    try:
        with session_context(sqlite_path) as session:
            rows: List[RunRawItem] = list_run_raw_items(session, run_group_id)
    except Exception:
        # Pre-v1.3 database, or the table is otherwise unreadable. Callers fall
        # back to the legacy counts digest.
        return []

    return [
        {
            "source_id": row.source_id,
            "content_hash": row.content_hash or "",
        }
        for row in rows
    ]


def compute_raw_item_batch_digest(sqlite_path: str, run_group_id: str) -> str:
    """
    Compute a digest for the raw-item batch associated with a run group.

    Hashes the per-item rows recorded in ``run_raw_items`` during fetch, so the
    digest tracks actual item content: changing one raw item's content_hash
    changes the batch digest.

    ``raw_id`` is deliberately excluded. It embeds a fetch date and a random
    suffix, so including it would make the digest unique per run even for
    byte-identical content. ``fetch_action`` is likewise excluded so that
    refetching identical content yields the same digest -- this identifies the
    batch, not what the run did to it. Both remain in the table for audit.

    Fallback: when the run group has no lineage rows -- pre-v1.3 databases, run
    groups written before this release, and ``hardstop sources test`` (which
    does not record lineage) -- the legacy FETCH SourceRun counts digest is
    returned unchanged. The fallback keys off row count rather than table
    existence, because every session runs ``create_all`` and would therefore
    materialize an empty ``run_raw_items`` on any database.
    """
    snapshots = _load_run_raw_item_snapshots(sqlite_path, run_group_id)
    if snapshots:
        snapshots.sort(key=lambda item: (item["source_id"], item["content_hash"]))
        return _digest_from_snapshots(
            snapshots, include_fields=("source_id", "content_hash")
        )

    legacy_snapshots = _load_source_run_snapshots(sqlite_path, run_group_id, phase="FETCH")
    include_fields = (
        "source_id",
        "status",
        "status_code",
        "items_fetched",
        "items_new",
        "diagnostics",
    )
    return _digest_from_snapshots(legacy_snapshots, include_fields=include_fields)


__all__ = ["compute_raw_item_batch_digest", "compute_source_runs_digest"]
