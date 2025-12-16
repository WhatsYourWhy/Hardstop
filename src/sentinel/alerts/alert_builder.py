from typing import Dict, Optional

from sqlalchemy.orm import Session

from ..utils.id_generator import new_alert_id
from .alert_models import (
    AlertAction,
    AlertDiagnostics,
    AlertImpactAssessment,
    AlertScope,
    SentinelAlert,
)
from .impact_scorer import calculate_network_impact_score, map_score_to_classification


def build_basic_alert(event: Dict, session: Optional[Session] = None) -> SentinelAlert:
    """
    Build a minimal alert for a single event.
    
    Priority is determined by network impact score, not just input severity_guess.
    This makes classification deterministic and testable.

    Args:
        event: Event dict with facilities, lanes, shipments populated
        session: Optional SQLAlchemy session for network impact scoring
                 If None, falls back to severity_guess
    """
    alert_id = new_alert_id()
    root_event_id = event["event_id"]

    summary = event.get("title", "Risk event detected")
    risk_type = event.get("event_type", "GENERAL")
    
    # Calculate classification based on network impact
    diagnostics = None
    if session:
        impact_score, breakdown = calculate_network_impact_score(event, session)
        classification = map_score_to_classification(impact_score)
        classification_source = f"network_impact_score={impact_score}"
        
        # Build diagnostics object
        diagnostics = AlertDiagnostics(
            link_confidence=event.get("link_confidence", {}),
            link_provenance=event.get("link_provenance", {}),
            shipments_total_linked=event.get("shipments_total_linked", len(event.get("shipments", []))),
            shipments_truncated=event.get("shipments_truncated", False),
            impact_score=impact_score,
            impact_score_breakdown=breakdown,
        )
    else:
        # Fallback to severity_guess if no session provided
        classification = event.get("severity_guess", 1)
        classification_source = "severity_guess (no network data)"

    scope = AlertScope(
        facilities=event.get("facilities", []),
        lanes=event.get("lanes", []),
        shipments=event.get("shipments", []),
    )

    impact_assessment = AlertImpactAssessment(
        qualitative_impact=[event.get("raw_text", "")[:280]],
    )

    reasoning = [
        f"Event type: {risk_type}",
        f"Classification: {classification} (from {classification_source})",
        "Scope derived from network entity matching.",
    ]

    recommended_actions = [
        AlertAction(
            id="ACT-VERIFY",
            description="Verify status with responsible operator or facility.",
            owner_role="Operations / Supply Chain",
            due_within_hours=4,
        )
    ]

    return SentinelAlert(
        alert_id=alert_id,
        risk_type=risk_type,
        classification=classification,
        status="OPEN",
        summary=summary,
        root_event_id=root_event_id,
        scope=scope,
        impact_assessment=impact_assessment,
        reasoning=reasoning,
        recommended_actions=recommended_actions,
        confidence_score=0.5,
        diagnostics=diagnostics,
    )

