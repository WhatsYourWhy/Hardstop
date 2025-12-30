from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from hardstop.config.loader import (
    load_config,
    load_sources_config,
    load_suppression_config,
)
from hardstop.utils.time import utc_now_z


def _canonical_dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _prune_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _prune_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_prune_none(v) for v in value]
    return value


def fingerprint_config(snapshot: Optional[Dict[str, Any]]) -> str:
    """Return SHA-256 fingerprint for provided config snapshot."""
    snapshot = snapshot or {}
    payload = _canonical_dumps(snapshot).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolve_config_snapshot() -> Dict[str, Any]:
    """Load runtime, sources, and suppression configs (best-effort)."""
    snapshot: Dict[str, Any] = {}
    try:
        snapshot["runtime"] = load_config()
    except FileNotFoundError:
        snapshot["runtime"] = {}
    try:
        snapshot["sources"] = load_sources_config()
    except FileNotFoundError:
        snapshot["sources"] = {}
    try:
        snapshot["suppression"] = load_suppression_config()
    except FileNotFoundError:
        snapshot["suppression"] = {}
    return snapshot


@dataclass
class ArtifactRef:
    id: str
    hash: str
    kind: str
    schema: Optional[str] = None
    bytes: Optional[int] = None


@dataclass
class Diagnostic:
    code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunRecord:
    run_id: str
    operator_id: str
    mode: str
    started_at: str
    ended_at: str
    config_hash: str
    input_refs: List[ArtifactRef] = field(default_factory=list)
    output_refs: List[ArtifactRef] = field(default_factory=list)
    warnings: List[Diagnostic] = field(default_factory=list)
    errors: List[Diagnostic] = field(default_factory=list)
    cost: Dict[str, int] = field(default_factory=dict)
    best_effort: Dict[str, Any] = field(default_factory=dict)


TimeCanonicalizer = Callable[[str], str]


def _apply_canonicalize_time(timestamp: str, canonicalize_time: Optional[TimeCanonicalizer]) -> str:
    if canonicalize_time:
        return canonicalize_time(timestamp)
    return timestamp


def canonicalize_time_factory(
    *,
    fixed_value: Optional[str] = None,
    precision: Optional[int] = None,
) -> TimeCanonicalizer:
    """
    Build a simple timestamp normalizer for deterministic runs.

    Args:
        fixed_value: If provided, always return this value (ignores input).
        precision: Number of microsecond digits to keep (0 = seconds). Values outside
            0-6 are ignored.

    Returns:
        Callable that normalizes ISO8601 timestamps.
    """

    def _canonicalize(timestamp: str) -> str:
        if fixed_value is not None:
            return fixed_value
        if precision is None:
            return timestamp
        if not (0 <= precision <= 6):
            return timestamp
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return timestamp
        micro_factor = 10 ** (6 - precision)
        truncated_micro = (dt.microsecond // micro_factor) * micro_factor
        dt = dt.replace(microsecond=truncated_micro, tzinfo=dt.tzinfo or timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    return _canonicalize


def emit_run_record(
    operator_id: str,
    *,
    mode: str,
    run_id: Optional[str] = None,
    config_snapshot: Optional[Dict[str, Any]] = None,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    canonicalize_time: Optional[TimeCanonicalizer] = None,
    input_refs: Optional[Iterable[ArtifactRef]] = None,
    output_refs: Optional[Iterable[ArtifactRef]] = None,
    warnings: Optional[Iterable[Diagnostic]] = None,
    errors: Optional[Iterable[Diagnostic]] = None,
    cost: Optional[Dict[str, int]] = None,
    best_effort: Optional[Dict[str, Any]] = None,
    dest_dir: Path | str = Path("run_records"),
    filename_basename: Optional[str] = None,
) -> RunRecord:
    """Create and persist a RunRecord JSON document."""
    started_at = _apply_canonicalize_time(started_at or utc_now_z(), canonicalize_time)
    ended_at = _apply_canonicalize_time(ended_at or utc_now_z(), canonicalize_time)
    config_hash = fingerprint_config(config_snapshot)
    record = RunRecord(
        run_id=run_id or str(uuid.uuid4()),
        operator_id=operator_id,
        mode=mode,
        started_at=started_at,
        ended_at=ended_at,
        config_hash=config_hash,
        input_refs=list(input_refs or []),
        output_refs=list(output_refs or []),
        warnings=list(warnings or []),
        errors=list(errors or []),
        cost=cost or {},
        best_effort=best_effort or {},
    )
    output_dir = Path(dest_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{filename_basename}.json"
        if filename_basename
        else f"{record.started_at.replace(':', '').replace('-', '').replace('T', '_')}_{record.run_id}.json"
    )
    target_path = output_dir / filename
    with target_path.open("w", encoding="utf-8") as fh:
        json.dump(_prune_none(asdict(record)), fh, indent=2, sort_keys=True)
    return record


__all__ = [
    "ArtifactRef",
    "Diagnostic",
    "RunRecord",
    "emit_run_record",
    "fingerprint_config",
    "resolve_config_snapshot",
    "canonicalize_time_factory",
    "TimeCanonicalizer",
]
