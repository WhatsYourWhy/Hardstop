# P2 Readiness Kickoff

This note maps the P2 execution items from `docs/EXECUTION_PLAN.md` to concrete
code paths and acceptance criteria so contributors can start implementation
quickly.

## Canonicalization v2 (src/hardstop/parsing/*)

- **Current state:** Normalization and entity extraction live in
  `src/hardstop/parsing/normalizer.py` and `src/hardstop/parsing/entity_extractor.py`
  but are coupled to downstream steps and lack explicit operator boundaries.
- **Acceptance criteria:**
  - Canonicalization operators declare inputs/outputs and emit RunRecords.
  - Entity linking handles partial data gracefully with deterministic fallbacks.
  - Tests pin canonical payload hashes for representative sources.

## Impact scoring transparency (src/hardstop/alerts/*)

- **Current state:** `src/hardstop/alerts/impact_scorer.py` computes scores with
  trust-tier modifiers but rationale details are not persisted in a stable,
  inspectable format.
- **Acceptance criteria:**
  - Persist rationale (trust-tier modifiers, network criticality, suppression context)
    alongside each scored alert/incident.
  - Regression tests in `tests/test_impact_scorer.py` pin rationale fields and
    ensure deterministic scoring deltas.

## Correlation evidence graph (src/hardstop/output/incidents/*)

- **Current state:** Incident correlation emits merged incidents but does not
  store evidence describing *why* events merged (temporal overlap, shared
  facilities, correlation keys).
- **Acceptance criteria:**
  - Introduce correlation evidence artifacts under `src/hardstop/output/incidents/`
    that enumerate merge reasons and inputs.
  - Briefs and export paths surface evidence summaries for analyst audit.
  - Tests validate evidence capture for overlapping events and for negative cases
    (no merge when evidence is insufficient).

## Incident replay CLI (src/hardstop/cli.py)

- **Current state:** CLI stubs exist for replay but no end-to-end path is wired.
- **Acceptance criteria:**
  - Implement `hardstop incidents replay <incident_id>` to re-materialize inputs
    and confirm determinate outputs using recorded RunRecords and artifacts.
  - Replay supports pinned timestamps/ids for determinism.
  - Tests cover a happy-path replay and a failure-path with missing artifacts.
