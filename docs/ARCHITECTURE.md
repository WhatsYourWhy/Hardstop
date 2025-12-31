# Hardstop Runtime Technical Architecture

Hardstop Runtime is a local-first deterministic decision engine. It ingests heterogeneous signals, normalizes and correlates them over time, evaluates them using explicit operators, and emits decision artifacts with provenance and fingerprints.

---

## Purpose

Hardstop exists to make reliable, explainable decisions offline or in constrained environments. The runtime is designed for:

- deterministic execution (by default)
- explicit inputs/outputs (no hidden context)
- replayability (same inputs + same versions + same config → same outputs)
- provenance and auditability
- bounded processing (avoid “firehose” behavior)
- offline-first operation

Non-goals include conversational agent behavior, autonomous planning, self-modifying policies, and black-box model authority in the decision path.

---

## System Overview

Hardstop is structured around three layers:

1. **Ingestion Layer** — adapters fetch or receive signals from APIs, feeds, files, or streams.
2. **Decision Core (Operators + Runtime)** — a deterministic pipeline of operators transforms signals into correlated incidents and decision artifacts.
3. **Artifact Layer (Storage + Reporting)** — all outputs are stored as structured artifacts with fingerprints and provenance.

Each layer has explicit contracts so that inputs, outputs, and state transitions are observable and auditable.

---

## Core Concepts

### Signal

Signals are the smallest input units.

| Field | Description |
| --- | --- |
| `signal_id` | Stable unique id or derived hash |
| `source` | Adapter / source identifier |
| `observed_at` | Timestamp from source if available |
| `ingested_at` | Runtime timestamp |
| `type` | Enum/category |
| `payload` | Canonical JSON payload; raw preserved if needed |
| `confidence` | Optional numeric (deterministic input only) |
| `raw_ref` | Optional pointer to raw blob |

Signals are immutable once stored (append-only).

### Operator

Operators are deterministic transforms with explicit read/write behavior and resource budgets. They:

- declare the artifact types they read/write
- default to strict deterministic mode
- emit a RunRecord on every execution

### Decision Artifact

Decision artifacts are the outputs of evaluation (risk scores, classified incidents, recommended actions). Reports/briefs are derived artifacts that never influence upstream logic.

---

## Execution Model

### Runtime Loop

The runtime is a repeated cycle (cron or daemon):

1. Ingest new signals (adapters enforce rate limits + payload bounds)
2. Normalize/canonicalize
3. Apply noise control (suppression/dedup)
4. Correlate temporally
5. Evaluate / score
6. Emit decision artifacts + reports

### Determinism Modes

- **Strict mode (default):** disallows nondeterministic sources (randomness, unpinned dependencies, dynamic models without versioning).
- **Best-effort mode:** allows nondeterminism, but the operator must declare it and capture metadata (seed, model hash, etc.).

Strict mode runs are replayable as long as code, config, and inputs match.

---

## Storage & Provenance

A local persistent store (SQLite by default) supports:

- append-only signals
- append-only artifacts
- run records (provenance)
- indexes for retrieval/correlation windows
- additive migrations

### Run Record (Provenance Unit)

| Field | Description |
| --- | --- |
| `run_id` | Unique execution id |
| `operator_id` | Name + version |
| `started_at`, `ended_at` | Timing metadata |
| `mode` | strict / best-effort |
| `config_hash` | Hash of resolved config used |
| `input_refs[]` | Artifact ids/hashes read |
| `output_refs[]` | Artifact ids/hashes written |
| `warnings[]`, `errors[]` | Structured diagnostics |
| `cost` | Time, memory estimate, bytes in/out |

The RunRecord is the backbone for replay, audit, and billing-like accounting.

