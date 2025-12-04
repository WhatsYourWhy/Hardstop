from typing import Dict

from ..utils.id_generator import new_alert_id
from .alert_models import (
    AlertAction,
    AlertImpactAssessment,
    AlertScope,
    SentinelAlert,
)


def build_basic_alert(event: Dict) -> SentinelAlert:
    """
    Build a minimal alert for a single event.

    In v1, this is a simple heuristic placeholder; the agent can refine it later.
    """
    alert_id = new_alert_id()
    root_event_id = event["event_id"]

    summary = event.get("title", "Risk event detected")
    risk_type = event.get("event_type", "GENERAL")
    priority = event.get("severity_guess", 1)

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
        f"Initial severity guess: {priority}",
        "Scope derived from basic entity matching.",
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
        priority=priority,
        status="OPEN",
        summary=summary,
        root_event_id=root_event_id,
        scope=scope,
        impact_assessment=impact_assessment,
        reasoning=reasoning,
        recommended_actions=recommended_actions,
        confidence_score=0.5,
    )

