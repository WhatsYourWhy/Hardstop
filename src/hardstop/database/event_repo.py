"""Repository for events table operations."""

import json
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from hardstop.database.schema import Event
from hardstop.utils.logging import get_logger

logger = get_logger(__name__)


def save_event(
    session: Session,
    event: Dict,
    suppression_primary_rule_id: Optional[str] = None,
    suppression_rule_ids: Optional[List[str]] = None,
    suppressed_at_utc: Optional[str] = None,
    suppression_reason_code: Optional[str] = None,
) -> Event:
    """
    Save normalized event to database.
    
    Args:
        session: SQLAlchemy session
        event: Normalized event dict
        suppression_primary_rule_id: Optional primary suppression rule ID (v0.8)
        suppression_rule_ids: Optional list of matched suppression rule IDs (v0.8)
        suppressed_at_utc: Optional ISO 8601 timestamp when suppressed (v0.8)
        suppression_reason_code: Optional stable reason code for analytics (v1.1)
        
    Returns:
        Event row
    """
    event_id = event.get("event_id")
    if not event_id:
        raise ValueError("Event must have event_id")
    
    # Check if event already exists
    existing = session.query(Event).filter(Event.event_id == event_id).first()
    if existing:
        logger.debug(f"Event already exists: {event_id}")
        return existing
    
    # Prepare suppression metadata
    suppression_rule_ids_json = None
    if suppression_rule_ids:
        suppression_rule_ids_json = json.dumps(suppression_rule_ids)
    
    # Create new event
    event_row = Event(
        event_id=event_id,
        source_type=event.get("source_type", "UNKNOWN"),
        source_name=event.get("source_name"),
        source_id=event.get("source_id"),
        raw_id=event.get("raw_id"),
        title=event.get("title"),
        raw_text=event.get("raw_text"),
        event_type=event.get("event_type"),
        event_time_utc=event.get("event_time_utc"),
        severity_guess=event.get("severity_guess", 1),
        city=event.get("city"),
        state=event.get("state"),
        country=event.get("country"),
        location_hint=event.get("location_hint"),
        entities_json=event.get("entities_json"),
        event_payload_json=event.get("event_payload_json"),
        trust_tier=event.get("trust_tier"),  # v0.7: store trust_tier
        suppression_primary_rule_id=suppression_primary_rule_id,  # v0.8: suppression metadata
        suppression_rule_ids_json=suppression_rule_ids_json,
        suppressed_at_utc=suppressed_at_utc,
        suppression_reason_code=suppression_reason_code,
    )
    
    session.add(event_row)
    logger.debug(f"Created new event: {event_id}")
    return event_row


def get_event_by_id(session: Session, event_id: str) -> Optional[Event]:
    """Get event by ID."""
    return session.query(Event).filter(Event.event_id == event_id).first()


def get_events_by_source(
    session: Session,
    source_id: str,
    limit: Optional[int] = None,
) -> list[Event]:
    """Get events by source ID."""
    query = session.query(Event).filter(Event.source_id == source_id)
    query = query.order_by(Event.event_time_utc.desc() if Event.event_time_utc else Event.event_id.desc())
    if limit:
        query = query.limit(limit)
    return query.all()

