# API Layer Rules

This module is the **canonical query/transform surface** for Hardstop data.

## Rules

1. **No SQLAlchemy imports** - API functions call repo functions only
2. **No sorting/filtering unless presentation shaping** - Repos handle query logic
3. **Return Pydantic models or composition wrappers** - Reuse existing models (HardstopAlert) wherever possible
4. **This is the canonical surface** - All query/transform logic lives here, not in output/ or cli/

## Structure

- `models.py` - Composition DTOs only (AlertDetailDTO, etc.)
- `brief_api.py` - Brief read model (BriefReadModel v1)
- `alerts_api.py` - Alert queries (list_alerts, get_alert_detail)
- `sources_api.py` - Source queries (list_sources, get_sources_health)

## Usage

```python
from hardstop.api.brief_api import get_brief
from hardstop.api.alerts_api import list_alerts, get_alert_detail

# All functions take session and return typed models/dicts
brief = get_brief(session, since="24h", include_class0=False, limit=20)
alerts = list_alerts(session, since="24h", classification=2, limit=50)
```

## Surfaces and contracts (P3-ready)

The API functions below are the only supported read surfaces for P3 reporting and integrations.

### `brief_api.get_brief`
- Returns **BriefReadModel v1** dicts shaped for markdown/JSON briefs.
- Keys:
  - `read_model_version`: `brief.v1`
  - `generated_at_utc`: ISO 8601 with `Z`
  - `window`: `{since: "24h"|"72h"|"168h", since_hours: int}`
  - `counts`: `new`, `updated`, plus `impactful`(2)/`relevant`(1)/`interesting`(0)
  - `tier_counts`: counts by `global|regional|local|unknown`
  - `top`: up to 2 class-2 alerts sorted by impact; includes tier/trust_tier, scope, correlation, evidence summary
  - `updated` / `created`: lists keyed by `correlation.action` (`UPDATED` vs `CREATED`) preserving repo order and limited by `limit`
  - `suppressed`: `count`, `by_rule` (top 5), `by_source` (top 5)
  - `suppressed_legacy`: backward-compatible totals
- Deterministic presentation shaping (sorting is explicit where used). Consumers should **not** resort or mutate before rendering.
- Deprecation: `output/daily_brief.generate_brief` is a legacy wrapper around this function. New callers must import `api.brief_api.get_brief` directly.

### `alerts_api.list_alerts`
- Returns a list of `HardstopAlert` Pydantic models.
- Inputs: optional `since` window, `classification`, `tier`, `source_id`, `limit`, `offset`.
- Outputs include correlation info (`correlation.key/action/alert_id`), scope (facilities/lanes/shipments), impact score diagnostics (if present), recommended actions, and optional incident evidence summary when available.
- Sorting and primary filtering are handled by `alert_repo.query_recent_alerts`; API filters only refine the in-memory result.

### `alerts_api.get_alert_detail`
- Returns an `AlertDetailDTO` composed of:
  - `alert`: `HardstopAlert`
  - `provenance`: `AlertProvenance` (`root_event_count`, optional `root_event_ids`, `first_seen_source_id`, `first_seen_tier`)
  - `current_tier` / `current_source_id`: reflect the last updater
  - `source_runs_summary`: populated when `alert.source_id` is available (latest source health metrics)
- Use when building detail pages or incident exports that need provenance alongside alert fields.

### `sources_api.get_sources_health`
- Returns merged config + DB health dicts for all sources with:
  - `source_id`, `tier`, `enabled`, `type`, `tags`
  - `last_success_utc`, `success_rate`, `last_status_code`, `last_items_new`, `last_ingest`
  - `is_stale` (computed from `stale` threshold), `health_score`, `health_budget_state`, `health_factors`, `suppression_ratio`
- Accepts `lookback` and `stale` windows (supports `Xd`/`Xh`); defaults are tuned for operator dashboards.

## Testing

- Test API functions directly (not through CLI)
- Verify invariants (counts match, ordering rules hold)
- No snapshot tests - test structure, not exact bytes
