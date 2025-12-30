# P2 Readiness Kickoff

This note maps the P2 execution items from `docs/EXECUTION_PLAN.md` to concrete
code paths and acceptance criteria so contributors can start implementation
quickly. P1 health scoring, suppression explainability, and failure-budget
gating are complete (see `hardstop/ops/source_health.py`,
`hardstop/database/raw_item_repo.py`, and `hardstop/ops/run_status.py`), so this
doc starts from that baseline before enumerating P2 work.

## Canonicalization v2 (src/hardstop/parsing/*)

- **Current state:** Normalization and entity extraction live in
  `src/hardstop/parsing/normalizer.py` and `src/hardstop/parsing/entity_extractor.py`
  but are coupled to downstream steps and lack explicit operator boundaries.
- **Acceptance criteria:**
  - Canonicalization operators declare inputs/outputs and emit RunRecords (extend
    provenance expectations documented in `docs/ARCHITECTURE.md` and
    `docs/specs/run-record.schema.json`).
  - Entity linking handles partial data gracefully with deterministic fallbacks
    aligned to the canonicalization spec to be expanded in `docs/specs/`.
  - Tests pin canonical payload hashes for representative sources using
    `tests/fixtures/*.json|.csv` and add deterministic regressions to
    `tests/test_correlation.py` and `tests/test_golden_run.py`.

## Impact scoring transparency (src/hardstop/alerts/*)

- **Current state:** `src/hardstop/alerts/impact_scorer.py` computes scores with
  trust-tier modifiers but rationale details are not persisted in a stable,
  inspectable format.
- **Acceptance criteria:**
  - Persist rationale (trust-tier modifiers, network criticality, suppression context)
    alongside each scored alert/incident.
  - Regression tests in `tests/test_impact_scorer.py` pin rationale fields and
    ensure deterministic scoring deltas; refresh golden expectations under
    `tests/fixtures/` when rationale changes.
  - Document the rationale payload in `docs/ARCHITECTURE.md` and keep the
    scoring section synchronized with `docs/EXECUTION_PLAN.md` when modifiers
    evolve.

## Correlation evidence graph (src/hardstop/output/incidents/*)

- **Current state:** Incident correlation emits merged incidents but does not
  store evidence describing *why* events merged (temporal overlap, shared
  facilities, correlation keys).
- **Acceptance criteria:**
  - Introduce correlation evidence artifacts under `src/hardstop/output/incidents/`
    that enumerate merge reasons and inputs.
  - Briefs and export paths surface evidence summaries for analyst audit.
  - Tests validate evidence capture for overlapping events and for negative cases
    (no merge when evidence is insufficient) using deterministic fixtures in
    `tests/fixtures/` plus regressions in `tests/test_correlation.py` and
    `tests/test_output_renderer_only.py`.
  - Keep evidence schema aligned with `docs/ARCHITECTURE.md` decision artifact
    sections and any incident schema notes in `docs/specs/run-record.schema.json`.

## Incident replay CLI (src/hardstop/cli.py)

- **Current state:** CLI stubs exist for replay but no end-to-end path is wired.
- **Acceptance criteria:**
  - Implement `hardstop incidents replay <incident_id>` to re-materialize inputs
    and confirm determinate outputs using recorded RunRecords and artifacts.
  - Replay supports pinned timestamps/ids for determinism and requires
    `RunRecord` provenance plus stored artifacts (including correlation evidence)
    and the resolved config fingerprint hash to be present before execution.
  - Replay honors strict vs best-effort: strict mode fails deterministically if
    any input artifact or RunRecord is missing, while best-effort surfaces
    warnings but continues.
  - Tests cover a happy-path replay and deterministic failure modes when
    artifacts are missing, anchored in `tests/test_run_record.py`,
    `tests/test_golden_run.py`, and new replay-specific cases under
    `tests/test_output_renderer_only.py` or a dedicated `tests/output/`
    namespace.
