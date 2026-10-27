"""Regression tests for the alert/evidence commit ordering.

These tests cover the first fail-closed safeguard, not the planned immutable
database-backed evidence and alert versioning layer.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from hardstop.alerts.alert_builder import build_basic_alert
from hardstop.database.schema import Alert


def _event(event_id="EVT-COMMIT-1"):
    return {
        "event_id": event_id,
        "title": "Warehouse closure",
        "raw_text": "Warehouse closure at DC-01",
        "event_type": "CLOSURE",
        "facilities": ["DC-01"],
        "lanes": [],
        "shipments": [],
        "event_time_utc": "2026-10-27T00:00:00Z",
        "link_confidence": {"facility": 0.95},
        "link_provenance": {"facility": "FACILITY_ID_EXACT"},
        "trust_tier": 2,
    }


def _alerts(session):
    return session.execute(select(Alert)).scalars().all()


def test_evidence_write_failure_does_not_commit_new_alert(session, tmp_path):
    with patch(
        "hardstop.alerts.alert_builder.build_incident_evidence_artifact",
        side_effect=OSError("disk full"),
    ), pytest.raises(OSError, match="disk full"):
        build_basic_alert(_event(), session=session, incident_dest_dir=tmp_path)

    assert _alerts(session) == []


def test_evidence_hash_mismatch_does_not_commit_new_alert(session, tmp_path):
    with patch(
        "hardstop.alerts.alert_builder.verify_artifact_payload",
        return_value=("incorrect", "incorrect", False),
    ), pytest.raises(ValueError, match="failed verification"):
        build_basic_alert(_event(), session=session, incident_dest_dir=tmp_path)

    assert _alerts(session) == []


def test_evidence_exists_before_new_alert_commit(session, tmp_path):
    original_commit = session.commit

    def checked_commit():
        artifacts = list(Path(tmp_path).glob("*.json"))
        assert len(artifacts) == 1
        assert json.loads(artifacts[0].read_text(encoding="utf-8"))["artifact_hash"]
        original_commit()

    with patch.object(session, "commit", side_effect=checked_commit):
        alert = build_basic_alert(_event(), session=session, incident_dest_dir=tmp_path)

    assert _alerts(session)[0].alert_id == alert.alert_id


def test_failed_evidence_write_preserves_existing_alert(session, tmp_path):
    initial = build_basic_alert(_event(), session=session, incident_dest_dir=tmp_path)
    row = _alerts(session)[0]
    original_count = row.update_count
    original_summary = row.summary

    with patch(
        "hardstop.alerts.alert_builder.build_incident_evidence_artifact",
        side_effect=OSError("disk full"),
    ), pytest.raises(OSError, match="disk full"):
        build_basic_alert(
            {**_event("EVT-COMMIT-2"), "title": "Revised warehouse closure"},
            session=session,
            incident_dest_dir=tmp_path,
        )

    session.expire_all()
    row = _alerts(session)[0]
    assert row.alert_id == initial.alert_id
    assert row.update_count == original_count
    assert row.summary == original_summary
