"""Brief read model API (BriefReadModel v1).

This is the canonical query/transform surface for brief data.
All query logic lives here - output/daily_brief.py is renderer-only.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict

from sqlalchemy.orm import Session

from ..database.alert_repo import query_recent_alerts
from ..database.raw_item_repo import query_suppressed_items
from ..utils.time import utc_now_z

if TYPE_CHECKING:
    from ..database.schema import Alert


def _parse_since(since_str: str) -> int:
    """Parse --since argument (24h, 72h, 7d) to hours."""
    since_str = since_str.lower().strip()
    if since_str.endswith("h"):
        return int(since_str[:-1])
    elif since_str.endswith("d"):
        return int(since_str[:-1]) * 24
    else:
        raise ValueError(f"Invalid --since format: {since_str}. Use 24h, 72h, or 7d")


def _infer_correlation_action(alert: "Alert") -> str:
    """Infer correlation action from alert status (fallback only).
    
    Prefer using alert.correlation_action if available, as it's a fact
    about ingest time, not a lifecycle state.
    """
    if alert.status == "UPDATED":
        return "UPDATED"
    else:
        return "CREATED"  # OPEN status means it was created


def _load_scope(alert: "Alert") -> Dict:
    """Load scope from JSON or return empty dict."""
    if not alert.scope_json:
        return {
            "facilities": [],
            "lanes": [],
            "shipments": [],
            "shipments_total_linked": 0,
            "shipments_truncated": False,
        }
    try:
        return json.loads(alert.scope_json)
    except (json.JSONDecodeError, TypeError):
        return {
            "facilities": [],
            "lanes": [],
            "shipments": [],
            "shipments_total_linked": 0,
            "shipments_truncated": False,
        }


def _alert_to_dict(alert: "Alert") -> Dict:
    """Convert Alert row to dict for brief output (v0.7: includes tier and trust_tier)."""
    scope = _load_scope(alert)
    
    return {
        "alert_id": alert.alert_id,
        "classification": alert.classification,
        "impact_score": alert.impact_score,
        "summary": alert.summary,
        "correlation": {
            "key": alert.correlation_key or "",
            "action": alert.correlation_action or _infer_correlation_action(alert),  # Prefer stored fact
            "alert_id": alert.alert_id,
        },
        "scope": scope,
        "first_seen_utc": alert.first_seen_utc,
        "last_seen_utc": alert.last_seen_utc,
        "update_count": alert.update_count or 0,
        "tier": alert.tier,  # v0.7: tier for grouping
        "trust_tier": alert.trust_tier,  # v0.7: trust tier
    }


def get_brief(
    session: Session,
    since: str,  # "24h", "72h", "7d"
    include_class0: bool = False,
    limit: int = 20,
) -> Dict:
    """
    Generate brief read model (BriefReadModel v1).
    
    This is the canonical query/transform surface for brief data.
    All query logic lives here - repos handle DB queries, this handles shaping.
    
    Args:
        session: SQLAlchemy session
        since: Time window string (24h, 72h, 7d)
        include_class0: Whether to include classification 0 alerts
        limit: Maximum number of alerts per section
        
    Returns:
        BriefReadModel v1 dict with structure:
        {
            "read_model_version": "brief.v1",
            "generated_at_utc": "ISO 8601 UTC with Z suffix",
            "window": {"since": "24h", "since_hours": 24},
            "counts": {
                "new": int,
                "updated": int,
                "impactful": int,
                "relevant": int,
                "interesting": int
            },
            "tier_counts": {
                "global": int,
                "regional": int,
                "local": int,
                "unknown": int
            },
            "top": [alert_dict, ...],  # Max 2, sorted by impact_score DESC
            "updated": [alert_dict, ...],  # Limited by limit param, preserves repo order
            "created": [alert_dict, ...],  # Limited by limit param, preserves repo order
            "suppressed": {
                "count": int,
                "by_rule": [{"rule_id": str, "count": int}, ...],  # Top 5, sorted DESC
                "by_source": [{"source_id": str, "count": int}, ...]  # Top 5, sorted DESC
            },
            "suppressed_legacy": {
                "total_queried": int,
                "limit_applied": int
            },
        }
        
    Note on ordering:
    - Repo order is preserved for `created` and `updated` lists (repo sorts by classification DESC, impact_score DESC, etc.)
    - Only `top` is re-sorted by impact_score DESC (intentional presentation shaping)
    - `tier_counts` dict iteration order is stable (Python 3.7+ dict order is insertion-order)
    - Suppression rollups are explicitly sorted before limiting to top 5
    """
    # Parse since string
    since_hours = _parse_since(since)
    
    # Query alerts (repo handles sorting - canonical order)
    alerts = query_recent_alerts(
        session,
        since_hours=since_hours,
        include_class0=include_class0,
        limit=limit * 2,  # Get more to filter by action
    )
    
    # Convert to dicts (transform layer)
    alert_dicts = [_alert_to_dict(a) for a in alerts]
    
    # Separate by correlation action (presentation shaping)
    created = [a for a in alert_dicts if a["correlation"]["action"] == "CREATED"]
    updated = [a for a in alert_dicts if a["correlation"]["action"] == "UPDATED"]
    
    # Get top impactful (presentation shaping)
    top_impact = [
        a for a in alert_dicts
        if a["classification"] == 2
    ]
    top_impact.sort(key=lambda x: (x["impact_score"] or 0), reverse=True)
    top_impact = top_impact[:2]  # Max 2
    
    # Count by classification (presentation shaping)
    counts = {
        "impactful": len([a for a in alert_dicts if a["classification"] == 2]),
        "relevant": len([a for a in alert_dicts if a["classification"] == 1]),
        "interesting": len([a for a in alert_dicts if a["classification"] == 0]),
    }
    
    # Count by tier (presentation shaping)
    tier_counts = {
        "global": len([a for a in alert_dicts if a.get("tier") == "global"]),
        "regional": len([a for a in alert_dicts if a.get("tier") == "regional"]),
        "local": len([a for a in alert_dicts if a.get("tier") == "local"]),
        "unknown": len([a for a in alert_dicts if a.get("tier") is None]),  # Handle None tier
    }
    
    # Query suppressed items (via repo)
    suppressed_items = query_suppressed_items(session, since_hours=since_hours)
    suppressed_count = len(suppressed_items)
    
    # Aggregate suppressed (presentation shaping)
    suppressed_by_rule: Dict[str, int] = {}
    suppressed_by_source: Dict[str, int] = {}
    for item in suppressed_items:
        if item.suppression_primary_rule_id:
            suppressed_by_rule[item.suppression_primary_rule_id] = suppressed_by_rule.get(item.suppression_primary_rule_id, 0) + 1
        if item.source_id:
            suppressed_by_source[item.source_id] = suppressed_by_source.get(item.source_id, 0) + 1
    
    # Sort and take top 5 (explicit sorting for deterministic JSON)
    suppressed_by_rule_list = [
        {"rule_id": rule_id, "count": count}
        for rule_id, count in sorted(suppressed_by_rule.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    suppressed_by_source_list = [
        {"source_id": source_id, "count": count}
        for source_id, count in sorted(suppressed_by_source.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    
    # Return BriefReadModel v1
    return {
        "read_model_version": "brief.v1",
        "generated_at_utc": utc_now_z(),
        "window": {
            "since": f"{since_hours}h",
            "since_hours": since_hours,
        },
        "counts": {
            "new": len(created),
            "updated": len(updated),
            **counts,
        },
        "tier_counts": tier_counts,
        "top": top_impact,
        "updated": updated[:limit],
        "created": created[:limit],
        "suppressed": {
            "count": suppressed_count,
            "by_rule": suppressed_by_rule_list,
            "by_source": suppressed_by_source_list,
        },
        "suppressed_legacy": {  # Keep for backward compatibility
            "total_queried": len(alerts),
            "limit_applied": limit,
        },
    }

