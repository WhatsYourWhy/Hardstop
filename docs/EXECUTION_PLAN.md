# Hardstop Execution Plan

This document translates the Hardstop runtime architecture into a concrete,
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
   can demo (`hardstop run`, `hardstop brief`) plus regression tests that lock
   in behavior.
4. **Protect local-first defaults** – no network writes, no hidden services, and
   strict mode is always the default path.

---

## Priority Bands at a Glance

| Priority | Focus Area | Why it is first | Representative Deliverables | Exit Criteria |
| --- | --- | --- | --- | --- |
| **P0** | Deterministic kernel hardening | Without trustworthy RunRecords and bounded operators, no downstream plan is replayable. | Complete RunRecord schema, config fingerprinting, CLI exit-code matrix, deterministic fixtures | Golden-run fixture reproduces hashes; `hardstop doctor` reports RunRecord coverage gaps <= 5% |
| **P1** | Source health + ingestion reliability | The pipeline depends on timely, bounded signals. | Tier-aware source registry, health scoring, suppression auditing, adapter conformance tests | `hardstop sources health` surfaces stale/failing sources with actionable codes; adapters emit standardized `SourceRun` rows |
| **P2** | Decision core + artifact quality | Alerts must be correct before we broadcast them. | Canonicalization refactor, impact scoring rationale, correlation evidence graph, incident replay CLI | Regression suite validates impact scoring deltas <= 5%; incidents carry full provenance |
| **P3** | Reporting + integrations | Only after artifacts are correct do we expand surfaces. | Markdown/JSON briefs v2, export API, Slack/Linear sinks, CI-ready exit signals | Daily brief + export flows align with new artifact schema; integration hooks stay read-only |

---

## Detailed Execution Steps

### P0 – Deterministic Kernel Hardening

- **RunRecord coverage**: extend `tests/test_run_status.py` and `hardstop/ops/*`
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
- **Operational ergonomics**: align CLI exit codes, `hardstop doctor`, and
  run-status footer so we can rely on them in CI/CD integrations later.

#### P0 Verification (Dec 2025)

- `python3 -m pytest` passes (103 tests as of Dec 2025). `tests/test_run_record.py`,
  `tests/test_run_status.py`, and `tests/test_golden_run.py` lock the RunRecord schema,
  the resolved merged-config fingerprint hash (canonical JSON serialization of the
  post-default snapshot), the strict vs best-effort exit-code matrix, and the golden
  fixture digests (with nondeterministic fields such as timestamps/paths normalized
  out of the hashed payloads) that guard determinism.
- `hardstop run` emits RunRecords with merged config fingerprints and mode metadata
  through the `hardstop.ops.run_record` helpers, and the CLI footer mirrors the exit-code
  decisions validated in the tests above.
- `hardstop doctor` exercises the same schema- and config-validation paths that drive
  RunRecord diagnostics, so CI or local operators get identical guidance before
  progressing to P1 workstreams.
- Given identical inputs, resolved configs, and strict mode, rerunning `hardstop run`
  produces identical RunRecord hashes plus unchanged golden artifact digests.
- Deterministic runs rely on caller-supplied IDs/timestamps (or replay-pinned values),
  stable hashing of normalized inputs with canonical key ordering, and deterministic
  ordering of diagnostics/messages prior to hashing/serialization. Operators that must
  tolerate nondeterminism switch to best-effort, declare their entropy sources
  (wall-clock reads, random jitter, network ordering), and record seeds/metadata under
  `best_effort` so replays know which fields may drift. Strict mode scrubs or pins
  nondeterministic fields when possible and will fail fast if an operator attempts to
  emit untracked entropy.

**P0 invariants**
- Every operator emits/finalizes a RunRecord for each execution.
- Config fingerprint hashes remain stable for identical resolved (post-default) snapshots.
- Strict vs best-effort exit codes and CLI footer messaging remain stable across runs.
- Golden fixture digests remain stable because nondeterministic fields are normalized.

### P1 – Source Reliability & Health

- **Source registry revamp**: move source definitions into a canonical schema
  with per-tier defaults (trust tier weighting, classification floor, max
  items).
- **Health scoring**: augment `hardstop sources health` with fetch success
  rates, stale timers, and suppression hit ratios. Persist metrics so runs can
  be trended.
- **Adapter contracts**: require every adapter to emit structured diagnostics
  (HTTP status, bytes pulled, dedupe count). Back this with contract tests under
  `tests/test_source_health*.py`.
- **Suppression observability**: log and persist suppression reasons so noise
  rules can be tuned; expose `--explain-suppress` in CLI docs.
- **Failure budget automation**: wire the health data into `hardstop doctor`
  so unhealthy sources block progression to downstream phases when appropriate.

#### P1 Retrospective (Shipped in v1.1.0)

