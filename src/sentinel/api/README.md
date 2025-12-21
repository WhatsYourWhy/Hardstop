# API Layer Rules

This module is the **canonical query/transform surface** for Sentinel data.

## Rules

1. **No SQLAlchemy imports** - API functions call repo functions only
2. **No sorting/filtering unless presentation shaping** - Repos handle query logic
3. **Return Pydantic models or composition wrappers** - Reuse existing models (SentinelAlert) wherever possible
4. **This is the canonical surface** - All query/transform logic lives here, not in output/ or cli/

## Structure

- `models.py` - Composition DTOs only (AlertDetailDTO, etc.)
- `brief_api.py` - Brief read model (BriefReadModel v1)
- `alerts_api.py` - Alert queries (list_alerts, get_alert_detail)
- `sources_api.py` - Source queries (list_sources, get_sources_health)

## Usage

```python
from sentinel.api.brief_api import get_brief
from sentinel.api.alerts_api import list_alerts, get_alert_detail

# All functions take session and return typed models/dicts
brief = get_brief(session, since="24h", include_class0=False, limit=20)
alerts = list_alerts(session, since="24h", classification=2, limit=50)
```

## Testing

- Test API functions directly (not through CLI)
- Verify invariants (counts match, ordering rules hold)
- No snapshot tests - test structure, not exact bytes

