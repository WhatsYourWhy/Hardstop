"""v1.3 incident evidence hash verification on the read path."""

import json

import pytest

from hardstop.ops.run_record import artifact_hash, canonical_dumps
from hardstop.output.incidents.evidence import (
    IncidentArtifactMismatchError,
    load_incident_evidence_summary,
    verify_artifact_payload,
)


def _write_artifact(dest_dir, *, alert_id="ALERT-1", correlation_key="KEY-1", tamper=False):
    dest_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "artifact_version": "incident-evidence.v1",
        "kind": "IncidentEvidence",
        "correlation_key": correlation_key,
        "generated_at_utc": "2025-01-01T00:00:00Z",
        "merge_reasons": [],
        "merge_summary": ["Shared facilities: FAC-1"],
        "inputs": {"alert_id": alert_id},
    }
    payload["artifact_hash"] = artifact_hash(payload)
    if tamper:
        # Change the body without updating the stored hash -- the exact case
        # the pre-v1.3 loader trusted silently.
        payload["merge_summary"] = ["Tampered: totally different reason"]
    path = dest_dir / f"{alert_id}.json"
    path.write_text(canonical_dumps(payload), encoding="utf-8")
    return path


def test_verify_artifact_payload_accepts_intact_artifact(tmp_path):
    path = _write_artifact(tmp_path / "incidents")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected, stored, matches = verify_artifact_payload(payload)
    assert matches
    assert expected == stored


def test_verify_artifact_payload_detects_tampering(tmp_path):
    path = _write_artifact(tmp_path / "incidents", tamper=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected, stored, matches = verify_artifact_payload(payload)
    assert not matches
    assert expected != stored


def test_verify_artifact_payload_treats_missing_hash_as_match(tmp_path):
    """A hash-less artifact is legitimate; there is nothing to contradict."""
    payload = {"kind": "IncidentEvidence", "inputs": {"alert_id": "A"}}
    expected, stored, matches = verify_artifact_payload(payload)
    assert matches
    assert stored is None
    assert expected


def test_load_summary_returns_verified_artifact_unchanged(tmp_path):
    """The happy path must not gain verification keys (brief.v1 compatibility)."""
    dest = tmp_path / "incidents"
    _write_artifact(dest)
    summary = load_incident_evidence_summary("ALERT-1", "KEY-1", dest_dir=dest)
    assert summary is not None
    assert "artifact_hash_verified" not in summary
    assert "artifact_hash_expected" not in summary


def test_load_summary_flags_tampered_artifact_in_best_effort(tmp_path):
    dest = tmp_path / "incidents"
    _write_artifact(dest, tamper=True)
    summary = load_incident_evidence_summary("ALERT-1", "KEY-1", dest_dir=dest)
    assert summary["artifact_hash_verified"] is False
    assert summary["artifact_hash_expected"]
    assert summary["artifact_hash_expected"] != summary["artifact_hash"]


def test_load_summary_raises_on_tampered_artifact_in_strict(tmp_path):
    dest = tmp_path / "incidents"
    _write_artifact(dest, tamper=True)
    with pytest.raises(IncidentArtifactMismatchError):
        load_incident_evidence_summary("ALERT-1", "KEY-1", dest_dir=dest, strict=True)


def test_verify_helper_agrees_with_incidents_replay(tmp_path):
    """
    The replay command and the brief read path must use the same check.

    cmd_incidents_replay computes the expected hash via verify_artifact_payload;
    this pins that they agree so the two surfaces cannot drift apart again.
    """
    path = _write_artifact(tmp_path / "incidents", tamper=True)
    payload = json.loads(path.read_text(encoding="utf-8"))

    expected, _stored, _matches = verify_artifact_payload(payload)
    replay_expected = artifact_hash(
        {k: v for k, v in payload.items() if k != "artifact_hash"}
    )
    assert expected == replay_expected


def test_renderer_marks_unverified_evidence():
    from hardstop.output.daily_brief import render_markdown

    alert = {
        "alert_id": "ALERT-1",
        "classification": 2,
        "impact_score": 9,
        "summary": "Spill",
        "correlation": {"key": "K", "action": "CREATED", "alert_id": "ALERT-1"},
        "scope": {
            "facilities": [], "lanes": [], "shipments": [],
            "shipments_total_linked": 0, "shipments_truncated": False,
        },
        "first_seen_utc": "2025-01-01T00:00:00Z",
        "last_seen_utc": "2025-01-01T00:00:00Z",
        "update_count": 0,
        "tier": "global",
        "trust_tier": 2,
        "evidence_summary": {
            "merge_summary": ["Shared facilities: FAC-1"],
            "artifact_hash": "abc123",
            "artifact_hash_verified": False,
        },
    }
    brief_data = {
        "read_model_version": "brief.v1",
        "generated_at_utc": "2025-01-02T00:00:00Z",
        "window": {"since": "24h", "since_hours": 24},
        "counts": {"new": 1, "updated": 0, "impactful": 1, "relevant": 0, "interesting": 0},
        "tier_counts": {"global": 1, "regional": 0, "local": 0, "unknown": 0},
        "top": [alert],
        "updated": [],
        "created": [alert],
        "suppressed": {"count": 0, "by_rule": [], "by_source": []},
        "suppressed_legacy": {"total_queried": 1, "limit_applied": 20},
    }

    markdown = render_markdown(brief_data)
    assert "Evidence (UNVERIFIED):" in markdown