Implementation note: `hardstop.ops.run_record` contains the canonical emitter. CLI surfaces such as `hardstop run` persist RunRecords under `run_records/`, ensuring every execution captures the config fingerprint and run-status diagnostics.
Fetch (`hardstop fetch`), ingest (`hardstop ingest-external`), and brief (`hardstop brief`) now emit per-operator RunRecords keyed by a shared `run_group_id`, threading raw-item batches, `SourceRun` rows, and brief artifacts through explicit input/output refs for provenance.
Deterministic and replayed runs can provide fixed `run_id`, `started_at`, and `ended_at` values plus a `canonicalize_time` helper to normalize timestamps (e.g., round to whole seconds). File names can be pinned via `filename_basename` to avoid timestamp drift in golden fixtures. Best-effort (nondeterministic) runs must populate `best_effort` metadata to explain entropy sources and enable repeatability notes.

### Incident Evidence Artifacts

- Location: `output/incidents/`
- Schema: `incident-evidence.v1` (non-decisional)
- Purpose: Capture why alerts merged (temporal overlap, correlation key, shared facilities/lanes) and the inputs (alert_id, root_event_ids, event metadata) that drove the merge decision.
- Hashing: Canonical JSON (`hardstop.ops.run_record.artifact_hash`) with `ArtifactRef.kind = "IncidentEvidence"` so RunRecords and briefs can reference the evidence payload.
- Consumption: Brief/export renderers read the latest artifact per alert/correlation key to surface `merge_summary` strings without re-querying the DB, keeping reporting read-only and deterministic.

---

## Fingerprinting & Replayability

- Fingerprint every ingested raw blob, normalized signal payload, operator config, and operator output.
- Use canonical JSON serialization (stable key ordering) and SHA-256 hashing with explicit schema/version identifiers.
- Replay contract: a run is replayable if operator code version, input refs, config hash, and strict/best-effort metadata match. Replay must reproduce the exact output hashes.

## Deterministic Kernel Contract

- Every operator emits and finalizes a RunRecord (success or failure) via `hardstop.ops.run_record`, capturing mode metadata, resolved config fingerprint, and artifact refs. This is the enforcement spine for provenance and exit-code evaluation.
- Config fingerprints hash the resolved merged snapshot (defaults applied, overrides folded in) using canonical serialization, so identical configs produce identical hashes across hosts.
- Golden artifacts and fixtures hash only normalized payloads (timestamps, filesystem paths, or other nondeterministic fields are scrubbed) to prevent drift in determinism guards.
- Strict vs best-effort exit codes, CLI footer messaging, and run-status diagnostics are regression-locked; rerunning in strict mode with identical inputs and resolved config reproduces the same RunRecord hashes and golden artifact digests.
- Deterministic runs require caller-supplied identifiers and timestamps (or replay-pinned values) so that hashing inputs is stable. Operators hash normalized payloads with canonical key ordering; diagnostic and message streams are ordered deterministically before hashing/serialization.
- Best-effort mode is the only place nondeterministic inputs are allowed (e.g., wall-clock, random jitter). Operators must capture seeds/metadata under `best_effort` and note which fields are nondeterministic; strict mode either rejects those fields or replaces them with pinned values during replays.
- Validation sources: `docs/specs/run-record.schema.json` defines the serialized contract, while `docs/EXECUTION_PLAN.md#P0-Verification` documents the pytest-backed enforcement that keeps these invariants true.

---

## Bounded Processing

Hardstop enforces bounded causal radius to avoid “firehose” behavior:

- Adapters cap payload size, enforce paging/sampling, and respect `max_signals_per_cycle`.
- Operators operate on explicit windows (time/count/bytes) and declare them.
- Correlation is windowed with `max_window_hours` + `max_candidates`.
- `max_bytes_per_signal`, `max_candidates`, and similar knobs are part of runtime config and therefore fingerprinted.

---

## Operator Taxonomy

