"""Repository functions for alert persistence and correlation."""

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database.schema import Alert


def find_recent_alert_by_key(
    session: Session,
    correlation_key: str,
    within_days: int = 7,
) -> Optional[Alert]:
    """
    Find the most recent alert with the given correlation key within the specified days.
    
    Uses ISO 8601 string comparison for reliable date filtering (SQLite stores as TEXT).
    
    Args:
        session: SQLAlchemy session
        correlation_key: Correlation key to search for
        within_days: How many days back to look (default 7)
        
    Returns:
        Most recent Alert with matching key, or None if not found
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    cutoff_iso = cutoff.isoformat()  # ISO 8601 string for lexicographic comparison

    q = session.query(Alert).filter(Alert.correlation_key == correlation_key)

    # Get all alerts with matching key, ordered by last_seen_utc
    alerts = q.order_by(Alert.last_seen_utc.desc().nullslast()).all()
    
    # Filter by date using ISO string comparison (works because ISO 8601 is lexicographically sortable)
    for alert in alerts:
        if alert.last_seen_utc:
            # Convert to ISO string if it's a datetime object (shouldn't happen, but be safe)
            if isinstance(alert.last_seen_utc, datetime):
                alert_iso = alert.last_seen_utc.isoformat()
            else:
                alert_iso = str(alert.last_seen_utc)
            
            # Lexicographic comparison works for ISO 8601 strings
            if alert_iso >= cutoff_iso:
                return alert
    
    # If no alerts with valid dates within window, return None (don't return old alerts)
    return None


def load_root_event_ids(alert_row: Alert) -> list[str]:
    """Load root_event_ids from JSON string."""
    if not alert_row.root_event_ids_json:
        return []
    try:
        return json.loads(alert_row.root_event_ids_json)
    except (json.JSONDecodeError, TypeError):
        return []


def save_root_event_ids(alert_row: Alert, ids: list[str]) -> None:
    """Save root_event_ids as JSON string (sorted, deduplicated)."""
    alert_row.root_event_ids_json = json.dumps(sorted(set(ids)))


def upsert_new_alert_row(
    session: Session,
    *,
    alert_id: str,
    summary: str,
    risk_type: str,
    classification: int,
    status: str,
    reasoning: str | None,
    recommended_actions: str | None,
    root_event_id: str,
    correlation_key: str,
    correlation_action: str = "CREATED",
    impact_score: int | None = None,
    scope_json: str | None = None,
    tier: str | None = None,  # v0.7: tier for brief efficiency
    source_id: str | None = None,  # v0.7: source ID for UI efficiency
    trust_tier: int | None = None,  # v0.7: trust tier
) -> Alert:
    """
    Create a new alert row in the database.
    
    Args:
        session: SQLAlchemy session
        alert_id: Unique alert ID
        summary: Alert summary
        risk_type: Risk type
        classification: Classification (0-2)
        status: Status string
        reasoning: Reasoning text (can be None)
        recommended_actions: Recommended actions text (can be None)
        root_event_id: Root event ID
        correlation_key: Correlation key
        correlation_action: Correlation action ("CREATED" or "UPDATED")
        impact_score: Network impact score (0-10, optional)
        scope_json: Scope as JSON string (optional)
        
    Returns:
        Created Alert row
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()  # Store as ISO 8601 string for consistency

    row = Alert(
        alert_id=alert_id,
        summary=summary,
        risk_type=risk_type,
        classification=classification,
        priority=classification,  # DEPRECATED: Mirrors classification for backward compatibility only. Do not use for logic.
        status=status,
        root_event_id=root_event_id,
        reasoning=reasoning,
        recommended_actions=recommended_actions,
        correlation_key=correlation_key,
        correlation_action=correlation_action,
        first_seen_utc=now_iso,  # ISO string for consistent storage
        last_seen_utc=now_iso,   # ISO string for consistent storage
        update_count=0,
        impact_score=impact_score,
        scope_json=scope_json,
        tier=tier,  # v0.7: tier for brief efficiency
        source_id=source_id,  # v0.7: source ID for UI efficiency
        trust_tier=trust_tier,  # v0.7: trust tier
    )
    save_root_event_ids(row, [root_event_id])
    session.add(row)
    return row


def update_existing_alert_row(
    session: Session,
    row: Alert,
    *,
    new_summary: str,
    new_classification: int,
    root_event_id: str,
    correlation_action: str = "UPDATED",
    impact_score: int | None = None,
    scope_json: str | None = None,
    tier: str | None = None,  # v0.7: tier (from latest event)
    source_id: str | None = None,  # v0.7: source ID (from latest event)
    trust_tier: int | None = None,  # v0.7: trust tier (from latest event)
) -> Alert:
    """
    Update an existing alert row with new information.
    
    Args:
        session: SQLAlchemy session
        row: Existing Alert row to update
        new_summary: New summary text
        new_classification: New classification (takes max of old and new)
        root_event_id: New root event ID to add to list
        correlation_action: Correlation action for this update (default "UPDATED")
        impact_score: New impact score (optional, updates if provided)
        scope_json: Updated scope JSON (optional, updates if provided)
        
    Returns:
        Updated Alert row
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()  # Store as ISO 8601 string for consistency

    row.summary = new_summary
    row.classification = max(row.classification or 0, new_classification)
    row.priority = row.classification  # DEPRECATED: Mirrors classification for backward compatibility only. Do not use for logic.
    row.status = "UPDATED"
    row.correlation_action = correlation_action  # Store fact about this update
    row.last_seen_utc = now_iso  # ISO string for consistent storage
    row.update_count = (row.update_count or 0) + 1
    
    if impact_score is not None:
        row.impact_score = impact_score
    
    if scope_json is not None:
        row.scope_json = scope_json  # Update scope with latest event data
    
    # v0.7: Update tier/source_id/trust_tier from latest event (deterministic behavior)
    if tier is not None:
        row.tier = tier
    if source_id is not None:
        row.source_id = source_id
    if trust_tier is not None:
        row.trust_tier = trust_tier

    ids = load_root_event_ids(row)
    if root_event_id not in ids:
        ids.append(root_event_id)
    save_root_event_ids(row, ids)

    session.add(row)
    return row


def query_recent_alerts(
    session: Session,
    since_hours: int = 24,
    include_class0: bool = False,
    limit: int = 20,
) -> List[Alert]:
    """
    Query alerts that were created or updated within the specified time window.
    
    Args:
        session: SQLAlchemy session
        since_hours: How many hours back to look (default 24)
        include_class0: Whether to include classification 0 alerts (default False)
        limit: Maximum number of alerts to return (default 20)
        
    Returns:
        List of Alert rows, sorted by classification DESC, impact_score DESC,
        update_count DESC, last_seen_utc DESC
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    cutoff_iso = cutoff.isoformat()
    
    # Query: last_seen_utc >= cutoff OR first_seen_utc >= cutoff
    q = session.query(Alert).filter(
        or_(
            Alert.last_seen_utc >= cutoff_iso,
            Alert.first_seen_utc >= cutoff_iso,
        )
    )
    
    # Filter out class 0 if not included
    if not include_class0:
        q = q.filter(Alert.classification > 0)
    
    # Sort: classification DESC, impact_score DESC (nulls last), update_count DESC, last_seen_utc DESC
    # Note: SQLite TEXT comparison works for ISO 8601 strings
    q = q.order_by(
        Alert.classification.desc(),
        Alert.impact_score.desc().nullslast(),
        Alert.update_count.desc().nullslast(),
        Alert.last_seen_utc.desc().nullslast(),
    )
    
    return q.limit(limit).all()

