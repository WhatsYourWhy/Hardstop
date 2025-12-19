"""Repository functions for source_runs table operations (v0.9)."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from sentinel.database.schema import SourceRun
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


def create_source_run(
    session: Session,
    run_group_id: str,
    source_id: str,
    phase: str,  # FETCH | INGEST
    run_at_utc: str,  # ISO 8601
    status: str,  # SUCCESS | FAILURE
    status_code: Optional[int] = None,
    error: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    items_fetched: int = 0,
    items_new: int = 0,
    items_processed: int = 0,
    items_suppressed: int = 0,
    items_events_created: int = 0,
    items_alerts_touched: int = 0,
) -> SourceRun:
    """
    Create a SourceRun record.
    
    Args:
        session: SQLAlchemy session
        run_group_id: UUID linking related runs
        source_id: Source ID
        phase: FETCH or INGEST
        run_at_utc: ISO 8601 timestamp
        status: SUCCESS or FAILURE
        status_code: HTTP status code (if applicable)
        error: Error message (if failed)
        duration_seconds: Duration of the operation
        items_fetched: Number of items fetched (FETCH phase)
        items_new: Number of new items stored (FETCH phase)
        items_processed: Number of items processed (INGEST phase)
        items_suppressed: Number of items suppressed (INGEST phase)
        items_events_created: Number of events created (INGEST phase)
        items_alerts_touched: Number of alerts created/updated (INGEST phase)
        
    Returns:
        SourceRun row
    """
    run_id = str(uuid.uuid4())
    
    source_run = SourceRun(
        run_id=run_id,
        run_group_id=run_group_id,
        source_id=source_id,
        phase=phase,
        run_at_utc=run_at_utc,
        status=status,
        status_code=status_code,
        error=error,
        duration_seconds=duration_seconds,
        items_fetched=items_fetched,
        items_new=items_new,
        items_processed=items_processed,
        items_suppressed=items_suppressed,
        items_events_created=items_events_created,
        items_alerts_touched=items_alerts_touched,
    )
    
    session.add(source_run)
    logger.debug(f"Created SourceRun {run_id} for {source_id} ({phase}, {status})")
    
    return source_run


def list_recent_runs(
    session: Session,
    source_id: Optional[str] = None,
    limit: int = 50,
    phase: Optional[str] = None,
) -> List[SourceRun]:
    """
    Query recent source runs with optional filters.
    
    Args:
        session: SQLAlchemy session
        source_id: Filter by source ID (optional)
        limit: Maximum number of runs to return
        phase: Filter by phase (FETCH or INGEST, optional)
        
    Returns:
        List of SourceRun rows, ordered by run_at_utc DESC
    """
    query = session.query(SourceRun)
    
    if source_id:
        query = query.filter(SourceRun.source_id == source_id)
    
    if phase:
        query = query.filter(SourceRun.phase == phase)
    
    return query.order_by(SourceRun.run_at_utc.desc()).limit(limit).all()


def get_source_health(
    session: Session,
    source_id: str,
    lookback_n: int = 10,
) -> Dict:
    """
    Get health metrics for a specific source.
    
    Args:
        session: SQLAlchemy session
        source_id: Source ID
        lookback_n: Number of recent FETCH runs to consider for success rate
        
    Returns:
        Dict with:
        - last_success_utc: Most recent successful FETCH run (ISO 8601 or None)
        - last_failure_utc: Most recent failed FETCH run (ISO 8601 or None)
        - success_rate: Success rate from last N FETCH runs (0.0 to 1.0)
        - last_status_code: Status code from most recent FETCH run (int or None)
        - last_error: Error message from most recent FETCH run (str or None)
        - last_items_fetched: Items fetched in most recent FETCH run (int)
        - last_items_new: New items stored in most recent FETCH run (int)
        - last_ingest: Dict with processed/suppressed/events/alerts from most recent INGEST run
    """
    # Get recent FETCH runs
    fetch_runs = list_recent_runs(session, source_id=source_id, limit=lookback_n, phase="FETCH")
    
    # Calculate success rate
    if fetch_runs:
        successful = sum(1 for run in fetch_runs if run.status == "SUCCESS")
        success_rate = successful / len(fetch_runs)
    else:
        success_rate = 0.0
    
    # Find last success and failure
    last_success_utc = None
    last_failure_utc = None
    last_status_code = None
    last_error = None
    last_items_fetched = 0
    last_items_new = 0
    
    for run in fetch_runs:
        if run.status == "SUCCESS" and last_success_utc is None:
            last_success_utc = run.run_at_utc
            if last_status_code is None:
                last_status_code = run.status_code
            if last_items_fetched == 0:
                last_items_fetched = run.items_fetched
            if last_items_new == 0:
                last_items_new = run.items_new
        elif run.status == "FAILURE" and last_failure_utc is None:
            last_failure_utc = run.run_at_utc
            if last_status_code is None:
                last_status_code = run.status_code
            if last_error is None:
                last_error = run.error
    
    # Get most recent FETCH run for status_code/error/items (if not already set)
    if fetch_runs:
        most_recent = fetch_runs[0]
        if last_status_code is None:
            last_status_code = most_recent.status_code
        if last_error is None:
            last_error = most_recent.error
        if last_items_fetched == 0:
            last_items_fetched = most_recent.items_fetched
        if last_items_new == 0:
            last_items_new = most_recent.items_new
    
    # Get most recent INGEST run
    ingest_runs = list_recent_runs(session, source_id=source_id, limit=1, phase="INGEST")
    last_ingest = {
        "processed": 0,
        "suppressed": 0,
        "events": 0,
        "alerts": 0,
    }
    
    if ingest_runs:
        run = ingest_runs[0]
        last_ingest = {
            "processed": run.items_processed,
            "suppressed": run.items_suppressed,
            "events": run.items_events_created,
            "alerts": run.items_alerts_touched,
        }
    
    return {
        "last_success_utc": last_success_utc,
        "last_failure_utc": last_failure_utc,
        "success_rate": success_rate,
        "last_status_code": last_status_code,
        "last_error": last_error,
        "last_items_fetched": last_items_fetched,
        "last_items_new": last_items_new,
        "last_ingest": last_ingest,
    }


def get_all_source_health(
    session: Session,
    lookback_n: int = 10,
) -> List[Dict]:
    """
    Get health metrics for all sources.
    
    Args:
        session: SQLAlchemy session
        lookback_n: Number of recent FETCH runs to consider for success rate
        
    Returns:
        List of health dicts, one per source_id
    """
    # Get all unique source_ids
    source_ids = session.query(SourceRun.source_id).distinct().all()
    source_ids = [row[0] for row in source_ids]
    
    # Get health for each source
    health_list = []
    for source_id in source_ids:
        health = get_source_health(session, source_id, lookback_n=lookback_n)
        health["source_id"] = source_id
        health_list.append(health)
    
    return health_list

