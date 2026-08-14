"""Repository for run_raw_items table operations (v1.3 lineage)."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from hardstop.database.schema import RunRawItem
from hardstop.utils.logging import get_logger

logger = get_logger(__name__)

VALID_FETCH_ACTIONS = ("NEW", "DUPLICATE", "RETRY")


def record_run_raw_item(
    session: Session,
    *,
    run_group_id: str,
    raw_id: str,
    source_id: str,
    content_hash: Optional[str],
    fetch_action: str,
    recorded_at_utc: Optional[str] = None,
) -> RunRawItem:
    """
    Record that a run group touched a raw item.

    Deliberately does not query for an existing row: sessions are created with
    autoflush disabled, so pending rows are invisible to a query and a
    same-transaction re-add would fail the composite primary key at commit.
    Callers are responsible for not recording the same raw_id twice within a
    run group (see cmd_fetch's recorded_raw_ids set).

    Args:
        session: SQLAlchemy session
        run_group_id: Run group that fetched this item
        raw_id: Raw item ID
        source_id: Source ID
        content_hash: Raw item content hash (may be None on legacy rows)
        fetch_action: NEW | DUPLICATE | RETRY
        recorded_at_utc: Optional ISO 8601 timestamp. If None, uses current time.

    Returns:
        The RunRawItem row added to the session (not yet committed)
    """
    if recorded_at_utc is None:
        recorded_at_utc = datetime.now(timezone.utc).isoformat()

    row = RunRawItem(
        run_group_id=run_group_id,
        raw_id=raw_id,
        source_id=source_id,
        content_hash=content_hash,
        fetch_action=fetch_action,
        recorded_at_utc=recorded_at_utc,
    )
    session.add(row)
    logger.debug(
        "Recorded run lineage: %s/%s (%s)", run_group_id, raw_id, fetch_action
    )
    return row


def list_run_raw_items(session: Session, run_group_id: str) -> List[RunRawItem]:
    """
    List lineage rows for a run group, ordered deterministically.

    Args:
        session: SQLAlchemy session
        run_group_id: Run group ID

    Returns:
        List of RunRawItem rows ordered by (source_id, raw_id)
    """
    return (
        session.query(RunRawItem)
        .filter(RunRawItem.run_group_id == run_group_id)
        .order_by(RunRawItem.source_id.asc(), RunRawItem.raw_id.asc())
        .all()
    )
