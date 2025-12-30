"""Correlation evidence artifact helpers.

These utilities build and read IncidentEvidence artifacts that explain
why alerts merged. Artifacts are JSON documents stored under
``output/incidents/`` (by default) and hashed deterministically so they
can be referenced from RunRecords and replayed later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from hardstop.ops.run_record import artifact_hash, canonical_dumps


def _as_list(value: Iterable[str] | None) -> List[str]:
    if value is None:
        return []
    return list(value)


def _parse_scope(scope_json: Any) -> Dict[str, List[str]]:
    if not scope_json:
        return {"facilities": [], "lanes": [], "shipments": []}
    if isinstance(scope_json, str):
        try:
            scope_json = json.loads(scope_json)
        except json.JSONDecodeError:
            return {"facilities": [], "lanes": [], "shipments": []}
    return {
        "facilities": _as_list(scope_json.get("facilities")),
        "lanes": _as_list(scope_json.get("lanes")),
        "shipments": _as_list(scope_json.get("shipments")),
    }


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class IncidentEvidenceArtifact:
    """Incident evidence artifact payload."""

    artifact_version: str
    kind: str
    correlation_key: str
    generated_at_utc: str
    inputs: Dict[str, Any]
    merge_reasons: List[Dict[str, Any]] = field(default_factory=list)
    merge_summary: List[str] = field(default_factory=list)
    overlap: Dict[str, List[str]] = field(default_factory=dict)
    scope: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    window_hours: int = 0
    artifact_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "artifact_version": self.artifact_version,
            "kind": self.kind,
            "correlation_key": self.correlation_key,
            "generated_at_utc": self.generated_at_utc,
            "inputs": self.inputs,
            "merge_reasons": self.merge_reasons,
            "merge_summary": self.merge_summary,
            "overlap": self.overlap,
            "scope": self.scope,
            "window_hours": self.window_hours,
        }
        payload["artifact_hash"] = self.artifact_hash or artifact_hash(payload)
        return payload


def _build_merge_reasons(
    *,
    correlation_key: str,
    event_facilities: Sequence[str],
    event_lanes: Sequence[str],
    existing_scope: Dict[str, List[str]],
    last_seen_utc: Optional[str],
    generated_at_utc: str,
    window_hours: int,
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, List[str]]]:
    shared_facilities = sorted(set(event_facilities) & set(existing_scope.get("facilities", [])))
    shared_lanes = sorted(set(event_lanes) & set(existing_scope.get("lanes", [])))
    overlap = {"facilities": shared_facilities, "lanes": shared_lanes}

    reasons: List[Dict[str, Any]] = []
    summary: List[str] = []

    reasons.append(
        {
            "code": "CORRELATION_KEY_MATCH",
            "message": "Correlation key matched existing alert",
            "matched": True,
            "details": {"correlation_key": correlation_key},
        }
    )
    summary.append("Correlation key matched existing alert")

    temporal_matched = False
    if last_seen_utc:
        try:
            last_seen_dt = datetime.fromisoformat(last_seen_utc.replace("Z", "+00:00"))
            generated_dt = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
            delta_hours = (generated_dt - last_seen_dt).total_seconds() / 3600.0
            temporal_matched = delta_hours <= window_hours
        except ValueError:
            temporal_matched = False
    reasons.append(
        {
            "code": "TEMPORAL_OVERLAP",
            "message": f"Existing alert seen within {window_hours}h window",
            "matched": temporal_matched,
            "details": {"existing_last_seen_utc": last_seen_utc, "window_hours": window_hours},
        }
    )
    if temporal_matched:
        summary.append(f"Existing alert seen within {window_hours}h window")

    reasons.append(
        {
            "code": "SHARED_FACILITIES",
            "message": f"Shared facilities: {', '.join(shared_facilities)}" if shared_facilities else "No shared facilities",
            "matched": bool(shared_facilities),
            "details": {"shared": shared_facilities},
        }
    )
    if shared_facilities:
        summary.append(f"Shared facilities: {', '.join(shared_facilities)}")

    reasons.append(
        {
            "code": "SHARED_LANES",
            "message": f"Shared lanes: {', '.join(shared_lanes)}" if shared_lanes else "No shared lanes",
            "matched": bool(shared_lanes),
            "details": {"shared": shared_lanes},
        }
    )
    if shared_lanes:
        summary.append(f"Shared lanes: {', '.join(shared_lanes)}")

    return reasons, summary, overlap


def build_incident_evidence_artifact(
    *,
    alert_id: str,
    event: Dict[str, Any],
    correlation_key: str,
    existing_alert: Any,
    window_hours: int,
    dest_dir: str | Path = "output/incidents",
    generated_at: Optional[str] = None,
    filename_basename: Optional[str] = None,
) -> Tuple[IncidentEvidenceArtifact, "ArtifactRef", Path]:
    """
    Build and persist an IncidentEvidence artifact.

    Returns:
        (artifact_obj, ArtifactRef, artifact_path)
    """
    from hardstop.ops.run_record import ArtifactRef  # Local import to avoid cycles

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    generated_at_utc = (generated_at or event.get("event_time_utc") or event.get("published_at_utc") or _now_utc_iso())
    if "Z" not in generated_at_utc and generated_at_utc.endswith("+00:00"):
        generated_at_utc = generated_at_utc.replace("+00:00", "Z")

    scope_existing = _parse_scope(getattr(existing_alert, "scope_json", None))
    scope_incoming = {
        "facilities": _as_list(event.get("facilities")),
        "lanes": _as_list(event.get("lanes")),
        "shipments": _as_list(event.get("shipments")),
    }
    existing_root_ids = getattr(existing_alert, "root_event_ids_json", None)
    if isinstance(existing_root_ids, str):
        try:
            existing_root_ids = json.loads(existing_root_ids)
        except json.JSONDecodeError:
            existing_root_ids = []

    reasons, summary, overlap = _build_merge_reasons(
        correlation_key=correlation_key,
        event_facilities=scope_incoming["facilities"],
        event_lanes=scope_incoming["lanes"],
        existing_scope=scope_existing,
        last_seen_utc=getattr(existing_alert, "last_seen_utc", None),
        generated_at_utc=generated_at_utc,
        window_hours=window_hours,
    )

    artifact = IncidentEvidenceArtifact(
        artifact_version="incident-evidence.v1",
        kind="IncidentEvidence",
        correlation_key=correlation_key,
        generated_at_utc=generated_at_utc,
        inputs={
            "alert_id": alert_id,
            "event": {
                "event_id": event.get("event_id") or event.get("raw_id") or event.get("id"),
                "event_type": event.get("event_type"),
                "observed_at_utc": generated_at_utc,
                "title": event.get("title"),
            },
            "existing_alert": {
                "alert_id": getattr(existing_alert, "alert_id", None),
                "last_seen_utc": getattr(existing_alert, "last_seen_utc", None),
                "root_event_ids": existing_root_ids or [],
            },
        },
        merge_reasons=reasons,
        merge_summary=summary,
        overlap=overlap,
        scope={
            "existing": scope_existing,
            "incoming": scope_incoming,
        },
        window_hours=window_hours,
    )

    payload = artifact.to_dict()
    artifact.artifact_hash = payload["artifact_hash"]

    filename = filename_basename or f"{alert_id}__{event.get('event_id', 'event')}__{correlation_key.replace('|', '_')}"
    artifact_path = dest_dir / f"{filename}.json"
    artifact_path.write_text(canonical_dumps(payload), encoding="utf-8")

    artifact_ref = ArtifactRef(
        id=f"incident-evidence:{alert_id}",
        hash=payload["artifact_hash"],
        kind="IncidentEvidence",
        schema="incident-evidence/v1",
        bytes=len(canonical_dumps(payload).encode("utf-8")),
    )
    return artifact, artifact_ref, artifact_path


def _load_artifact_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_incident_evidence_summary(
    alert_id: str,
    correlation_key: str,
    *,
    dest_dir: str | Path = "output/incidents",
) -> Optional[Dict[str, Any]]:
    """
    Load the latest incident evidence summary for an alert/correlation key pair.
    """
    dest_dir = Path(dest_dir)
    if not dest_dir.exists():
        return None

    candidates = []
    for path in dest_dir.glob("*.json"):
        payload = _load_artifact_file(path)
        if not payload:
            continue
        if payload.get("inputs", {}).get("alert_id") != alert_id:
            continue
        if payload.get("correlation_key") != correlation_key:
            continue
        generated_at = payload.get("generated_at_utc") or ""
        candidates.append((generated_at, path, payload))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    latest_payload = candidates[0][2]
    recomputed_hash = artifact_hash({k: v for k, v in latest_payload.items() if k != "artifact_hash"})
    latest_payload["artifact_hash"] = latest_payload.get("artifact_hash") or recomputed_hash
    return latest_payload


__all__ = [
    "IncidentEvidenceArtifact",
    "build_incident_evidence_artifact",
    "load_incident_evidence_summary",
]
