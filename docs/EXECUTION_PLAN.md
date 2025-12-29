# Sentinel Execution Plan

This document translates the Sentinel runtime architecture into a concrete,
prioritized execution plan. The goal is to ensure every change furthers the
deterministic, local-first design while sequencing work from the most
foundational dependencies to user-facing integrations.

---

## Guiding Principles

1. **Determinism before features** – every new surface must emit fingerprints,
   RunRecords, and bounded execution hooks before we consider UX polish.
2. **Single source of truth for contracts** – schemas, configs, and operator
   boundaries live in `docs/ARCHITECTURE.md` + `docs/specs`. Implementation and
   documentation changes ship together.
3. **Ship measurable increments** – each priority band ends with artifacts we
   can demo (`sentinel run`, `sentinel brief`) plus regression tests that lock
   in behavior.
4. **Protect local-first defaults** – no network writes, no hidden services, and
   strict mode is always the default path.

---

## Priority Bands at a Glance

| Priority | Focus Area | Why it is first | Representative Deliverables | Exit Criteria |
| --- | --- | --- | --- | --- |
| **P0** | Deterministic kernel hardening | Without trustworthy RunRecords and bounded operators, no downstream plan is replayable. | Complete RunRecord schema, config fingerprinting, CLI exit-code matrix, deterministic fixtures | Golden-run fixture reproduces hashes; `sentinel doctor` reports RunRecord coverage gaps <= 5% |
| **P1** | Source health + ingestion reliability | The pipeline depends on timely, bounded signals. | Tier-aware source registry, health scoring, suppression auditing, adapter conformance tests | `sentinel sources health` surfaces stale/failing sources with actionable codes; adapters emit standardized `SourceRun` rows |
| **P2** | Decision core + artifact quality | Alerts must be correct before we broadcast them. | Canonicalization refactor, impact scoring rationale, correlation evidence graph, incident replay CLI | Regression suite validates impact scoring deltas <= 5%; incidents carry full provenance |
| **P3** | Reporting + integrations | Only after artifacts are correct do we expand surfaces. | Markdown/JSON briefs v2, export API, Slack/Linear sinks, CI-ready exit signals | Daily brief + export flows align with new artifact schema; integration hooks stay read-only |

---

## Detailed Execution Steps

### P0 – Deterministic Kernel Hardening

- **RunRecord coverage**: extend `tests/test_run_status.py` and `sentinel/ops/*`
  to ensure every operator writes `input_refs`, `output_refs`, config hashes,
  and mode metadata. Add `docs/specs/run-record.schema.json` acceptance tests.
- **Config fingerprinting**: formalize a merged config view (`runtime.yaml`,
  operator defaults, env overrides) and persist the stable hash alongside every
  RunRecord.
- **Strict/best-effort enforcement**: gate operators behind explicit modes,
  fail fast when an operator attempts nondeterministic IO without switching to
  best-effort.
- **Golden-run fixture**: refresh the fixture dataset under `tests/fixtures/`
  and assert SHA-256 outputs for alerts, incidents, and briefs. This guards all
  downstream work.
- **Operational ergonomics**: align CLI exit codes, `sentinel doctor`, and
  run-status footer so we can rely on them in CI/CD integrations later.

#### P0 Verification (Dec 2025)

- `python3 -m pytest` currently passes 103 tests, with `tests/test_run_record.py`,
  `tests/test_run_status.py`, and `tests/test_golden_run.py` locking in the
  RunRecord schema, config fingerprint hash, exit-code matrix, and golden fixture
  digests that guard determinism.
- `sentinel run` now emits RunRecords with merged config fingerprints and
  mode metadata (strict vs best-effort) through the `sentinel.ops.run_record`
  helpers, and the CLI footer mirrors the exit-code decisions validated in the
  tests above.
- `sentinel doctor` exercises the same schema- and config-validation paths that
  drive RunRecord diagnostics, so CI or local operators get identical guidance
  before progressing to P1 workstreams.

### P1 – Source Reliability & Health

- **Source registry revamp**: move source definitions into a canonical schema
  with per-tier defaults (trust tier weighting, classification floor, max
  items).
- **Health scoring**: augment `sentinel sources health` with fetch success
  rates, stale timers, and suppression hit ratios. Persist metrics so runs can
  be trended.
- **Adapter contracts**: require every adapter to emit structured diagnostics
  (HTTP status, bytes pulled, dedupe count). Back this with contract tests under
  `tests/test_source_health*.py`.
- **Suppression observability**: log and persist suppression reasons so noise
  rules can be tuned; expose `--explain-suppress` in CLI docs.
- **Failure budget automation**: wire the health data into `sentinel doctor`
  so unhealthy sources block progression to downstream phases when appropriate.

### P2 – Decision Core & Artifact Quality

- **Canonicalization v2**: consolidate normalization and entity extraction into
  explicit operators with declared inputs/outputs. Ensure entity linking
  gracefully handles partial data.
- **Impact scoring transparency**: document and persist rationale including
  trust-tier modifiers, network criticality, and suppression context. Add tests
  in `tests/test_impact_scorer.py`.
- **Correlation evidence graph**: expand incident correlation to store why
  events merged (temporal overlap, shared facilities) so analysts can audit.
- **Incident replay CLI**: add `sentinel incidents replay <incident_id>` to
  re-materialize inputs and confirm determinate outputs.
- **Artifact schema updates**: refresh `docs/specs/run-record.schema.json` and
  related SQLite migrations to match the richer incident + decision artifacts.

### P3 – Reporting, Export, and Integrations

- **Brief v2**: restructure Markdown/JSON briefs to consume the new artifacts,
  add badges for trust tiers, and expose suppression rationale for each alert.
- **Export API / bundles**: deliver read-only exports (JSON bundle + CSV) so
  downstream tools can ingest Sentinel outputs without touching the DB.
- **Chat & work tracker sinks**: document Slack webhook + Linear issue mirroring
  flows with deterministic retry logic; integrations should read from exported
  artifacts instead of live DB queries.
- **CI/CD hooks**: publish a reference GitHub Actions workflow that runs
  `sentinel run`, `sentinel doctor`, and surfaces exit codes/status summaries.
- **Operational playbooks**: document runbooks for remediation when sources or
  operators fail, tying back to health metrics emitted in earlier phases.

---

## Cross-Cutting Deliverables

- **Documentation cadence**: every phase requires README + `docs/ARCHITECTURE.md`
  updates plus changelog entries so contributors can follow along.
- **Testing + automation**: expand pytest suites, add benchmarking hooks, and
  gate releases on golden-run plus health test success.
- **Release packaging**: ensure `pyproject.toml` extras stay current and the
  `sentinel init` path provisions config compatible with the new plan.

---

## Current Status Snapshot (Dec 2025)

- P0 tasks complete and locked by regression tests (RunRecord schema + config
  fingerprints, strict/best-effort exit codes, golden-run fixtures).
- P1 groundwork in place via `sentinel sources health` but lacks suppression
  analytics and failure budgets.
- P2 correlation evidence and replay tooling not yet implemented.
- P3 integrations rely on ad-hoc scripts; no export bundle spec.

This plan should be revisited at the end of every release cycle to confirm
assumptions, retire completed work, and reprioritize based on new risks.
