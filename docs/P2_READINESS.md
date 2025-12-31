# P2 Readiness (Delivered Baseline)

This note now documents the shipped P2 scope from `docs/EXECUTION_PLAN.md`,
linking the live code paths, regression coverage, and acceptance criteria we
maintain going forward. P1 health scoring, suppression explainability, and
failure-budget gating remain in steady state (see
`hardstop/ops/source_health.py`, `hardstop/database/raw_item_repo.py`, and
`hardstop/ops/run_status.py`). The sections below ensure P2 features stay
regression-tested while contributors extend or maintain the decision core.

## Canonicalization v2 (src/hardstop/parsing/*)

- **Status:** Delivered. `CanonicalizeExternalEventOperator` and
  `EntityLinkingOperator` emit RunRecords, normalize fixtures from `tests/fixtures/`,
  and provide deterministic fallbacks for partial data before correlation.
- **Maintenance checklist / acceptance mapping:**
  - Keep operator input/output contracts aligned with `docs/ARCHITECTURE.md` and
    `docs/specs/run-record.schema.json`; emit RunRecords for every execution.
  - Preserve deterministic hashing of canonical payloads; update fixtures +
    schema docs when canonical fields evolve.
  - Ensure partial data paths remain deterministic (empty facilities/lanes/shipments).
- **Regression coverage:** `tests/test_correlation.py`,
  `tests/test_golden_run.py`, and fixture SHA checks under `tests/fixtures/normalized_event_spill.json`.

## Impact scoring transparency (src/hardstop/alerts/*)

- **Status:** Delivered. `hardstop/alerts/impact_scorer.py` persists rationale
  envelopes (network criticality, trust-tier modifiers, suppression context) and
  surfaces them via `AlertEvidence`.
- **Maintenance checklist / acceptance mapping:**
  - Keep rationale payload structure synchronized with `docs/ARCHITECTURE.md`,
    `docs/EXECUTION_PLAN.md`, and any downstream consumers (brief/export APIs).
  - Refresh fixtures/tests whenever scoring modifiers or keyword rules change to
    avoid silent drift in deterministic deltas.
  - Ensure suppression context continues to copy deterministic metadata from
    events (status, rule ids, reason codes).
- **Regression coverage:** `tests/test_impact_scorer.py`,
  `tests/test_demo_pipeline.py`, `tests/test_golden_run.py`.

## Correlation evidence graph (src/hardstop/output/incidents/*)

- **Status:** Delivered. `hardstop/output/incidents/evidence.py` stores merge
  reasons (temporal overlap, shared facilities/lanes, root-event history) and
  surfaces summaries to briefs/export APIs.
- **Maintenance checklist / acceptance mapping:**
  - Keep evidence schema mirrored in `docs/ARCHITECTURE.md` and
    `docs/specs/run-record.schema.json`, updating fixtures whenever fields evolve.
  - Maintain deterministic artifact hashing + filename conventions so `AlertEvidence`
    consumers remain replayable.
  - Ensure new merge heuristics also emit evidence entries and regression tests.
- **Regression coverage:** `tests/test_correlation.py`,
  `tests/test_output_renderer_only.py`, fixtures under
  `tests/fixtures/incident_evidence_spill.json`.

## Incident replay CLI (src/hardstop/cli.py)

- **Status:** Delivered. `hardstop incidents replay <incident_id>` re-materializes
  artifacts + RunRecords via `hardstop.incidents.replay@1.0.0` and enforces
  strict/best-effort semantics aligned with P0 provenance rules.
- **Maintenance checklist / acceptance mapping:**
  - Keep CLI + `hardstop/cli.py` args aligned with artifact directory layouts
    (`output/incidents`, `run_records/`) and ensure new artifact kinds wire into
    the replay envelope.
  - Maintain strict-mode failure behavior when dependencies are missing while
    surfacing actionable diagnostics in best-effort mode.
  - Ensure replay emits fresh RunRecords with fingerprints that match the current
    config snapshot (see `hardstop/ops/run_record.py` helpers).
- **Regression coverage:** `tests/test_run_record.py` (replay smoke test +
  schema validation), `tests/test_golden_run.py`, `tests/test_demo_pipeline.py`,
  and any CLI-focused suites covering failure modes.
