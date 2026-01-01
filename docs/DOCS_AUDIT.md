# Docs audit (Jan 2026)

Scope: `docs/` top-level. Goal: identify what to archive, what to update, and what remains to reach P3 reporting/export parity.

## Current state

- `ARCHITECTURE.md` – up to date for P0–P2. Needs a P3 pass to document brief/export contracts and integration boundaries.
- `EXECUTION_PLAN.md` – P3 section lists workstreams; now includes concrete acceptance criteria for briefs v2/export bundles/Slack+Linear sinks.
- `P2_READINESS.md` – accurate for shipped P2 baseline; keep as-is for maintenance.
- `INTEGRATIONS.md` – updated with Slack/Linear payload templates tied to brief/export fields.
- `specs/` – `canonicalization.md`, `run-record.schema.json`, and new `brief-v2.md` (export/bundle schema) are current.
- `archive/SPEC_HARDSTOP_V1.md` – archived legacy v1 spec (outdated fields: priority, stub brief, v0.4 notes).

## Archive
- `SPEC_HARDSTOP_V1.md` moved to `docs/archive/` as legacy reference; superseded by architecture/spec docs and current API surfaces.

## Updates needed to progress to P3
- Add a brief v2/export schema doc under `docs/specs/` (JSON/CSV bundle shape, evidence summary fields, suppression rollups). **(Done: `docs/specs/brief-v2.md`)**
- Update `ARCHITECTURE.md` + `EXECUTION_PLAN.md` with P3 acceptance criteria (brief v2 rendering, export API/CLI, CI signals). **(Done)**
- Extend `INTEGRATIONS.md` with canonical payload examples for Slack/Linear sinks and guidance to consume exported bundles (not DB). **(Done)**
- Add operational playbooks for P3 (runbooks for blocked sources, replay/export failure handling). **(Done: `docs/runbooks/reporting.md`)**

## Next steps (suggested order)
1) Wire brief v2 renderer/export bundle implementation to match `docs/specs/brief-v2.md`.
2) Add CI fixtures/snapshots for brief/export payloads (cover evidence hashes, suppression rollups, trust tiers).
3) Publish the GitHub Actions reference workflow that uploads brief/export artifacts and gates on exit codes.
4) Track adoption: ensure Slack/Linear bridges consume exports (not DB) and include correlation keys + evidence hashes.
