"""Repository for raw_items table operations."""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from sentinel.database.schema import RawItem
from sentinel.retrieval.dedupe import compute_content_hash, get_dedupe_key
from sentinel.utils.id_generator import new_event_id
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


def save_raw_item(
    session: Session,
    source_id: str,
    tier: str,
    candidate: Dict,
    fetched_at_utc: Optional[str] = None,
    trust_tier: Optional[int] = None,
) -> RawItem:
    """
    Save a raw item candidate to the database with deduplication.
    
    Args:
        session: SQLAlchemy session
        source_id: Source ID
        tier: Tier (global, regional, local)
        candidate: RawItemCandidate dict
        fetched_at_utc: Optional ISO 8601 timestamp. If None, uses current time.
        trust_tier: Optional trust tier (1|2|3). Default 2 if None.
        
    Returns:
        RawItem row (new or existing)
    """
    if fetched_at_utc is None:
        fetched_at_utc = datetime.now(timezone.utc).isoformat()
    
    canonical_id, content_hash = get_dedupe_key(source_id, candidate)
    
    # Check for existing item by canonical_id
    existing = None
    if canonical_id:
        existing = session.query(RawItem).filter(
            RawItem.source_id == source_id,
            RawItem.canonical_id == canonical_id,
        ).first()
    
    # If not found by canonical_id, check by content_hash
    if not existing and content_hash:
        existing = session.query(RawItem).filter(
            RawItem.source_id == source_id,
            RawItem.content_hash == content_hash,
        ).first()
    
    if existing:
        # Update fetched_at_utc but keep status
        existing.fetched_at_utc = fetched_at_utc
        logger.debug(f"Raw item already exists (dedupe): {source_id}/{canonical_id or content_hash[:8]}")
        return existing
    
    # Create new raw item
    raw_id = f"RAW-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{new_event_id().split('-')[-1]}"
    
    # Ensure content_hash is computed
    if not content_hash:
        content_hash = compute_content_hash(candidate)
    
    raw_item = RawItem(
        raw_id=raw_id,
        source_id=source_id,
        tier=tier,
        fetched_at_utc=fetched_at_utc,
        published_at_utc=candidate.get("published_at_utc"),
        canonical_id=canonical_id,
        url=candidate.get("url"),
        title=candidate.get("title"),
        raw_payload_json=json.dumps(candidate.get("payload", {}), default=str),
        content_hash=content_hash,
        status="NEW",
        error=None,
        trust_tier=trust_tier,
    )
    
    session.add(raw_item)
    logger.debug(f"Created new raw item: {raw_id} from {source_id}")
    return raw_item


def get_raw_items_for_ingest(
    session: Session,
    limit: Optional[int] = None,
    min_tier: Optional[str] = None,
    source_id: Optional[str] = None,
    since_hours: Optional[int] = None,
) -> List[RawItem]:
    """
    Get raw items with NEW status for ingestion.
    
    Args:
        session: SQLAlchemy session
        limit: Maximum number of items to return
        min_tier: Minimum tier (global > regional > local). None = all tiers.
        source_id: Filter by specific source ID. None = all sources.
        since_hours: Only get items fetched within this many hours. None = all.
        
    Returns:
        List of RawItem rows
    """
    query = session.query(RawItem).filter(RawItem.status == "NEW")
    
    # Filter by source
    if source_id:
        query = query.filter(RawItem.source_id == source_id)
    
    # Filter by tier (tier priority: global > regional > local)
    if min_tier:
        tier_priority = {"global": 3, "regional": 2, "local": 1}
        min_priority = tier_priority.get(min_tier, 0)
        for tier, priority in tier_priority.items():
            if priority >= min_priority:
                continue
            query = query.filter(RawItem.tier != tier)
    
    # Filter by time (belt-and-suspenders: both fetched_at and published_at)
    if since_hours:
        cutoff = datetime.now(timezone.utc).timestamp() - (since_hours * 3600)
        # Compare ISO strings (lexicographic comparison works for ISO 8601)
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        # Primary filter: fetched_at_utc (when we actually got it)
        query = query.filter(RawItem.fetched_at_utc >= cutoff_iso)
        # Secondary filter: published_at_utc if available (feeds can be inconsistent)
        # Only include items where published_at_utc is None (no date) or within window
        from sqlalchemy import or_
        query = query.filter(
            or_(
                RawItem.published_at_utc.is_(None),  # No published date = include
                RawItem.published_at_utc >= cutoff_iso,  # Published within window = include
            )
        )
    
    # Order by fetched_at_utc (oldest first)
    query = query.order_by(RawItem.fetched_at_utc.asc())
    
    if limit:
        query = query.limit(limit)
    
    return query.all()


def mark_raw_item_status(
    session: Session,
    raw_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """
    Update raw item status.
    
    Args:
        session: SQLAlchemy session
        raw_id: Raw item ID
        status: New status (NORMALIZED, FAILED)
        error: Optional error message (for FAILED status)
    """
    raw_item = session.query(RawItem).filter(RawItem.raw_id == raw_id).first()
    if not raw_item:
        logger.warning(f"Raw item not found: {raw_id}")
        return
    
    raw_item.status = status
    if error:
        raw_item.error = error
    
    session.commit()
    logger.debug(f"Updated raw item {raw_id} status to {status}")


def get_raw_item_by_id(session: Session, raw_id: str) -> Optional[RawItem]:
    """Get raw item by ID."""
    return session.query(RawItem).filter(RawItem.raw_id == raw_id).first()

