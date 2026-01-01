# Output & rendering layer

Renders briefs and incident evidence artifacts from canonical API/read-model data.

## Responsibilities
- Render daily briefs (markdown/JSON) using `api.brief_api.get_brief` as the canonical data source.
- Manage incident evidence artifacts under `output/incidents/` that explain correlation/merge decisions.

## Stable entry points
- `render_markdown(brief_data)` in `daily_brief.py` for markdown rendering.
- `generate_brief(...)` in `daily_brief.py` is **deprecated** and simply wraps `api.brief_api.get_brief`; new callers must use the API module directly.
- Incident evidence helpers in `incidents/evidence.py` to build and load merge artifacts used by briefs and alert evidence summaries.

## Contracts
- **Inputs:** Brief read-model dicts (`brief.v1`) from `api.brief_api`; incident artifacts built via `build_incident_evidence_artifact`.
- **Outputs:** Markdown/JSON strings for briefs; incident evidence artifacts with deterministic hashes.
- **Determinism:** Rendering order is explicit (tier grouping, impact sorting); artifact hashing uses canonical dumps for replayability.

## P3 readiness notes
- Briefs must display tier/trust tier, suppression rollups, and evidence summaries (merge summaries or artifact hashes).
- Plan to archive `generate_brief` once downstream callers migrate; keep deprecation notice in place until removed.
- Future exports (Slack/Linear/JSON bundles) should consume the same `brief.v1` shape to keep reporting surfaces consistent.
