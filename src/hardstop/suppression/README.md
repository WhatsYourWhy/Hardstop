# Suppression engine

Noise control for fetched/ingested items. Responsible for applying global and per-source suppression rules deterministically.

## Responsibilities
- Define suppression models (`models.py`) and apply them in `engine.py`.
- Compute suppression ratios and primary rule IDs for downstream reporting (brief suppression rollups, source health `suppression_ratio`).

## Stable entry points
- Suppression engine functions (see `engine.py`) used by ingestion/pipeline operators to mark items as suppressed and persist rule hits.

## Contracts
- **Inputs:** normalized items/events plus resolved suppression config (`config/suppression.yaml`); optional per-source overrides.
- **Outputs:** suppression decisions with primary rule IDs and aggregates used by `api.brief_api` and `sources_api`.
- **Determinism:** Rule evaluation is deterministic; keep rule ordering stable and avoid RNG in pattern matching.

## P3 readiness notes
- Keep suppression rollup data (rule ID counts, source-level ratios) available for briefs and source-health exports.
- Future explainability should reuse the existing rule IDs and reason codes to maintain compatibility with reporting surfaces.
