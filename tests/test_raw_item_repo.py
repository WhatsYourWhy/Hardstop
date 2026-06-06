from hardstop.database.raw_item_repo import (
    get_raw_items_for_ingest,
    mark_raw_item_status,
    save_raw_item,
)


def test_refetch_failed_raw_item_requeues_for_ingest(session):
    candidate = {
        "canonical_id": "retry-me",
        "title": "Retry me",
        "payload": {"title": "Retry me"},
    }

    raw_item = save_raw_item(
        session,
        source_id="source-a",
        tier="global",
        candidate=candidate,
        fetched_at_utc="2026-01-01T00:00:00+00:00",
    )
    session.commit()

    mark_raw_item_status(session, raw_item.raw_id, "FAILED", error="transient parse failure")
    session.commit()

    refetched = save_raw_item(
        session,
        source_id="source-a",
        tier="global",
        candidate=candidate,
        fetched_at_utc="2026-01-02T00:00:00+00:00",
    )
    session.commit()

    queued_ids = [item.raw_id for item in get_raw_items_for_ingest(session)]

    assert refetched.raw_id == raw_item.raw_id
    assert refetched.status == "NEW"
    assert refetched.error is None
    assert refetched.raw_id in queued_ids
