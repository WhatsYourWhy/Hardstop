"""Tests for alert provenance semantics."""

from datetime import datetime, timedelta, timezone

from hardstop.api.alerts_api import get_alert_detail
from hardstop.database.alert_repo import update_existing_alert_row, upsert_new_alert_row
from hardstop.database.event_repo import save_event
from hardstop.database.raw_item_repo import save_raw_item


def test_alert_provenance_first_seen_uses_earliest_raw_item(session):
    base_time = datetime(2024, 5, 1, tzinfo=timezone.utc)
    first_seen_time = base_time.isoformat()
    later_time = (base_time + timedelta(hours=2)).isoformat()

    raw_item_first = save_raw_item(
        session,
        source_id="SRC-FIRST",
        tier="global",
        candidate={"payload": {"id": "one"}},
        fetched_at_utc=first_seen_time,
    )
    raw_item_later = save_raw_item(
        session,
        source_id="SRC-LATER",
        tier="local",
        candidate={"payload": {"id": "two"}},
        fetched_at_utc=later_time,
    )

    save_event(
        session,
        {
            "event_id": "EVT-PROV-1",
            "source_type": "TEST",
            "source_id": "SRC-FIRST",
            "raw_id": raw_item_first.raw_id,
            "event_time_utc": first_seen_time,
        },
    )
    save_event(
        session,
        {
            "event_id": "EVT-PROV-2",
            "source_type": "TEST",
            "source_id": "SRC-LATER",
            "raw_id": raw_item_later.raw_id,
            "event_time_utc": later_time,
        },
    )

    alert_row = upsert_new_alert_row(
        session,
        alert_id="ALERT-PROV-1",
        summary="Provenance test alert",
        risk_type="TEST",
        classification=1,
        status="OPEN",
        reasoning=None,
        recommended_actions=None,
        root_event_id="EVT-PROV-1",
        correlation_key="prov:test:1",
    )
    update_existing_alert_row(
        session,
        alert_row,
        new_summary="Provenance test alert updated",
        new_classification=1,
        root_event_id="EVT-PROV-2",
        correlation_action="UPDATED",
    )
    session.commit()

    detail = get_alert_detail(session, "ALERT-PROV-1")
    assert detail is not None
    assert detail.provenance is not None
    assert detail.provenance.first_seen_source_id == "SRC-FIRST"
    assert detail.provenance.first_seen_tier == "global"


def test_alert_provenance_falls_back_to_event_time(session):
    early_time = datetime(2024, 6, 1, tzinfo=timezone.utc).isoformat()
    later_time = datetime(2024, 6, 1, 1, tzinfo=timezone.utc).isoformat()

    save_event(
        session,
        {
            "event_id": "EVT-PROV-3",
            "source_type": "TEST",
            "source_id": "SRC-EVENT",
            "event_time_utc": early_time,
        },
    )
    save_event(
        session,
        {
            "event_id": "EVT-PROV-4",
            "source_type": "TEST",
            "source_id": "SRC-LATER",
            "event_time_utc": later_time,
        },
    )

    alert_row = upsert_new_alert_row(
        session,
        alert_id="ALERT-PROV-2",
        summary="Event time provenance",
        risk_type="TEST",
        classification=1,
        status="OPEN",
        reasoning=None,
        recommended_actions=None,
        root_event_id="EVT-PROV-4",
        correlation_key="prov:test:2",
    )
    update_existing_alert_row(
        session,
        alert_row,
        new_summary="Event time provenance updated",
        new_classification=1,
        root_event_id="EVT-PROV-3",
        correlation_action="UPDATED",
    )
    session.commit()

    detail = get_alert_detail(session, "ALERT-PROV-2")
    assert detail is not None
    assert detail.provenance is not None
    assert detail.provenance.first_seen_source_id == "SRC-EVENT"
    assert detail.provenance.first_seen_tier is None
