"""Daily brief generation for Sentinel alerts."""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..database.alert_repo import query_recent_alerts
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


def _infer_correlation_action(alert: Alert) -> str:
    """Infer correlation action from alert status (fallback only).
    
    Prefer using alert.correlation_action if available, as it's a fact
    about ingest time, not a lifecycle state.
    """
    if alert.status == "UPDATED":
        return "UPDATED"
    else:
        return "CREATED"  # OPEN status means it was created


def _load_scope(alert: Alert) -> Dict:
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


def _alert_to_dict(alert: Alert) -> Dict:
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


def generate_brief(
    session: Session,
    since_hours: int = 24,
    include_class0: bool = False,
    limit: int = 20,
) -> Dict:
    """
    Generate daily brief data structure.
    
    Args:
        session: SQLAlchemy session
        since_hours: How many hours back to look
        include_class0: Whether to include classification 0 alerts
        limit: Maximum number of alerts to return
        
    Returns:
        Dict with brief data
    """
    alerts = query_recent_alerts(
        session,
        since_hours=since_hours,
        include_class0=include_class0,
        limit=limit * 2,  # Get more to filter by action
    )
    
    # Convert to dicts
    alert_dicts = [_alert_to_dict(a) for a in alerts]
    
    # Separate by correlation action
    created = [a for a in alert_dicts if a["correlation"]["action"] == "CREATED"]
    updated = [a for a in alert_dicts if a["correlation"]["action"] == "UPDATED"]
    
    # Get top impactful (classification 2, highest impact_score)
    top_impact = [
        a for a in alert_dicts
        if a["classification"] == 2
    ]
    top_impact.sort(key=lambda x: (x["impact_score"] or 0), reverse=True)
    top_impact = top_impact[:2]  # Max 2
    
    # Count by classification
    counts = {
        "impactful": len([a for a in alert_dicts if a["classification"] == 2]),
        "relevant": len([a for a in alert_dicts if a["classification"] == 1]),
        "interesting": len([a for a in alert_dicts if a["classification"] == 0]),
    }
    
    # v0.7: Count by tier (from Alert.tier column)
    tier_counts = {
        "global": len([a for a in alert_dicts if a.get("tier") == "global"]),
        "regional": len([a for a in alert_dicts if a.get("tier") == "regional"]),
        "local": len([a for a in alert_dicts if a.get("tier") == "local"]),
    }
    
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "since": f"{since_hours}h",
        "counts": {
            "new": len(created),
            "updated": len(updated),
            **counts,
        },
        "tier_counts": tier_counts,  # v0.7: tier counts
        "top": top_impact,
        "updated": updated[:limit],
        "created": created[:limit],
        "suppressed": {
            "total_queried": len(alerts),
            "limit_applied": limit,
        },
    }


