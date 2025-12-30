"""Repository functions for source_runs table operations (v1.1)."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from hardstop.database.schema import SourceRun
from hardstop.ops.source_health import compute_health_score
from hardstop.utils.logging import get_logger

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
    diagnostics: Optional[Dict[str, Any]] = None,
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
        diagnostics: Optional structured diagnostics for observability
        
    Returns:
        SourceRun row
    """
    run_id = str(uuid.uuid4())
    
    diagnostics_json = json.dumps(diagnostics) if diagnostics else None

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
        diagnostics_json=diagnostics_json,
    )
    
    session.add(source_run)
    logger.debug(f"Created SourceRun {run_id} for {source_id} ({phase}, {status})")
    
    return source_run


def list_recent_runs(
    session: Session,
    source_id: Optional[str] = None,
    limit: int = 50,
    phase: Optional[str] = None,
    run_group_id: Optional[str] = None,
) -> List[SourceRun]:
    """
    Query recent source runs with optional filters.
    
    Args:
        session: SQLAlchemy session
        source_id: Filter by source ID (optional)
        limit: Maximum number of runs to return
        phase: Filter by phase (FETCH or INGEST, optional)
        run_group_id: Filter by run_group_id (optional)
        
    Returns:
        List of SourceRun rows, ordered by run_at_utc DESC
    """
    query = session.query(SourceRun)
    
    if source_id:
        query = query.filter(SourceRun.source_id == source_id)
    
    if phase:
        query = query.filter(SourceRun.phase == phase)
    
    if run_group_id:
        query = query.filter(SourceRun.run_group_id == run_group_id)
    
    return query.order_by(SourceRun.run_at_utc.desc()).limit(limit).all()


def _load_diagnostics(row: SourceRun) -> Dict[str, Any]:
    if not row.diagnostics_json:
        return {}
    try:
        return json.loads(row.diagnostics_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_source_health(
    session: Session,
    source_id: str,
    lookback_n: int = 10,
    stale_threshold_hours: int = 48,
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
    
    fetch_durations: List[float] = []
    bytes_downloaded: List[int] = []
    dedupe_rates: List[float] = []
    consecutive_failures = 0
    max_failure_streak_computed = False

    for run in fetch_runs:
        diagnostics = _load_diagnostics(run)
        if run.duration_seconds:
            fetch_durations.append(run.duration_seconds)
        if diagnostics.get("bytes_downloaded") is not None:
            bytes_downloaded.append(int(diagnostics.get("bytes_downloaded") or 0))
        items_seen = diagnostics.get("items_seen")
        dedupe_dropped = diagnostics.get("dedupe_dropped")
        if items_seen:
            dropped = dedupe_dropped or 0
            dedupe_rates.append(dropped / max(items_seen, 1))

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

        if not max_failure_streak_computed:
            if run.status == "FAILURE":
                consecutive_failures += 1
            else:
                max_failure_streak_computed = True
    
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
        "suppression_reason_counts": {},
    }
    
    if ingest_runs:
        run = ingest_runs[0]
        diagnostics = _load_diagnostics(run)
        last_ingest = {
            "processed": run.items_processed,
            "suppressed": run.items_suppressed,
            "events": run.items_events_created,
            "alerts": run.items_alerts_touched,
            "suppression_reason_counts": diagnostics.get("suppression_reason_counts", {}),
        }

    suppression_ratio = None
    if last_ingest["processed"]:
        suppression_ratio = last_ingest["suppressed"] / max(last_ingest["processed"], 1)

    last_success_dt = _parse_iso_timestamp(last_success_utc)
    stale_hours = None
    if last_success_dt:
        stale_hours = (datetime.now(timezone.utc) - last_success_dt).total_seconds() / 3600

    metrics_snapshot = {
        "success_rate": success_rate,
        "stale_hours": stale_hours,
        "consecutive_failures": consecutive_failures,
        "last_status_code": last_status_code,
        "last_error": last_error,
        "avg_bytes_downloaded": sum(bytes_downloaded) / len(bytes_downloaded) if bytes_downloaded else 0,
        "dedupe_rate": sum(dedupe_rates) / len(dedupe_rates) if dedupe_rates else None,
        "suppression_ratio": suppression_ratio,
        "avg_duration_seconds": sum(fetch_durations) / len(fetch_durations) if fetch_durations else None,
    }
    score_result = compute_health_score(metrics_snapshot, stale_threshold_hours=stale_threshold_hours)
    
    return {
        "last_success_utc": last_success_utc,
        "last_failure_utc": last_failure_utc,
        "success_rate": success_rate,
        "last_status_code": last_status_code,
        "last_error": last_error,
        "last_items_fetched": last_items_fetched,
        "last_items_new": last_items_new,
        "last_ingest": last_ingest,
        "suppression_ratio": suppression_ratio,
        "stale_hours": stale_hours,
        "consecutive_failures": consecutive_failures,
        "avg_bytes_downloaded": metrics_snapshot["avg_bytes_downloaded"],
        "dedupe_rate": metrics_snapshot["dedupe_rate"],
        "avg_duration_seconds": metrics_snapshot["avg_duration_seconds"],
        "health_score": score_result.score,
        "health_budget_state": score_result.budget_state,
        "health_factors": score_result.factors,
    }


def get_all_source_health(
    session: Session,
    lookback_n: int = 10,
    stale_threshold_hours: int = 48,
    source_ids: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Get health metrics for all sources.
    
    Args:
        session: SQLAlchemy session
        lookback_n: Number of recent FETCH runs to consider for success rate
        
    Returns:
        List of health dicts, one per source_id
    """
    # Determine which sources to include
    if source_ids is None:
        source_rows = session.query(SourceRun.source_id).distinct().all()
        source_ids = [row[0] for row in source_rows]
    
    # Get health for each source
    health_list = []
    for source_id in source_ids:
        health = get_source_health(
            session,
            source_id,
            lookback_n=lookback_n,
            stale_threshold_hours=stale_threshold_hours,
        )
        health["source_id"] = source_id
        health_list.append(health)
    
    return health_list

