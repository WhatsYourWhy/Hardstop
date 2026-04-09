"""Shared helpers for CLI commands."""

import hashlib
import json
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from hardstop.config.loader import get_source_with_defaults
from hardstop.ops.artifacts import compute_raw_item_batch_digest, compute_source_runs_digest
from hardstop.ops.run_record import ArtifactRef
from hardstop.utils.logging import get_logger

logger = get_logger(__name__)


def _resolve_source_defaults(source_config_raw, sources_config):
    """
    Resolve source config defaults while remaining tolerant to patched helpers
    that only accept a single positional argument (e.g., during tests).
    """
    if not source_config_raw:
        return {}
    try:
        return get_source_with_defaults(source_config_raw, sources_config)
    except TypeError:
        return get_source_with_defaults(source_config_raw)


def _hash_parts(*parts: str) -> str:
    """Stable SHA-256 hash for artifact refs."""
    payload = "||".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _derive_seed(label: str) -> int:
    """Derive a deterministic seed from a stable label (e.g., run_group_id)."""
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _run_group_ref(run_group_id: str) -> ArtifactRef:
    return ArtifactRef(
        id=f"run-group:{run_group_id}",
        hash=_hash_parts(run_group_id),
        kind="RunGroup",
    )


def _log_run_record_failure(context: str, error: Exception) -> None:
    logger.warning("Failed to emit %s run record: %s", context, error)
    print(f"[hardstop] RunRecord emission failure ({context}): {error}", file=sys.stderr)


def _safe_raw_batch_hash(sqlite_path: str, run_group_id: str, fallback_parts: Iterable[str]) -> str:
    try:
        return compute_raw_item_batch_digest(sqlite_path, run_group_id)
    except Exception as exc:
        logger.debug("Falling back to legacy raw batch hash: %s", exc, exc_info=True)
        return _hash_parts(*fallback_parts)


def _safe_source_runs_hash(
    sqlite_path: str,
    run_group_id: str,
    *,
    phase: str,
    fallback_parts: Iterable[str],
) -> str:
    try:
        return compute_source_runs_digest(sqlite_path, run_group_id, phase)
    except Exception as exc:
        logger.debug("Falling back to legacy source-runs hash: %s", exc, exc_info=True)
        return _hash_parts(*fallback_parts)


def _load_run_records(run_records_dir: Path) -> List[dict]:
    records: List[dict] = []
    if not run_records_dir.exists():
        return records
    for path in sorted(run_records_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_path"] = str(path)
            records.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return records


def _find_incident_artifacts(
    incident_id: str,
    *,
    artifacts_dir: Path,
    correlation_key: Optional[str] = None,
) -> List[tuple[str, Path, dict]]:
    matches: List[tuple[str, Path, dict]] = []
    if not artifacts_dir.exists():
        return matches
    for path in artifacts_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        inputs = payload.get("inputs") or {}
        if inputs.get("alert_id") != incident_id:
            continue
        if correlation_key and payload.get("correlation_key") != correlation_key:
            continue
        generated_at = payload.get("generated_at_utc") or ""
        matches.append((generated_at, path, payload))
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches
