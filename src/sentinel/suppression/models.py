"""Pydantic models for suppression rules and results."""

from typing import List, Optional

from pydantic import BaseModel, Field


class SuppressionRule(BaseModel):
    """A suppression rule that can match items to suppress."""
    
    id: str = Field(..., description="Unique rule identifier")
    enabled: bool = Field(default=True, description="Whether this rule is active")
    kind: str = Field(..., description="Match kind: keyword, regex, or exact")
    field: str = Field(..., description="Field to match: title, summary, raw_text, url, event_type, source_id, tier, or any")
    pattern: str = Field(..., description="Pattern to match against")
    case_sensitive: bool = Field(default=False, description="Whether matching is case-sensitive")
    note: Optional[str] = Field(default=None, description="Optional human-readable note")
    reason_code: Optional[str] = Field(default=None, description="Short code for reporting (defaults to id)")
    
    def get_reason_code(self) -> str:
        """Get the reason code, defaulting to id if not set."""
        return self.reason_code or self.id


class SuppressionResult(BaseModel):
    """Result of suppression evaluation."""
    
    is_suppressed: bool = Field(..., description="Whether the item was suppressed")
    primary_rule_id: Optional[str] = Field(default=None, description="First matching rule ID (deterministic)")
    matched_rule_ids: List[str] = Field(default_factory=list, description="All matching rule IDs")
    notes: List[str] = Field(default_factory=list, description="Optional human-readable notes from matched rules")