1. **Ingestion Operators (Adapters)** — fetch new records, normalize timestamps and ids, preserve raw payload if configured, enforce rate limits/payload bounds. Outputs: `RawBlob?`, `Signal`.
2. **Canonicalization Operators** — map source-specific fields into canonical schema and enrich via deterministic lookups. Outputs: `SignalCanonical`.
3. **Noise Control Operators** — suppression/dedup/throttling with audit trails. Outputs: `SignalFiltered`, suppression audit artifacts.
4. **Temporal Inference Operators (Correlation)** — group signals into incidents/events using windowed similarity rules, emit correlation evidence. Outputs: `Incident`, `IncidentEvidence`.
5. **Evaluation Operators (Scoring/Decisions)** — apply deterministic scoring models, produce risk posture + rationale. Outputs: `DecisionArtifact`.
6. **Reporting Operators** — render artifacts into Markdown/JSON briefs or export bundles. Outputs: `Brief`, export files. They never influence upstream decisions.

### Mapping to Current Hardstop Modules

| Taxonomy Layer | Hardstop Modules | Notes |
| --- | --- | --- |
| Ingestion Operators | `hardstop/retrieval/adapters.py`, `hardstop/retrieval/fetcher.py` | Adapters already limit rate and stamp `SourceRun` metrics. |
| Canonicalization | `hardstop/parsing/normalizer.py`, `hardstop/parsing/entity_extractor.py` | Includes deterministic enrichment with network data. |
| Noise Control | `hardstop/suppression/engine.py`, `hardstop/retrieval/dedupe.py` (implicit) | Suppression metadata is persisted for audits. |
| Temporal Inference | `hardstop/alerts/correlation.py`, `hardstop/alerts/alert_builder.py` (incident grouping) | 7-day window + correlation key boundedness. |
| Evaluation | `hardstop/alerts/impact_scorer.py`, `hardstop/alerts/alert_builder.py` | Strict heuristics with trust-tier modifiers and rationale fields. |
| Reporting | `hardstop/output/daily_brief.py`, `hardstop/api/export.py` | Render-only; no decision authority. |
| Artifact Layer | `hardstop/database/*`, `hardstop/ops/run_status.py` | SQLite store, migrations, run evaluation, provenance. |

When adding new modules, declare their taxonomy tier and the artifact types they read/write so operators remain composable.
Canonicalization operator inputs/outputs and hashing rules are described in detail in [`docs/specs/canonicalization.md`](specs/canonicalization.md).

### Impact scoring rationale payload (deterministic audit envelope)

Impact scoring emits deterministic rationale alongside numeric scores under `AlertEvidence.diagnostics.impact_score_rationale`:

- `network_criticality`: Facilities, lanes, and shipments that contributed to the base score. Includes the deltas applied, shipment counts, and near-term priority shipment IDs (sorted) so replayed runs reproduce the same rationale ordering.
- `modifiers`: Trust-tier and weighting-bias deltas applied after the base score (`trust_tier_delta`, `weighting_bias_delta`, and the asserted `trust_tier`).
- `suppression_context`: Stable suppression metadata copied from the event (`suppression_status`, `suppression_primary_rule_id`, `suppression_rule_ids` sorted deterministically, and `suppression_reason_code` when present).
- `score_trace`: Base score before modifiers, final capped score, and any keyword terms that triggered scoring.

The rationale payload is purely evidentiary; it does not change the decision surface but keeps score explainability stable across runs.

---

## Configuration Model

Configuration is part of determinism, so it must be fingerprinted.

- `runtime.yaml` — global limits, mode (strict/best-effort), schedules.
- `adapters/*.yaml` — source-specific credentials, paging, rate limits, bounds.
- `operators/*.yaml` — thresholds, windows, weights per operator.
- `schemas/` — pinned versions for canonical payloads.

At runtime, configs are merged with defaults, resolved to concrete values, and hashed (`config_hash`). The resolved view is stored alongside RunRecords.

---

## Security Model (Local-First)

Threat model v0.1 focuses on preventing accidental data exfiltration and uncontrolled reads, while keeping the decision path reproducible.

- Adapters are the only network boundary; a “no-network mode” is supported for air-gapped environments.
- File system reads are scoped to configured directories.
- Secrets live in environment variables or OS keychain integrations (future work).
- If third-party operators/plugins are introduced, they must be sandboxed, signed, and use explicit allowlists for reads/writes.

---

## Extensibility

