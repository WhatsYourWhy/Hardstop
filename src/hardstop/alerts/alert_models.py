from typing import List, Optional

from pydantic import BaseModel, computed_field


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


class AlertDiagnostics(BaseModel):
    """Diagnostic information for alert audit and debugging.
    
    This is non-decisional evidence - it explains how the system arrived at
    its decisions but does not itself constitute a decision.
    """
    link_confidence: dict[str, float] = {}
    link_provenance: dict[str, str] = {}
    shipments_total_linked: int = 0
    shipments_truncated: bool = False
    impact_score: int = 0
    impact_score_breakdown: list[str] = []


class AlertEvidence(BaseModel):
    """Non-decisional evidence that supports alert decisions.
    
    This contains what the system believes (diagnostics, linking notes, etc.)
    but is separate from what the system asserts (classification, summary, scope).
    
    When LLM reasoning is added later, it will go here as evidence, not as decisions.
    """
    diagnostics: Optional[AlertDiagnostics] = None
    linking_notes: list[str] = []  # Human-readable notes from entity linking process
    correlation: Optional[dict[str, str | int | None]] = None  # Structured correlation info
    # Format: {"key": str, "action": "CREATED" | "UPDATED" | None, "alert_id": str | None}
    # When session is None, action and alert_id are None (key is always computed)
    source: Optional[dict[str, str | int | None]] = None  # Source metadata for external events (v0.7)
    # Format: {"id": str, "tier": str, "raw_id": str, "url": str | None, "trust_tier": int | None}


class HardstopAlert(BaseModel):
    """Structured risk alert with clear decision/evidence boundary.
    
    Decisions (what system asserts):
    - classification: Risk tier (0=Interesting, 1=Relevant, 2=Impactful)
    - summary: Alert summary
    - scope: Affected entities
    - recommended_actions: What to do
    
    Evidence (what system believes, but doesn't decide):
    - evidence: Non-decisional support data (diagnostics, linking notes, etc.)
    """
    alert_id: str
    risk_type: str
    classification: int  # 0=Interesting, 1=Relevant, 2=Impactful (canonical field)
    status: str
    summary: str
    root_event_id: str
    scope: AlertScope
    impact_assessment: AlertImpactAssessment
    reasoning: list[str]  # System's explanation (decision artifact)
    recommended_actions: List[AlertAction]
    model_version: str = "hardstop-v1"
    confidence_score: Optional[float] = None
    evidence: Optional[AlertEvidence] = None  # Non-decisional evidence
    
    # Backward compatibility: priority mirrors classification
    # DEPRECATED: Use classification instead. This field will be removed in v0.4.
    @computed_field
    @property
    def priority(self) -> int:
        """
        Deprecated: Use classification instead.
        
        Returns classification value for backward compatibility.
        This field mirrors classification and will be removed in v0.4.
        """
        return self.classification
    
    # Backward compatibility: diagnostics mirrors evidence.diagnostics
    # DEPRECATED: Use evidence.diagnostics instead. This field will be removed in v0.4.
    @computed_field
    @property
    def diagnostics(self) -> Optional[AlertDiagnostics]:
        """
        Deprecated: Use evidence.diagnostics instead.
        
        Returns evidence.diagnostics for backward compatibility.
        This field will be removed in v0.4.
        """
        if self.evidence and self.evidence.diagnostics:
            return self.evidence.diagnostics
        return None

