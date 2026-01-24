# Export bundle schema (v1)

This document describes the export surfaces implemented in `src/hardstop/api/export.py` and exposed via the `hardstop export` CLI.
The export API is read-only and emits deterministic bundles with optional manifests when an output path is provided.

## Common envelope

All JSON exports share the same top-level envelope:

```json
{
  "export_schema_version": "1",
  "exported_at_utc": "2025-01-01T00:00:00Z",
  "data": {}
}
```

- `export_schema_version`: Schema version (string, currently `"1"`).
- `exported_at_utc`: UTC timestamp for the export run (RFC3339 with `Z`).
- `data`: The payload specific to the export type.

## Brief export (`hardstop export brief`)

JSON-only export of the daily brief read model.

```json
{
  "export_schema_version": "1",
  "exported_at_utc": "2025-01-01T00:00:00Z",
  "data": {
    "read_model_version": "brief.v1",
    "generated_at_utc": "2025-01-01T00:00:00Z",
    "window": {"since": "24h"},
    "counts": {},
    "tier_counts": {},
    "top": [],
    "updated": [],
    "created": [],
    "suppressed": [],
    "suppressed_legacy": []
  }
}
```

The `data` payload mirrors the output of `hardstop.api.brief_api.get_brief` (brief v1).
For exports, `generated_at_utc` is normalized to the most recent alert timestamp
(preferring `last_seen_utc`, then `first_seen_utc`) when available so that bundles
remain deterministic across identical inputs.

## Alerts export (`hardstop export alerts`)

### JSON format

JSON export includes a list of `HardstopAlert` models serialized with `.model_dump()`.
The alert schema follows `src/hardstop/alerts/alert_models.py`.

```json
{
  "export_schema_version": "1",
  "exported_at_utc": "2025-01-01T00:00:00Z",
  "data": [
    {
      "alert_id": "ALERT-...",
      "risk_type": "...",
      "classification": 2,
      "status": "OPEN",
      "summary": "...",
      "root_event_id": "EVT-...",
      "scope": {"facilities": [], "lanes": [], "shipments": []},
      "impact_assessment": {"qualitative_impact": []},
      "reasoning": [],
      "recommended_actions": [],
      "model_version": "hardstop-v1",
      "confidence_score": null,
      "evidence": {
        "diagnostics": {"impact_score": 5, "impact_score_breakdown": []},
        "linking_notes": [],
        "correlation": {"key": "...", "action": "CREATED", "alert_id": "ALERT-..."},
        "incident_evidence": {
          "artifact_hash": "...",
          "merge_summary": [],
          "root_event_ids": []
        }
      }
    }
  ]
}
```

### CSV format

CSV exports are flat and use a stable column order. The header row is:

```
alert_id,classification,impact_score,tier,trust_tier,source_id,correlation_action,update_count,first_seen_utc,last_seen_utc,summary
```

- `impact_score` comes from alert diagnostics when present, otherwise the persisted DB value.
- `correlation_action` is inferred from alert evidence or persisted correlation metadata.

## Sources export (`hardstop export sources`)

JSON-only export of source health data as returned by `hardstop.api.sources_api.get_sources_health`.

```json
{
  "export_schema_version": "1",
  "exported_at_utc": "2025-01-01T00:00:00Z",
  "data": [
    {
      "source_id": "source-1",
      "tier": "global",
      "enabled": true,
      "type": "rss",
      "tags": [],
      "last_success_utc": "2025-01-01T00:00:00+00:00",
      "success_rate": 1.0,
      "last_status_code": 200,
      "last_items_new": 3,
      "last_ingest": {"processed": 3, "suppressed": 0, "events": 3, "alerts": 1},
      "is_stale": false,
      "health_score": 100,
      "health_budget_state": "HEALTHY",
      "health_factors": [],
      "suppression_ratio": 0.0
    }
  ]
}
```

## Export manifest (`*.manifest.json`)

When `--out` is provided, the export API writes a sidecar manifest file named
`<output>.manifest.json` to support verification and replay.

```json
{
  "manifest_version": "1",
  "export_schema_version": "1",
  "exported_at_utc": "2025-01-01T00:00:00Z",
  "config_hash": "...",
  "export_data_hash": "...",
  "artifact_hashes": ["..."],
  "config_snapshot": {}
}
```

- `config_hash`: Hash of the resolved config snapshot.
- `export_data_hash`: Hash of the exported payload (JSON export) or the CSV manifest metadata,
  computed with `exported_at_utc` removed to keep deterministic manifests.
- `artifact_hashes`: Incident evidence artifact hashes referenced by alerts (if any).
- `config_snapshot`: Full resolved config snapshot for client-side verification.
