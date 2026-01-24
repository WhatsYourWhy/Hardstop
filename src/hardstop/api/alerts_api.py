"""Alerts API: canonical query surface for alert data."""

import json
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy.orm import Session

from ..alerts.alert_models import (
    AlertAction,
    AlertDiagnostics,
    AlertEvidence,
    AlertImpactAssessment,
    AlertScope,
    IncidentEvidenceSummary,
    HardstopAlert,
)
from ..database.alert_repo import (
    get_first_seen_provenance,
    load_root_event_ids,
    query_recent_alerts,
)
from ..database.source_run_repo import get_source_health
from ..output.incidents.evidence import load_incident_evidence_summary
from .models import AlertDetailDTO, AlertProvenance, SourceRunsSummary

if TYPE_CHECKING:
    from ..database.schema import Alert


def _alert_row_to_hardstop_alert(alert_row: "Alert") -> HardstopAlert:
    """Convert Alert ORM row to HardstopAlert Pydantic model."""
    # Load scope from JSON
    scope_dict = {}
    if alert_row.scope_json:
        try:
            scope_dict = json.loads(alert_row.scope_json)
        except (json.JSONDecodeError, TypeError):
            scope_dict = {}
    
    scope = AlertScope(
        facilities=scope_dict.get("facilities", []),
        lanes=scope_dict.get("lanes", []),
        shipments=scope_dict.get("shipments", []),
    )
    
    # Load impact assessment (minimal - stored in scope_json for now)
    impact_assessment = AlertImpactAssessment(
        qualitative_impact=[],
    )
    
    # Load reasoning
    reasoning = []
    if alert_row.reasoning:
        reasoning = [line.strip() for line in alert_row.reasoning.split("\n") if line.strip()]
    
    # Load recommended actions
    recommended_actions = []
    if alert_row.recommended_actions:
        try:
            actions_data = json.loads(alert_row.recommended_actions)
            if isinstance(actions_data, list):
                recommended_actions = [AlertAction(**action) for action in actions_data]
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Build evidence (hydrate diagnostics from stored payload when present)
    diagnostics = None
    if alert_row.diagnostics_json:
        try:
            diagnostics_payload = json.loads(alert_row.diagnostics_json)
            if isinstance(diagnostics_payload, dict):
                diagnostics = AlertDiagnostics(**diagnostics_payload)
        except (json.JSONDecodeError, TypeError):
            diagnostics = None
    if diagnostics is None and alert_row.impact_score is not None:
        diagnostics = AlertDiagnostics(
            impact_score=alert_row.impact_score,
            impact_score_breakdown=[],
        )

    evidence = None
    if diagnostics is not None or alert_row.correlation_key or alert_row.correlation_action:
        evidence = AlertEvidence(
            diagnostics=diagnostics,
            linking_notes=[],
            correlation={
                "key": alert_row.correlation_key or "",
                "action": alert_row.correlation_action or None,
                "alert_id": alert_row.alert_id,
            },
        )
    incident_summary_data = load_incident_evidence_summary(alert_row.alert_id, alert_row.correlation_key or "")
    if incident_summary_data:
        if evidence is None:
            evidence = AlertEvidence(
                diagnostics=None,
                linking_notes=[],
                correlation={
                    "key": alert_row.correlation_key or "",
                    "action": alert_row.correlation_action or None,
                    "alert_id": alert_row.alert_id,
                },
            )
        evidence.incident_evidence = IncidentEvidenceSummary(**incident_summary_data)
    
    return HardstopAlert(
        alert_id=alert_row.alert_id,
        risk_type=alert_row.risk_type,
        classification=alert_row.classification,
        status=alert_row.status,
        summary=alert_row.summary,
        root_event_id=alert_row.root_event_id,
        scope=scope,
        impact_assessment=impact_assessment,
        reasoning=reasoning,
        recommended_actions=recommended_actions,
        model_version="hardstop-v1",
        confidence_score=None,
        evidence=evidence,
    )


def list_alerts(
    session: Session,
    since: Optional[str] = None,
    classification: Optional[int] = None,
    tier: Optional[str] = None,
    source_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[HardstopAlert]:
    """
    List alerts with optional filters.
    
    Args:
        session: SQLAlchemy session
        since: Time window string (24h, 72h, 7d) - if None, no time filter
        classification: Filter by classification (0, 1, 2) - if None, all
        tier: Filter by tier (global, regional, local) - if None, all
        source_id: Filter by source_id - if None, all
        limit: Maximum number of alerts to return
        offset: Number of alerts to skip
        
    Returns:
        List of HardstopAlert models, sorted by canonical order (repo handles sorting)
    """
    # Parse since to hours if provided
    since_hours = None
    if since:
        from .brief_api import _parse_since
        since_hours = _parse_since(since)
    
    # Query alerts (repo handles sorting - canonical order)
    alerts = query_recent_alerts(
        session,
        since_hours=since_hours or 24 * 365,  # If no since, use 1 year as default
        include_class0=classification is None or classification == 0,
        limit=limit + offset,  # Get more to apply offset
    )
    
    # Apply filters that repo doesn't handle
    filtered = alerts
    if classification is not None:
        filtered = [a for a in filtered if a.classification == classification]
    if tier is not None:
        filtered = [a for a in filtered if a.tier == tier]
    if source_id is not None:
        filtered = [a for a in filtered if a.source_id == source_id]
    
    # Apply offset and limit
    filtered = filtered[offset:offset + limit]
    
    # Convert to HardstopAlert models
    return [_alert_row_to_hardstop_alert(a) for a in filtered]


def get_alert_detail(
    session: Session,
    alert_id: str,
) -> Optional[AlertDetailDTO]:
    """
    Get alert detail with provenance and source runs summary.
    
    Args:
        session: SQLAlchemy session
        alert_id: Alert ID
        
    Returns:
        AlertDetailDTO or None if not found
    """
    # Use repo function for query (canonical surface rule)
    from ..database.alert_repo import find_alert_by_id
    
    alert_row = find_alert_by_id(session, alert_id)
    if not alert_row:
        return None
    
    # Convert to HardstopAlert
    alert = _alert_row_to_hardstop_alert(alert_row)
    
    # Build provenance (minimal - only root_event_count for now)
    root_event_ids = load_root_event_ids(alert_row)
    first_seen_source_id, first_seen_tier = get_first_seen_provenance(session, alert_row)
    provenance = AlertProvenance(
        root_event_count=len(root_event_ids),
        root_event_ids=root_event_ids if len(root_event_ids) <= 10 else None,  # Only include if small
        first_seen_source_id=first_seen_source_id,
        first_seen_tier=first_seen_tier,
    )
    
    source_runs_summary = None
    if alert_row.source_id:
        health = get_source_health(session, alert_row.source_id)
        source_runs_summary = SourceRunsSummary(
            source_id=alert_row.source_id,
            last_success_utc=health.get("last_success_utc"),
            success_rate=health.get("success_rate", 0.0),
            last_status_code=health.get("last_status_code"),
            last_items_new=health.get("last_items_new", 0),
            last_ingest=health.get("last_ingest"),
        )
    
    return AlertDetailDTO(
        alert=alert,
        current_tier=alert_row.tier,
        current_source_id=alert_row.source_id,
        source_runs_summary=source_runs_summary,
        provenance=provenance,
    )