def render_markdown(brief_data: Dict) -> str:
    """Render brief data as markdown."""
    lines = []
    
    # Header
    since_str = brief_data["since"]
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append(f"# Sentinel Daily Brief — {date_str} (since {since_str})")
    lines.append("")
    
    # Counts
    counts = brief_data["counts"]
    tier_counts = brief_data.get("tier_counts", {"global": 0, "regional": 0, "local": 0})
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **New:** {counts['new']} | **Updated:** {counts['updated']}")
    lines.append(
        f"- **Impactful (2):** {counts['impactful']} | "
        f"**Relevant (1):** {counts['relevant']} | "
        f"**Interesting (0):** {counts['interesting']}"
    )
    lines.append(
        f"- **Tier:** Global {tier_counts['global']} | "
        f"Regional {tier_counts['regional']} | "
        f"Local {tier_counts['local']}"
    )
    lines.append("")
    
    # Quiet Day - check early
    total = counts["new"] + counts["updated"]
    if total == 0:
        lines.append("## Quiet Day")
        lines.append("")
        lines.append("No alerts found for the selected time window.")
        lines.append("")
        lines.append("To generate alerts:")
        lines.append("- Run `sentinel demo` to process events")
        lines.append("- Configure event sources to ingest new events")
        lines.append("")
        return "\n".join(lines)
    
    # Top Impact (v0.7: grouped by tier)
    top = brief_data["top"]
    if top:
        lines.append("## Top Impact")
        lines.append("")
        
        # Group by tier
        top_by_tier = {
            "global": [a for a in top if a.get("tier") == "global"],
            "regional": [a for a in top if a.get("tier") == "regional"],
            "local": [a for a in top if a.get("tier") == "local"],
        }
        
        tier_badges = {"global": "[G]", "regional": "[R]", "local": "[L]"}
        
        for tier_name in ["global", "regional", "local"]:
            tier_alerts = top_by_tier[tier_name]
            if not tier_alerts:
                continue
            
            # Sort within tier: classification DESC, impact_score DESC, update_count DESC, last_seen_utc DESC
            tier_alerts.sort(
                key=lambda x: (
                    x["classification"],
                    x.get("impact_score") or 0,
                    x.get("update_count") or 0,
                    x.get("last_seen_utc") or "",
                ),
                reverse=True,
            )
            
            lines.append(f"### {tier_name.capitalize()}")
            lines.append("")
            for alert in tier_alerts:
                scope = alert["scope"]
                facilities = ", ".join(scope.get("facilities", [])[:3])
                if len(scope.get("facilities", [])) > 3:
                    facilities += f" (+{len(scope.get('facilities', [])) - 3} more)"
                
                lanes = ", ".join(scope.get("lanes", [])[:3])
                if len(scope.get("lanes", [])) > 3:
                    lanes += f" (+{len(scope.get('lanes', [])) - 3} more)"
                
                shipments_shown = len(scope.get("shipments", []))
                shipments_total = scope.get("shipments_total_linked", shipments_shown)
                shipments_str = f"{shipments_shown}/{shipments_total}" if shipments_total > shipments_shown else str(shipments_shown)
                
                badge = tier_badges.get(tier_name, "")
                lines.append(f"- **[{alert['classification']}]{badge}** {alert['summary']}")
                lines.append(f"  - **Key:** {alert['correlation']['key']}")
                if facilities or lanes or shipments_str != "0":
                    scope_parts = []
                    if facilities:
                        scope_parts.append(f"Facilities: {facilities}")
                    if lanes:
                        scope_parts.append(f"Lanes: {lanes}")
                    if shipments_str != "0":
                        scope_parts.append(f"Shipments: {shipments_str}")
                    lines.append(f"  - {' | '.join(scope_parts)}")
                lines.append(
                    f"  - **Last seen:** {alert['last_seen_utc']} | "
                    f"**Updates:** {alert['update_count']}"
                )
                lines.append("")
    
    # Updated Alerts (v0.7: grouped by tier)
    updated = brief_data["updated"]
    if updated:
        lines.append("## Updated Alerts")
        lines.append("")
        
        # Group by tier
        updated_by_tier = {
            "global": [a for a in updated if a.get("tier") == "global"],
            "regional": [a for a in updated if a.get("tier") == "regional"],
            "local": [a for a in updated if a.get("tier") == "local"],
        }
        
        tier_badges = {"global": "[G]", "regional": "[R]", "local": "[L]"}
        
        for tier_name in ["global", "regional", "local"]:
            tier_alerts = updated_by_tier[tier_name]
            if not tier_alerts:
                continue
            
            # Sort within tier: classification DESC, impact_score DESC, update_count DESC, last_seen_utc DESC
            tier_alerts.sort(
                key=lambda x: (
                    x["classification"],
                    x.get("impact_score") or 0,
                    x.get("update_count") or 0,
                    x.get("last_seen_utc") or "",
                ),
                reverse=True,
            )
            
            lines.append(f"### {tier_name.capitalize()}")
            lines.append("")
            for alert in tier_alerts:
                badge = tier_badges.get(tier_name, "")
                lines.append(f"- **[{alert['classification']}]{badge}** {alert['summary']} — Updates: {alert['update_count']}")
            lines.append("")
    
    # New Alerts (v0.7: grouped by tier)
    created = brief_data["created"]
    if created:
        lines.append("## New Alerts")
        lines.append("")
        
        # Group by tier
        created_by_tier = {
            "global": [a for a in created if a.get("tier") == "global"],
            "regional": [a for a in created if a.get("tier") == "regional"],
            "local": [a for a in created if a.get("tier") == "local"],
        }
        
        tier_badges = {"global": "[G]", "regional": "[R]", "local": "[L]"}
        
        for tier_name in ["global", "regional", "local"]:
            tier_alerts = created_by_tier[tier_name]
            if not tier_alerts:
                continue
            
            # Sort within tier: classification DESC, impact_score DESC, update_count DESC, last_seen_utc DESC
            tier_alerts.sort(
                key=lambda x: (
                    x["classification"],
                    x.get("impact_score") or 0,
                    x.get("update_count") or 0,
                    x.get("last_seen_utc") or "",
                ),
                reverse=True,
            )
            
            lines.append(f"### {tier_name.capitalize()}")
            lines.append("")
            for alert in tier_alerts:
                badge = tier_badges.get(tier_name, "")
                lines.append(f"- **[{alert['classification']}]{badge}** {alert['summary']}")
            lines.append("")
    
    return "\n".join(lines)


def render_json(brief_data: Dict) -> str:
    """Render brief data as JSON."""
    return json.dumps(brief_data, indent=2)

