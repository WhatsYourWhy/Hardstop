"""Composition DTOs for API layer.

These are thin wrappers that compose existing Pydantic models.
Do not duplicate fields from HardstopAlert - reuse the model directly.
"""

from typing import List, Optional

from pydantic import BaseModel

from ..alerts.alert_models import HardstopAlert


class AlertProvenance(BaseModel):
    """Provenance information for an alert."""
    root_event_count: int
    root_event_ids: Optional[List[str]] = None  # Optional: only if cheap to compute
    first_seen_source_id: Optional[str] = None  # Optional: only if cheap to compute
    first_seen_tier: Optional[str] = None  # Optional: only if cheap to compute


class SourceRunsSummary(BaseModel):
    """Summary of source runs for a source."""
    source_id: str
    last_success_utc: Optional[str] = None
    success_rate: float
    last_status_code: Optional[int] = None
    last_items_new: int = 0
    last_ingest: Optional[dict] = None  # processed/suppressed/events/alerts


class AlertDetailDTO(BaseModel):
    """Composition DTO: alert + related data for detail view."""
    alert: HardstopAlert
    current_tier: Optional[str] = None  # From alert (last updater)
    current_source_id: Optional[str] = None  # From alert (last updater)
    source_runs_summary: Optional[SourceRunsSummary] = None
    provenance: Optional[AlertProvenance] = None