- **Health score + budget states live**: `hardstop/ops/source_health.py` now emits deterministic scores and `health_budget_state` values (`HEALTHY`, `WATCH`, `BLOCKED`), surfaced in `hardstop sources health` and the API response for sources.
- **Suppression summaries and explain flag**: `hardstop/database/raw_item_repo.py` captures suppression reason counts, and `hardstop sources health --explain-suppress <source>` returns deterministic samples so operators can tune noisy rules.
- **Failure-budget gating**: `hardstop/ops/run_status.py` and `hardstop/cli.py` apply failure-budget blockers to exit codes (strict mode escalates warnings to exit code 2) so unhealthy sources halt downstream work.

#### P1 Execution Next Steps (Residual)

1. **Canonical source registry + tier defaults**
   - Produce a documented schema (lightweight spec doc + example YAML) that folds trust tier weighting, classification floors, weighting bias, and suppression overrides into a single source definition. Reference files: `config/sources.yaml`, `config/sources.example.yaml`, and `hardstop/config/loader.py`.
   - Update the loader so every CLI path (`hardstop sources list|health|test`) consumes the same normalized object. Add regression coverage in `tests/test_cli_sources.py` for tier defaults and schema validation errors.
   - *Exit criteria:* configuration diffs for a tier flip only change the trust tier field; health commands show tier + weighting bias without additional plumbing.

2. **Persisted health telemetry**
   - Extend `hardstop/database/source_run_repo.py` to store fetch success ratios, bytes pulled, suppression hit count, and rolling stale timers per source. Emit the metrics from adapters via `hardstop/retrieval/fetcher.py`.
   - Keep the scoring math pinned in `tests/test_source_health.py` and `tests/test_source_health_integration.py` to ensure deterministic aggregates when telemetry is replayed.
   - *Exit criteria:* rerunning `hardstop run` twice with identical inputs produces deterministic SourceRun rows whose aggregates are rendered in the health table without recomputing from scratch.

3. **Adapter diagnostics contract**
   - Define the required diagnostics envelope (HTTP status, bytes pulled, dedupe count, suppression hits) in this doc and mirror it in `docs/ARCHITECTURE.md`. Implement the logging in `hardstop/retrieval/adapters.py` and persist via `hardstop/database/raw_item_repo.py`.
   - Add pytest helpers so every adapter test asserts the diagnostics payload shape. Start with RSS + NWS fixtures in `tests/test_source_health*.py`.
   - *Exit criteria:* failing to emit diagnostics fails CI with a clear assertion instead of silently degrading observability.

### P2 – Decision Core & Artifact Quality

- **Canonicalization v2**: consolidate normalization and entity extraction into
  explicit operators with declared inputs/outputs. Ensure entity linking
  gracefully handles partial data.
- **Impact scoring transparency**: document and persist rationale including
  trust-tier modifiers, network criticality, and suppression context. Add tests
  in `tests/test_impact_scorer.py`.
- **Correlation evidence graph**: expand incident correlation to store why
  events merged (temporal overlap, shared facilities) so analysts can audit.
- **Incident replay CLI**: add `hardstop incidents replay <incident_id>` to
  re-materialize inputs and confirm determinate outputs.
- **Artifact schema updates**: refresh `docs/specs/run-record.schema.json` and
  related SQLite migrations to match the richer incident + decision artifacts.

### P3 – Reporting, Export, and Integrations

- **Brief v2**: restructure Markdown/JSON briefs to consume the new artifacts,
  add badges for trust tiers, and expose suppression rationale for each alert.
- **Export API / bundles**: deliver read-only exports (JSON bundle + CSV) so
  downstream tools can ingest Hardstop outputs without touching the DB.
- **Chat & work tracker sinks**: document Slack webhook + Linear issue mirroring
  flows with deterministic retry logic; integrations should read from exported
  artifacts instead of live DB queries.
- **CI/CD hooks**: publish a reference GitHub Actions workflow that runs
  `hardstop run`, `hardstop doctor`, and surfaces exit codes/status summaries.
- **Operational playbooks**: document runbooks for remediation when sources or
  operators fail, tying back to health metrics emitted in earlier phases.

---

## Cross-Cutting Deliverables

- **Documentation cadence**: every phase requires README + `docs/ARCHITECTURE.md`
  updates plus changelog entries so contributors can follow along.
- **Testing + automation**: expand pytest suites, add benchmarking hooks, and
  gate releases on golden-run plus health test success.
- **Release packaging**: ensure `pyproject.toml` extras stay current and the
  `hardstop init` path provisions config compatible with the new plan.

---

## Current Status Snapshot (Dec 2025)

- P0 tasks complete and locked by regression tests (RunRecord schema + config
  fingerprints, strict/best-effort exit codes, golden-run fixtures).
- P1 health scoring, suppression explainability, and failure-budget gating are
  live (`hardstop/ops/source_health.py`, `hardstop/database/raw_item_repo.py`,
  `hardstop/ops/run_status.py`, `hardstop/cli.py`); remaining work centers on
  the canonical source registry, persisted telemetry plumbing, and the adapter
  diagnostics contract.
- P2 correlation evidence and replay tooling not yet implemented.
- P3 integrations rely on ad-hoc scripts; no export bundle spec.

This plan should be revisited at the end of every release cycle to confirm
assumptions, retire completed work, and reprioritize based on new risks.
