from typing import List, Optional

from pydantic import BaseModel


class AlertAction(BaseModel):
    id: str
    description: str
    owner_role: str
    due_within_hours: int


class AlertScope(BaseModel):
    facilities: list[str] = []
    lanes: list[str] = []
    shipments: list[str] = []


class AlertImpactAssessment(BaseModel):
    time_risk_days: float | None = None
    revenue_at_risk: float | None = None
    customers_affected: list[str] = []
    qualitative_impact: list[str] = []


class SentinelAlert(BaseModel):
    alert_id: str
    risk_type: str
    priority: int
    status: str
    summary: str
    root_event_id: str
    scope: AlertScope
    impact_assessment: AlertImpactAssessment
    reasoning: list[str]
    recommended_actions: List[AlertAction]
    model_version: str = "sentinel-v1"
    confidence_score: Optional[float] = None

