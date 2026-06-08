import json
from datetime import datetime, timedelta, timezone

from hardstop.database.raw_item_repo import (
    get_raw_items_for_ingest,
    mark_raw_item_status,
    save_raw_item,
)
from hardstop.retrieval.dedupe import compute_content_hash


def test_refetch_failed_raw_item_requeues_for_ingest(session):
    candidate = {
        "canonical_id": "retry-me",
        "title": "Retry me",
        "url": "https://example.test/retry-me",
        "payload": {"title": "Retry me", "description": "bad payload"},
    }
    refetched_candidate = {
        "canonical_id": "retry-me",
        "title": "Retry me with corrected data",
        "url": "https://example.test/retry-me-corrected",
        "published_at_utc": "2026-01-02T00:00:00+00:00",
        "payload": {"title": "Retry me with corrected data", "description": "usable payload"},
    }

    raw_item = save_raw_item(
        session,
        source_id="source-a",
        tier="global",
        candidate=candidate,
        fetched_at_utc="2026-01-01T00:00:00+00:00",
        trust_tier=2,
    )
    session.commit()
    original_content_hash = raw_item.content_hash

    mark_raw_item_status(session, raw_item.raw_id, "FAILED", error="transient parse failure")
    session.commit()

    refetched = save_raw_item(
        session,
        source_id="source-a",
        tier="regional",
        candidate=refetched_candidate,
        fetched_at_utc="2026-01-02T00:00:00+00:00",
        trust_tier=3,
    )
    session.commit()

    queued_ids = [item.raw_id for item in get_raw_items_for_ingest(session)]

    assert refetched.raw_id == raw_item.raw_id
    assert refetched.status == "NEW"
    assert refetched.error is None
    assert refetched.raw_id in queued_ids
    assert refetched.tier == "regional"
    assert refetched.trust_tier == 3
    assert refetched.published_at_utc == "2026-01-02T00:00:00+00:00"
    assert refetched.title == "Retry me with corrected data"
    assert refetched.url == "https://example.test/retry-me-corrected"
    assert json.loads(refetched.raw_payload_json) == refetched_candidate["payload"]
    assert refetched.content_hash == compute_content_hash(refetched_candidate)
    assert refetched.content_hash != original_content_hash


def test_refetch_failed_raw_item_with_old_publish_date_survives_since_filter(session):
    now = datetime.now(timezone.utc)
    old_published_at = (now - timedelta(days=30)).isoformat()
    refetched_at = now.isoformat()
    candidate = {
        "canonical_id": "retry-old-published",
        "title": "Old article with transient failure",
        "url": "https://example.test/retry-old-published",
        "published_at_utc": old_published_at,
        "payload": {"title": "Old article with transient failure", "description": "bad payload"},
    }
    refetched_candidate = {
        **candidate,
        "payload": {"title": "Old article with transient failure", "description": "usable payload"},
    }

    raw_item = save_raw_item(
        session,
        source_id="source-a",
        tier="global",
        candidate=candidate,
        fetched_at_utc=(now - timedelta(days=1, minutes=1)).isoformat(),
        trust_tier=2,
    )
    session.commit()

    mark_raw_item_status(session, raw_item.raw_id, "FAILED", error="transient parse failure")
    session.commit()

    refetched = save_raw_item(
        session,
        source_id="source-a",
        tier="global",
        candidate=refetched_candidate,
        fetched_at_utc=refetched_at,
        trust_tier=2,
    )
    session.commit()

    queued_ids = [item.raw_id for item in get_raw_items_for_ingest(session, since_hours=24)]

    assert refetched.raw_id == raw_item.raw_id
    assert refetched.status == "NEW"
    assert refetched.published_at_utc == old_published_at
    assert refetched.raw_id in queued_ids
