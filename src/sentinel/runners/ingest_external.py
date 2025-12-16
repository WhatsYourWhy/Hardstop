"""Runner for ingesting external raw items into events and alerts."""

import json
from typing import Dict, Optional

from sqlalchemy.orm import Session

from sentinel.alerts.alert_builder import build_basic_alert
from sentinel.config.loader import get_all_sources, load_sources_config
from sentinel.database.event_repo import save_event
from sentinel.database.raw_item_repo import (
    get_raw_items_for_ingest,
    mark_raw_item_status,
)
from sentinel.parsing.network_linker import link_event_to_network
from sentinel.parsing.normalizer import normalize_external_event
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


def main(
    session: Session,
    limit: Optional[int] = None,
    min_tier: Optional[str] = None,
    source_id: Optional[str] = None,
    since_hours: Optional[int] = None,
) -> Dict[str, int]:
    """
    Main ingestion runner for external raw items.
    
    Processes raw_items with NEW status:
    1. Normalizes to events
    2. Persists events
    3. Links to network data
    4. Builds alerts (with correlation)
    5. Updates raw_item status
    
    Args:
        session: SQLAlchemy session
        limit: Maximum number of raw items to process
        min_tier: Minimum tier (global > regional > local)
        source_id: Filter by specific source ID
        since_hours: Only process items fetched within this many hours
        
    Returns:
        Dict with counts: {"processed": N, "events": M, "alerts": K, "errors": E}
    """
    # Load sources config for metadata
    sources_config = load_sources_config()
    all_sources = {s["id"]: s for s in get_all_sources(sources_config)}
    
    # Get raw items for ingestion
    raw_items = get_raw_items_for_ingest(
        session=session,
        limit=limit,
        min_tier=min_tier,
        source_id=source_id,
        since_hours=since_hours,
    )
    
    logger.info(f"Processing {len(raw_items)} raw items for ingestion")
    
    stats = {
        "processed": 0,
        "events": 0,
        "alerts": 0,
        "errors": 0,
    }
    
    for raw_item in raw_items:
        try:
            # Parse raw payload
            payload = json.loads(raw_item.raw_payload_json)
            
            # Build candidate dict
            candidate = {
                "canonical_id": raw_item.canonical_id,
                "title": raw_item.title,
                "url": raw_item.url,
                "published_at_utc": raw_item.published_at_utc,
                "payload": payload,
            }
            
            # Get source config for metadata
            source_config = all_sources.get(raw_item.source_id, {})
            
            # Normalize to event
            event = normalize_external_event(
                raw_item_candidate=candidate,
                source_id=raw_item.source_id,
                tier=raw_item.tier,
                raw_id=raw_item.raw_id,
                source_config=source_config,
            )
            
            # Persist event
            save_event(session, event)
            session.commit()
            stats["events"] += 1
            logger.debug(f"Created event {event['event_id']} from raw_item {raw_item.raw_id}")
            
            # Link to network
            event = link_event_to_network(event, session=session)
            
            # Build alert (handles correlation internally)
            alert = build_basic_alert(event, session=session)
            stats["alerts"] += 1
            logger.debug(f"Created/updated alert {alert.alert_id} for event {event['event_id']}")
            
            # Mark raw item as normalized
            mark_raw_item_status(session, raw_item.raw_id, "NORMALIZED")
            session.commit()
            
            stats["processed"] += 1
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to process raw_item {raw_item.raw_id}: {error_msg}", exc_info=True)
            mark_raw_item_status(session, raw_item.raw_id, "FAILED", error=error_msg)
            session.commit()
            stats["errors"] += 1
    
    logger.info(
        f"Ingestion complete: {stats['processed']} processed, "
        f"{stats['events']} events, {stats['alerts']} alerts, {stats['errors']} errors"
    )
    
    return stats

