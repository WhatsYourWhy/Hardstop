"""Daily brief rendering (markdown and JSON).

This module is renderer-only. All query/transform logic lives in api/brief_api.py.
"""

import json
from datetime import datetime, timezone
from typing import Dict

from sqlalchemy.orm import Session

from ..api.brief_api import get_brief


def generate_brief(
    session: Session,
    since_hours: int = 24,
    include_class0: bool = False,
    limit: int = 20,
) -> Dict:
    """
    Generate daily brief data structure.
    
    DEPRECATED: This is a compatibility wrapper. New code should use
    api.brief_api.get_brief() directly.
    
    This function calls the canonical API surface and converts since_hours
    to since string for backward compatibility.
    
    Args:
        session: SQLAlchemy session
        since_hours: How many hours back to look
        include_class0: Whether to include classification 0 alerts
        limit: Maximum number of alerts to return
        
    Returns:
        Dict with brief data (BriefReadModel v1 format)
    """
    since_str = f"{since_hours}h"
    return get_brief(session, since=since_str, include_class0=include_class0, limit=limit)


def render_markdown(brief_data: Dict) -> str:
    """Render brief data as markdown."""
    lines = []
    
    # Header
    # Support both old format (since) and new format (window.since)
    # TODO(v1.2): Remove legacy dict support (since key). Use window.since only.
    if "window" in brief_data:
        since_str = brief_data["window"]["since"]
    else:
        since_str = brief_data.get("since", "24h")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append(f"# Hardstop Daily Brief — {date_str} (since {since_str})")
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
    tier_summary_parts = []
    if tier_counts['global'] > 0:
        tier_summary_parts.append(f"Global {tier_counts['global']}")
    if tier_counts['regional'] > 0:
        tier_summary_parts.append(f"Regional {tier_counts['regional']}")
    if tier_counts['local'] > 0:
        tier_summary_parts.append(f"Local {tier_counts['local']}")
    if tier_counts['unknown'] > 0:
        tier_summary_parts.append(f"Unknown {tier_counts['unknown']}")
    
    if tier_summary_parts:
        lines.append(f"- **Tier:** {' | '.join(tier_summary_parts)}")
    else:
        lines.append("- **Tier:** None")
    
    # v0.8: Suppressed count
    suppressed = brief_data.get("suppressed", {})
    suppressed_count = suppressed.get("count", 0)
    if suppressed_count > 0:
        suppressed_by_rule = suppressed.get("by_rule", [])
        if suppressed_by_rule:
            top_rules = ", ".join([f"{r['rule_id']}={r['count']}" for r in suppressed_by_rule[:3]])
            lines.append(f"- **Suppressed:** {suppressed_count} (top: {top_rules})")
        else:
            lines.append(f"- **Suppressed:** {suppressed_count}")
    lines.append("")
    
    # Quiet Day - check early
    total = counts["new"] + counts["updated"]
    if total == 0:
        lines.append("## Quiet Day")
        lines.append("")
        lines.append("No alerts found for the selected time window.")
        lines.append("")
        lines.append("To generate alerts:")
        lines.append("- Run `hardstop demo` to process events")
        lines.append("- Configure event sources to ingest new events")
        lines.append("")
        return "\n".join(lines)
    
    # Top Impact (v0.7: grouped by tier)
    top = brief_data["top"]
    if top:
        lines.append("## Top Impact")
        lines.append("")
        
        # Group by tier (v0.7: include unknown tier for None values)
        top_by_tier = {
            "global": [a for a in top if a.get("tier") == "global"],
            "regional": [a for a in top if a.get("tier") == "regional"],
            "local": [a for a in top if a.get("tier") == "local"],
            "unknown": [a for a in top if a.get("tier") is None],
        }
        
        tier_badges = {"global": "[G]", "regional": "[R]", "local": "[L]", "unknown": "[?]"}
        
        for tier_name in ["global", "regional", "local", "unknown"]:
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
                trust_tier_val = alert.get('trust_tier')
                trust_suffix = f" (T{trust_tier_val})" if trust_tier_val else ""
                lines.append(f"- **[{alert['classification']}]{badge}** {alert['summary']}{trust_suffix}")
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
        
        # Group by tier (v0.7: include unknown tier for None values)
        updated_by_tier = {
            "global": [a for a in updated if a.get("tier") == "global"],
            "regional": [a for a in updated if a.get("tier") == "regional"],
            "local": [a for a in updated if a.get("tier") == "local"],
            "unknown": [a for a in updated if a.get("tier") is None],
        }
        
        tier_badges = {"global": "[G]", "regional": "[R]", "local": "[L]", "unknown": "[?]"}
        
        for tier_name in ["global", "regional", "local", "unknown"]:
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
                trust_tier_val = alert.get('trust_tier')
                trust_suffix = f" (T{trust_tier_val})" if trust_tier_val else ""
                lines.append(f"- **[{alert['classification']}]{badge}** {alert['summary']}{trust_suffix} — Updates: {alert['update_count']}")
            lines.append("")
    
    # New Alerts (v0.7: grouped by tier)
    created = brief_data["created"]
    if created:
        lines.append("## New Alerts")
        lines.append("")
        
        # Group by tier (v0.7: include unknown tier for None values)
        created_by_tier = {
            "global": [a for a in created if a.get("tier") == "global"],
            "regional": [a for a in created if a.get("tier") == "regional"],
            "local": [a for a in created if a.get("tier") == "local"],
            "unknown": [a for a in created if a.get("tier") is None],
        }
        
        tier_badges = {"global": "[G]", "regional": "[R]", "local": "[L]", "unknown": "[?]"}
        
        for tier_name in ["global", "regional", "local", "unknown"]:
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
                trust_tier_val = alert.get('trust_tier')
                trust_suffix = f" (T{trust_tier_val})" if trust_tier_val else ""
                lines.append(f"- **[{alert['classification']}]{badge}** {alert['summary']}{trust_suffix}")
            lines.append("")
    
    return "\n".join(lines)


def render_json(brief_data: Dict) -> str:
    """Render brief data as JSON."""
    return json.dumps(brief_data, indent=2, sort_keys=True)

