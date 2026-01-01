# Brief v2 / export bundle schema (draft P3 target)

This spec defines the reporting/export envelope for P3. It extends `brief.v1` with explicit evidence, suppression, and provenance fields so integrations can consume artifacts without DB reads.

## Brief JSON (brief.v2)

- `read_model_version`: `brief.v2`
- `generated_at_utc`: ISO 8601 with `Z`
- `window`: `{ since: "24h"|"72h"|"168h", since_hours: int }`
- `counts`: `new`, `updated`, `impactful`, `relevant`, `interesting`
- `tier_counts`: counts by `global|regional|local|unknown`
- `top`: list of alerts (see Alert shape) limited to class 2, sorted by impact
- `updated`: list of alerts where `correlation.action == "UPDATED"` (limit applied)
- `created`: list of alerts where `correlation.action == "CREATED"` (limit applied)
- `suppressed`: `{ count: int, by_rule: [{rule_id, count}], by_source: [{source_id, count}] }`
- `suppressed_legacy`: `{ total_queried: int, limit_applied: int }` (compat)

### Alert shape (brief/export)
- `alert_id`
- `risk_type`
- `classification` (0/1/2)
- `impact_score` (int) and `trust_tier` (1–3) plus `tier` (global/regional/local/None)
- `summary`
- `correlation`: `{ key, action ("CREATED"|"UPDATED"), alert_id }`
- `scope`: `{ facilities: [id], lanes: [id], shipments: [id], shipments_total_linked: int, shipments_truncated: bool }`
- `first_seen_utc`, `last_seen_utc`
- `update_count`
- `evidence_summary`: `{ merge_summary: [str], artifact_hash: str | None }`
- `provenance` (export-only): `{ root_event_count, root_event_ids? }`

## Export bundle (JSON)

Rendered from the same read model, enriched with provenance for downstream systems:
- `brief`: full brief.v2 payload
- `alerts`: array of alerts with `provenance` + optional `incident_evidence` snippet:
  - `incident_evidence`: `{ artifact_hash, overlap: {facilities, lanes}, merge_reasons: [code/message], generated_at_utc }`
- `source_health`: optional passthrough of `sources_api.get_sources_health` for dashboards
- `metadata`: `{ version: "brief-export.v1", generated_at_utc, run_id?, run_group_id? }`

## CSV exports (optional)

If a CSV companion is emitted, include columns:
- `alert_id, correlation_key, correlation_action, tier, trust_tier, classification, impact_score, summary, facilities, lanes, shipments, merge_summary, artifact_hash, first_seen_utc, last_seen_utc, update_count, source_id?, risk_type?`
- Use `|`-delimited lists for scope arrays; preserve deterministic ordering.

## Determinism and hashing
- Brief/export payloads must be generated from canonical API output (`brief_api.get_brief`) without additional re-sorting.
- `artifact_hash` references `incident-evidence.v1` payloads (see `output/incidents/evidence.py` and `docs/ARCHITECTURE.md`).
- Bundle filenames should allow pinning via `filename_basename` to avoid timestamp drift in CI snapshots.

## Compatibility
- `brief.v1` remains supported; `v2` adds `provenance` in exports and clarifies evidence/suppression fields.
- Renderers must tolerate missing `trust_tier` and `tier` values (display “Unknown”).