### Adding a New Operator

Must provide:

- operator id + version
- declared input/output artifact types
- configuration schema + defaults
- deterministic strict-mode behavior
- tests: schema validation, replayability (hash-stable outputs), bounded-window behavior

### Adding a New Adapter

Adapters must define paging/rate-limit behavior, cap payload sizes, produce canonical timestamps/ids, and emit stable fingerprints.

---

## Testing Strategy

1. **Determinism tests** — same inputs + config → same output hashes.
   - `tests/test_golden_run.py` locks the SHA-256 hash for the demo event fixture so regressions are detected immediately.
2. **Boundedness tests** — enforce max bytes/items/window per operator.
3. **Provenance tests** — RunRecords exist and reference the correct inputs/outputs.
4. **Migration tests** — additive migrations run cleanly and keep legacy artifacts readable.
5. **End-to-end “golden run”** — fixture dataset produces exact expected artifacts/hashes.

Tests for adapters/operators should run in strict mode with pinned dependencies and fixtures under `tests/`.

---

## Architecture-Aligned Execution Roadmap

The execution priorities are described in detail in
[`docs/EXECUTION_PLAN.md`](EXECUTION_PLAN.md). Each priority band maps directly
to architectural dependencies and current delivery status:

- **P0 – Deterministic kernel hardening (Delivered)**  
  RunRecord coverage, config fingerprinting, strict/best-effort enforcement, and golden-run fixtures are regression-locked so every operator is replayable before higher tiers ship.
- **P1 – Source reliability & health (Delivered)**  
  Canonical source schemas, tier-aware health scores, suppression analytics, and `hardstop doctor` failure-budget gating are live with persisted `SourceRun` telemetry and CLI coverage.
- **P2 – Decision core & artifact quality (Delivered, maintenance mode)**  
  Canonicalization v2, scoring rationale payloads, correlation evidence artifacts, and the incident replay CLI close the loop on replayable decisions; updates now focus on maintenance aligned with `docs/P2_READINESS.md`.
- **P3 – Reporting & integrations (Next up)**  
  Brief/export upgrades, deterministic bundles, and Slack/Linear/CI sinks remain open and depend on the stable artifacts from P2.

Revisit the roadmap alongside the execution plan every release cycle; updates
must land in README, this document, and the execution plan simultaneously.

For maintenance of the shipped P2 scope (canonicalization v2, impact scoring
transparency, correlation evidence, replay CLI), use `docs/P2_READINESS.md` as
the acceptance-mapping reference to keep code paths and regression suites aligned.

---

## Implementation Notes (Pragmatic Defaults)

- SQLite for storage with additive migrations.
- Canonical JSON + SHA-256 for hashes.
- Append-only artifacts + RunRecords; avoid in-place edits.
- Explicit operator boundaries; functions should accept/read artifacts rather than implicit globals.
- Keep the runtime loop simple; correctness and determinism trump clever scheduling.

---

## Alignment Checklist for the Current Codebase

Use this checklist when reviewing new changes or planning refactors:

- **Determinism:** `hardstop/alerts/impact_scorer.py` and other evaluators avoid nondeterministic sources; if randomness is introduced, capture seeds in RunRecord metadata.
- **Explicit I/O:** Repositories in `hardstop/database/` expose artifact-level APIs; operators should not reach directly into SQLite without declaring what they read/write.
- **Replayability:** CLI commands pin their config via `config_hash` (see `hardstop/ops/run_status.py`). Ensure fixtures in `tests/` include expected hashes.
- **Provenance:** `source_run_repo.py` + future RunRecord schemas capture inputs/outputs and warnings/errors for each operator.
- **Bounded Processing:** Retrieval adapters honor `--since`, `--max-items`, and per-source rate limits; correlation enforces 7-day windows; new operators must document their bounds.
- **Offline Capable:** Default execution works without network beyond adapter calls; provide `--no-network`/local fixture modes for demos.

When planning future work, map the feature to an operator tier, describe its inputs/outputs/config, and update this document plus related specs accordingly.
