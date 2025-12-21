"""Sources API: canonical query surface for source data."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..config.loader import get_all_sources, load_sources_config
from ..database.source_run_repo import get_all_source_health, get_source_health
from .models import SourceRunsSummary


def list_sources(config: Optional[Dict] = None) -> List[Dict]:
    """
    List all configured sources.
    
    Args:
        config: Optional sources config dict. If None, loads from default path.
        
    Returns:
        List of source dictionaries with id, tier, enabled, type, tags, etc.
    """
    return get_all_sources(config)


def get_sources_health(
    session: Session,
    config: Optional[Dict] = None,
    lookback: str = "7d",
    stale: str = "72h",
) -> List[Dict]:
    """
    Get health metrics for all sources, merged with config data.
    
    Args:
        session: SQLAlchemy session
        config: Optional sources config dict. If None, loads from default path.
        lookback: Lookback window for success rate (e.g., "7d", "10")
        stale: Stale threshold (e.g., "72h", "48h")
        
    Returns:
        List of health dicts with:
        - source_id
        - tier (from config)
        - enabled (from config)
        - last_success_utc
        - success_rate
        - last_status_code
        - last_items_new
        - last_ingest (dict with processed/suppressed/events/alerts)
        - is_stale (bool)
    """
    # Parse lookback (if it's a number, use as lookback_n; if it's "7d", parse to days)
    lookback_n = 10  # default
    if lookback:
        lookback_str = lookback.lower().strip()
        if lookback_str.endswith("d"):
            lookback_n = int(lookback_str[:-1]) * 2  # Rough estimate: 2 runs per day
        elif lookback_str.isdigit():
            lookback_n = int(lookback_str)
    
    # Parse stale threshold
    stale_hours = 72  # default
    if stale:
        stale_str = stale.lower().strip()
        if stale_str.endswith("h"):
            stale_hours = int(stale_str[:-1])
        elif stale_str.endswith("d"):
            stale_hours = int(stale_str[:-1]) * 24
    
    # Get health from database
    health_list = get_all_source_health(session, lookback_n=lookback_n)
    
    # Get source configs for tier/enabled info
    sources_config = load_sources_config() if config is None else config
    all_sources = {s["id"]: s for s in get_all_sources(sources_config)}
    
    # Merge health with config
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
    stale_cutoff_iso = stale_cutoff.isoformat()
    
    merged = []
    for health in health_list:
        source_id = health.get("source_id")
        source_config = all_sources.get(source_id, {})
        
        # Check if stale
        last_success = health.get("last_success_utc")
        is_stale = not last_success or last_success < stale_cutoff_iso
        
        merged.append({
            "source_id": source_id,
            "tier": source_config.get("tier", "unknown"),
            "enabled": source_config.get("enabled", True),
            "type": source_config.get("type", "unknown"),
            "tags": source_config.get("tags", []),
            "last_success_utc": last_success,
            "success_rate": health.get("success_rate", 0.0),
            "last_status_code": health.get("last_status_code"),
            "last_items_new": health.get("last_items_new", 0),
            "last_ingest": health.get("last_ingest"),
            "is_stale": is_stale,
        })
    
    return merged


def get_source_health_detail(
    session: Session,
    source_id: str,
    lookback: str = "7d",
) -> Optional[SourceRunsSummary]:
    """
    Get detailed health for a single source.
    
    Args:
        session: SQLAlchemy session
        source_id: Source ID
        lookback: Lookback window (e.g., "7d", "10")
        
    Returns:
        SourceRunsSummary or None if not found
    """
    # Parse lookback
    lookback_n = 10  # default
    if lookback:
        lookback_str = lookback.lower().strip()
        if lookback_str.endswith("d"):
            lookback_n = int(lookback_str[:-1]) * 2  # Rough estimate
        elif lookback_str.isdigit():
            lookback_n = int(lookback_str)
    
    health = get_source_health(session, source_id, lookback_n=lookback_n)
    if not health:
        return None
    
    return SourceRunsSummary(
        source_id=source_id,
        last_success_utc=health.get("last_success_utc"),
        success_rate=health.get("success_rate", 0.0),
        last_status_code=health.get("last_status_code"),
        last_items_new=health.get("last_items_new", 0),
        last_ingest=health.get("last_ingest"),
    )

