# Hardstop

**Hardstop** is a deterministic supply chain risk decision engine. It monitors external sources (RSS feeds, government APIs, alerts) and generates actionable risk alerts by linking events to your operational network.

<p align="center">
  <img src="docs/assets/hardstop-branding.png" alt="Hardstop branding" width="540">
</p>

## Table of Contents

- [Quick Start TL;DR](#quick-start-tldr)
- [What is Hardstop?](#what-is-hardstop)
- [Connect your tools](#connect-your-tools)
- [Status](#status)
- [Features](#features)
- [Quick Start](#quick-start)
- [First-Time Setup](#first-time-setup)
- [Demo Pipeline (P0 verification)](#demo-pipeline-p0-verification)
- [Daily Workflow](#daily-workflow)
- [Usage](#usage)
- [Configuration](#configuration)
- [Source Health Monitoring](#source-health-monitoring)
- [Exit Codes and Run Status](#exit-codes-and-run-status)
- [Architecture](#architecture)
- [Run Records in Practice](#run-records-in-practice)
- [Execution Plan](#execution-plan)
- [Requirements](#requirements)
- [Project Structure](#project-structure)
- [Key Documentation & Audits](#key-documentation--audits)
- [Support & Troubleshooting](#support--troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Changelog](#changelog)

## Quick Start TL;DR

1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install --require-hashes -r requirements.lock.txt`
3. `pip install --no-deps -e .`
4. `hardstop init` to copy example configs safely
5. Edit `config/sources.yaml` and `config/suppression.yaml`
6. `hardstop doctor` to verify PATH, DB, and health checks
7. `hardstop ingest` to seed facilities, lanes, and shipments
8. `hardstop run --since 24h` then `hardstop brief --today --since 24h`

## What is Hardstop?

Hardstop solves the problem of information overload from multiple alert sources. Instead of manually checking dozens of feeds, Hardstop:

- **Monitors** public sources (NWS alerts, FDA recalls, USCG notices, RSS feeds)
- **Filters** noise using configurable suppression rules
- **Links** events to your network (facilities, lanes, shipments)
- **Assesses** risk using deterministic impact scoring
- **Generates** tier-aware daily briefs with actionable alerts

**Key Differentiators:**
- **Local-first**: All data stored locally in SQLite, no cloud dependencies
- **Deterministic**: Same input = same output, fully auditable
- **Self-evaluating**: Exit codes and health checks tell you when something's wrong
- **Production-shaped**: Built for reliability with source health tracking and guaranteed failure reporting (we attempt to write one INGEST SourceRun per source per run_group_id; if the DB commit fails, the run record may not persist)

### Core Guarantees

- **Determinism & Auditability**: The P0 kernel is regression-locked so that identical inputs, resolved configs, and strict mode reruns produce identical RunRecord hashes and artifact digests. Deterministic runs rely on caller-supplied IDs/timestamps (or pinned values for replays), stable hashing of normalized inputs, and ordered diagnostics/messages. Best-effort runs must declare entropy (e.g., wall-clock reads, random jitter) and record seeds/metadata; strict mode scrubs or pins these fields and fails if untracked nondeterministic fields leak into hashes. See `docs/EXECUTION_PLAN.md#P0-Verification` for the validation contract.

## Connect your tools

Hardstop is designed to be local-first but still play nicely with your collaboration stack. Use the [integrations guide](docs/INTEGRATIONS.md) for:

- Posting daily briefs to Slack or other chat tools
- Pairing Hardstop runs with CI/CD in GitHub or GitLab
- Allowing agents or automations to act on deterministic alerts
- Mirroring high-impact alerts into Linear or other work trackers

## Status

**v1.0** — Production-shaped for personal daily driver use
- Self-evaluating runs with exit codes (healthy/warning/broken)
- Source health tracking and monitoring
- Guaranteed failure reporting (no silent failures)
- Smooth first-time setup with `hardstop init`
- Comprehensive health checks with actionable recommendations

## Features

### Core Capabilities

- **External Source Retrieval**: Fetch events from RSS/Atom feeds, NWS Alerts API, FDA, USCG, and other public sources
- **Source Health Monitoring**: Track fetch and ingest success rates, detect stale sources, test individual sources
- **Source Tiers**: Classify sources as Global, Regional, or Local for tier-aware processing
- **Trust Tier Weighting**: Prioritize sources based on reliability (tier 1-3) with configurable bias
- **Suppression Rules**: Filter noisy events using keyword, regex, or exact match patterns (global and per-source)
- **Event Processing**: Normalize raw events into canonical format
- **Network Linking**: Automatically link events to facilities, lanes, and shipments
- **Alert Generation**: Deterministic risk assessment using network impact scoring with trust tier modifiers and quality validation (confidence thresholds prevent false positives)
- **Alert Correlation**: Deduplicate and update alerts based on correlation keys
- **Tier-Aware Briefing**: Generate summaries with tier counts, badges, and grouping (markdown or JSON)
- **Run Status Evaluation**: Self-evaluating runs with exit codes (0=healthy, 1=warning, 2=broken)
- **Health Checks**: Comprehensive `hardstop doctor` command with actionable recommendations

### Exit Codes

Hardstop runs are self-evaluating and exit with appropriate codes:

- **0 (Healthy)**: No critical issues, pipeline functioning normally
- **1 (Warning)**: Some sources stale/failing, but pipeline still functioning
- **2 (Broken)**: Schema/config invalid, cannot fetch/ingest at all

Use `--strict` flag to treat warnings as broken (exit code 2).

## Quick Start

### Prerequisites (clean machine)

- Python **3.10+** with `pip` (`python3 --version` should report 3.10 or newer).
- The `python3-venv` package so `python3 -m venv` works. On Ubuntu/Debian run `sudo apt-get update && sudo apt-get install -y python3-venv`.
- A shell `PATH` entry for user-level scripts (typically `$HOME/.local/bin`). Add `export PATH="$HOME/.local/bin:$PATH"` to your shell rc file if `which hardstop` fails outside an activated virtualenv or `pip install --user` environment.

### Installation (reproducible and hashed)

```bash
# 1. Create + activate a virtual environment
python -m venv .venv
source .venv/bin/activate              # Linux / macOS
.\.venv\Scripts\Activate.ps1            # Windows PowerShell

# 2. Install the vetted, hashed dependency set
pip install --require-hashes -r requirements.lock.txt

# 3. Expose Hardstop in editable mode (keeps local code changes live)
pip install --no-deps -e .
```

> If `python3 -m venv` fails with `No module named venv`, install the `python3-venv` package from the prerequisites section and rerun the command.

- `requirements.lock.txt` bundles runtime + dev extras (pytest, pip-tools, pip-audit, etc.) so every install resolves to the same wheels across machines.
- After pulling new changes, re-sync with: `pip-sync requirements.lock.txt` (available because pip-tools is part of the lockset).
- Need a smaller runtime-only environment? Install from the lockfile and skip the editable step, or create a second venv that only runs `pip install --require-hashes -r requirements.lock.txt`.
- Windows PowerShell users may need `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` before running the activation script.

#### Verify the environment

```bash
pip check
pip-audit --progress-spinner off
pytest
```

All three commands must pass inside the locked environment before shipping changes. `pip-audit` is now scoped to the repo-owned dependencies, so findings are actionable and reproducible.

#### Updating dependencies (maintainers only)

Hardstop uses `pip-tools` to compile the lockfile from `pyproject.toml`. To refresh pins:

```bash
pip install --upgrade pip-tools
pip-compile --allow-unsafe --extra dev --generate-hashes \
  --output-file requirements.lock.txt pyproject.toml
```

Commit the updated `requirements.lock.txt` alongside any intentional spec bumps in `pyproject.toml`, then rerun the verification commands above.

### First-Time Setup

Run these once per checkout to bootstrap configuration safely:

1. Run `hardstop init` immediately after installation to copy the example configs. This command is idempotent—omit `--force` to preserve existing changes, and only pass `--force` when you intentionally want to overwrite your current configs with the shipped examples.
2. Review and edit `config/sources.yaml` plus `config/suppression.yaml` so they match your monitoring needs.
3. (Recommended) Run `hardstop doctor` to confirm PATH, config, database, and source health expectations before the first fetch.
4. Load network data, run the pipeline, and generate a brief.

```bash
# Initialize configuration files from examples
hardstop init          # add --force only when you intend to reset configs

# Review and customize config files
# - config/sources.yaml: Configure your sources
# - config/suppression.yaml: Configure suppression rules

# Optional but recommended: verify bootstrap health
hardstop doctor

# Load network data (required for network linking)
hardstop ingest
# See docs/CSV_CONTRACT.md for CSV format requirements

# Run your first fetch and ingest
hardstop run --since 24h

# Generate your first brief
hardstop brief --today --since 24h
```

> Newly added or “never run” sources appear as `BLOCKED` placeholders in `hardstop doctor` / `hardstop sources health` until they succeed once. Kick off `hardstop sources test <source_id> --since 72h` to prime a new source immediately—the state flips as soon as its first fetch records a success.

### Demo Pipeline (P0 verification)

Use the baked-in demo workflow when you need a sanity check of the network linker + alert builder stack.  
There are now two determinism modes:

- **live** (default): mirrors real runtime behavior. Alert IDs/timestamps drift with the wall clock, but classification, scope, and linkage invariants must match the README claims.
- **pinned**: freezes timestamp + UUID seed so audits/CI can diff byte-for-byte outputs. Alert IDs, incident artifact hashes, and determinism metadata stay constant.

```bash
# Install runtime + tests (once per environment)
pip install --require-hashes -r requirements.lock.txt
pip install --no-deps -e .

# Load the golden-path network data into SQLite (idempotent)
python3 -m hardstop.runners.load_network
```

#### Pinned / golden run (stable alert + artifacts)

```bash
# Run via module or CLI flag (same behavior)
python3 -m hardstop.runners.run_demo --mode pinned
# or
hardstop demo --mode pinned
```

Expected output (clean database):

- Alert ID `ALERT-20251229-d31a370b`
- classification `2` / impact score `5`
- scope matching facility `PLANT-01`, lanes `LANE-001..003`, and six shipments
- incident evidence at `output/incidents/ALERT-20251229-d31a370b__EVT-DEMO-0001__SAFETY_PLANT-01_LANE-001.json`
  - `determinism_mode: "pinned"`
  - `determinism_context.seed`, `.timestamp_utc`, `.run_id` recorded
  - artifact hash `e36dbe8cf992b8a2e49fb2eb3d867fe9a728517fcbe6bcc19d46e66875eaa2d6`

This is the value we compare during audits/CI runs.

#### Live demo spot-check (IDs drift)

```bash
python3 -m hardstop.runners.run_demo          # or `hardstop demo`
```

Alert IDs will reflect today’s date and a new UUID suffix, and the second run will correlate to the first.  
Classification, impact score, scope, and linking notes must still match the pinned run narrative above.

For a lighter-weight regression (no SQLite needed), run the fixture-based unit test:

```bash
python3 -m pytest tests/test_demo_pipeline.py
```

### Daily Workflow

```bash
# Fetch and process new events
hardstop run --since 24h

# Check system health
hardstop doctor

# View daily brief
hardstop brief --today --since 24h

# Monitor source health
hardstop sources health

# Test a specific source
hardstop sources test <source_id> --since 72h

### Source health outputs and suppression explanations

`hardstop sources health` now emits richer diagnostics so you can interpret why a source is healthy or blocked:

- **Columns**: `score` (0-100), `health_budget_state` (`HEALTHY`, `WATCH`, `BLOCKED`), `suppression_pct` (percentage of items suppressed), plus fetch/ingest stats per source.
- **Semantics**: `HEALTHY` means the rolling failure budget is intact, `WATCH` signals the budget is nearing exhaustion, and `BLOCKED` prevents downstream phases (strict runs exit 2).
- **API parity**: The sources API (`src/hardstop/api/sources_api.py`) returns `health_budget_state` alongside each source so integrations can react to the same gating logic.

Explain suppression decisions with deterministic samples:

```bash
# Show suppression reasons and sample items for a source
hardstop sources health --explain-suppress <source_id>

# Example output
# suppression_reasons:
#   RULE-001: 3 (title contains "test")
#   RULE-007: 1 (facility mismatch)
# samples:
#   RAW-123 -> RULE-001 ("test outage")
#   RAW-129 -> RULE-007 ("facility=PLANT-99 outside scope")
```

## Usage

### CLI Commands

#### Source Management

```bash
# List all configured sources
hardstop sources list

# Test a specific source
hardstop sources test <source_id> [--since 24h] [--max-items 20] [--ingest]

# View source health table
hardstop sources health [--stale 48h] [--lookback 10] [--explain-suppress <source_id>]
```

#### Fetching and Ingestion

```bash
# Fetch items from all enabled sources
hardstop fetch [--tier global|regional|local] [--since 24h] [--max-items-per-source 10]

# Ingest fetched items into events and alerts
hardstop ingest-external [--since 24h] [--no-suppress] [--explain-suppress] [--fail-fast]

# Convenience: fetch + ingest in one command
hardstop run [--since 24h] [--stale 48h] [--strict] [--no-suppress] [--fail-fast]
```

#### Briefing

```bash
# Generate daily brief (markdown)
hardstop brief --today [--since 24h|72h|7d] [--limit 20] [--include-class0]

# Generate brief in JSON format
hardstop brief --today --format json

# Custom time window
hardstop brief --today --since 72h
```

#### Export bundles

```bash
# Export brief JSON (prints to stdout unless --out is set)
hardstop export brief --since 24h --limit 20 --out brief.json

# Export alerts as JSON or CSV
hardstop export alerts --since 24h --format json --out alerts.json
hardstop export alerts --since 24h --format csv --out alerts.csv

# Export sources health JSON
hardstop export sources --lookback 7d --stale 72h --out sources.json
```

When `--out` is supplied, Hardstop writes a sidecar `*.manifest.json` file with
config fingerprints and export hashes to support verification. The full export
schema is documented in `docs/specs/export.schema.md`.

#### Health and Diagnostics

```bash
# Run comprehensive health checks
hardstop doctor

# Initialize configuration files
hardstop init [--force]
```

### Configuration

#### Source Configuration (`config/sources.yaml`)

Define external sources with metadata. Defaults are layered:

- `defaults`: HTTP/client behavior (timeout, max items, user agent).
- `tier_defaults`: trust-aware tuning for each tier (global, regional, local) that sets `trust_tier`, `classification_floor`, and `weighting_bias`.
- Per-source overrides: anything specified on the source wins over tier defaults.

- **id**: Unique source identifier
- **type**: Source adapter type (rss, nws_alerts)
- **tier**: Global, Regional, or Local
- **url**: Source endpoint URL
- **enabled**: Whether source is active
- **trust_tier**: Reliability tier (1-3, default 2)
  - Tier 3: High trust (official sources) → +1 impact score
  - Tier 2: Medium trust (default) → no modifier
  - Tier 1: Low trust → -1 impact score
  - **Note**: Trust tier semantics are designed for supply chain sources. Future domain adapters may require different trust tier interpretations.
- **classification_floor**: Minimum alert classification (0-2, default 0). Note: Quality validation may reduce classification below this floor to prevent false positives (Policy B: quality is authoritative).
- **weighting_bias**: Impact score adjustment (-2 to +2, default 0)
- **suppress**: Per-source suppression rules

**Example:**
```yaml
tier_defaults:
  global:
    trust_tier: 3
    classification_floor: 0
    weighting_bias: 0
  regional:
    trust_tier: 2
  local:
    trust_tier: 1
    weighting_bias: -1

tiers:
  global:
    - id: nws_active_us
      type: nws_alerts
      enabled: true
      tier: global
      url: "https://api.weather.gov/alerts/active"
      trust_tier: 3
      classification_floor: 0
      weighting_bias: 0
```

#### Suppression Configuration (`config/suppression.yaml`)

Define global suppression rules to filter noise:

- **enabled**: Master switch for suppression
- **rules**: List of suppression rules
  - **id**: Unique rule identifier
  - **kind**: Match type (keyword, regex, exact)
  - **field**: Field to match (title, summary, raw_text, url, event_type, source_id, tier, any)
  - **pattern**: Pattern to match
  - **case_sensitive**: Whether matching is case-sensitive
  - **note**: Human-readable note
  - **reason_code**: Short code for reporting

**Example:**
```yaml
enabled: true
rules:
  - id: global_test_alerts
    kind: keyword
    field: any
    pattern: "test alert"
    case_sensitive: false
    note: "Common noise across multiple feeds"
```

#### Alert Quality Configuration (`hardstop.config.yaml`)

Control how network linking confidence affects alert classification to prevent false positives:

- **min_confidence_class_1**: Minimum facility confidence for "Relevant" alerts (default 0.60)
- **min_confidence_class_2**: Minimum facility confidence for "Impactful" alerts (default 0.70)
- **min_confidence_ambiguous**: Minimum confidence for ambiguous facility matches (default 0.50, requires extra evidence)
- **allow_quality_override_floor**: Whether quality validation can override source policy minimum (default true, Policy B)

**Policy B (default)**: Quality validation is authoritative. Low-confidence network matches are downgraded to prevent false positives, even if `classification_floor` would raise them. Source policy minimum can still raise from 0, but cannot override quality caps.

**Example:**
```yaml
alert_quality:
  min_confidence_class_1: 0.60  # For "Relevant" alerts
  min_confidence_class_2: 0.70  # For "Impactful" alerts
  min_confidence_ambiguous: 0.50  # For ambiguous matches
  allow_quality_override_floor: true  # Quality caps are authoritative
```

**How it works:**
- Events with low facility confidence (< 0.60) are capped at classification 0 (Interesting)
- Ambiguous facility matches (multiple facilities in same city/state) are capped at classification 1 max, requiring 2+ compensating factors
- Classification 2 alerts require both high confidence (≥ 0.70) and 2+ high-impact factors (criticality, volume, priority shipments, keywords)
- Trust tier and high-impact keywords provide partial compensation but cannot fully override low confidence

**Quality validation metadata** is exposed in `alert.evidence.diagnostics.quality_validation`:
- `max_allowed_classification`: The quality cap applied to this alert
- `high_impact_factors_count`: Number of high-impact factors detected
- `facility_confidence`: Facility linking confidence score
- `facility_provenance`: How the facility was matched (exact ID, name, city/state, ambiguous)
- `applied_policy`: "A" or "B" (quality override policy)

### Source Health Monitoring

Hardstop tracks the health of all sources:

- **Fetch Success Rate**: Percentage of successful fetches over last N runs
- **Stale Detection**: Sources that haven't succeeded in X hours
- **Ingest Metrics**: Items processed, suppressed, events created, alerts touched
- **Error Tracking**: Last error message and status code
- **Health Score & Failure Budgets**: Each source receives a deterministic 0-100 score. Falling below the failure-budget threshold marks the source as `WATCH` (warning) or `BLOCKED` (gating downstream phases).
- **Suppression Analytics**: Reason codes and samples are captured per source so noisy rules can be tuned.
- **Never-run placeholders**: Newly added sources with no `SourceRun` history appear as `BLOCKED` (score ≈30) placeholders until their first successful fetch. This is expected and prevents Hardstop from assuming a source is healthy before it runs—kick off `hardstop sources test <source_id>` to validate a new source immediately.

**Commands:**
- `hardstop sources health`: View health table for all sources
- `hardstop sources health --explain-suppress <id>`: Print suppression reason codes and samples for a source
- `hardstop sources test <id>`: Test a specific source and view results
- `hardstop doctor`: Includes source health checks and recommendations

### Exit Codes and Run Status

Hardstop runs are self-evaluating:

- **Exit Code 0 (Healthy)**: All systems functioning normally
- **Exit Code 1 (Warning)**: Some sources failing/stale, but pipeline functioning
- **Exit Code 2 (Broken)**: Critical issues (schema drift, config errors, all sources failed)

**Run Status Footer:**
After each `hardstop run`, you'll see:
```
==================================================
Run status: HEALTHY
Top issues:
  - All systems healthy
==================================================
```

Use `--strict` to treat warnings as broken (exit code 2).

## Architecture

Hardstop Runtime is built around a deterministic loop: adapters ingest bounded sets of signals, operators transform them with explicit read/write contracts, and the runtime emits fingerprinted artifacts plus run records for replay. Design goals:

- **Deterministic by default**: Strict mode disallows nondeterministic dependencies and guarantees replayability.
- **Explicit inputs/outputs**: Every operator declares the artifact types it touches and records those refs in a RunRecord.
- **Local-first + bounded**: SQLite storage, capped windows, and adapter rate limits prevent “firehose” behavior.
- **Auditable**: Artifacts, configuration hashes, and provenance are fingerprinted so the same inputs always yield the same outputs.

Layers used in practice:

1. **Ingestion Layer** – `hardstop/retrieval` adapters fetch and fingerprint signals.
2. **Decision Core** – canonicalization, noise control, correlation, and scoring operators under `hardstop/parsing`, `hardstop/suppression`, and `hardstop/alerts`.
3. **Artifact Layer** – SQLite repositories plus reporting (`hardstop/output`, `hardstop/api`) persist and render decision artifacts.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full runtime specification and operator taxonomy, and refer to [docs/specs/run-record.schema.json](docs/specs/run-record.schema.json) for the RunRecord contract used by every operator execution.

### Run Records in Practice

Running `hardstop run` now emits a RunRecord JSON document under `run_records/`. Each record includes the merged configuration fingerprint, execution mode (strict vs best-effort), hashed references to the run group id, and the resolved run-status diagnostics. The schema matches `docs/specs/run-record.schema.json`, so you can validate or replay runs in downstream tooling by pointing a JSON Schema validator at the generated files.

For deterministic or replayed runs, you can supply your own `run_id`, `started_at`, and `ended_at` values plus an optional `canonicalize_time` helper to round timestamps (e.g., strip microseconds) or pin them to test fixtures. When you need stable filenames (CI snapshots), pass `filename_basename` to `emit_run_record` so the record does not embed wall-clock timestamps. If an operator uses nondeterministic inputs, populate `best_effort` metadata (seed, model version, notes) so replays document the entropy sources.

## Execution Plan

We translate the architecture above into a prioritized execution plan so every
change lands in the right order and keeps documentation in sync. The detailed
plan lives in [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md); the high-level
bands are:

1. **P0 – Deterministic kernel hardening:** finish RunRecord coverage, config
   fingerprinting, strict/best-effort enforcement, and golden-run fixtures so
   every operator remains replayable.
2. **P1 – Source reliability & health:** revamp the source registry, enhance
   health scoring and suppression observability, and wire failure budgets into
   `hardstop sources health` + `hardstop doctor`.
3. **P2 – Decision core & artifact quality:** refactor canonicalization,
   improve impact scoring explanations, add correlation evidence, and ship an
   incident replay CLI.
4. **P3 – Reporting & integrations:** deliver the next-generation briefs,
   export bundles, and read-only Slack/Linear sinks plus CI-ready run signals.

Each release should confirm which priority band is active and update this file,
`docs/ARCHITECTURE.md`, and the execution plan together.

## Requirements

- Python 3.10+
- SQLite (included with Python)
- Network access for fetching external sources

## Project Structure

```
hardstop-agent/
├── README.md
├── CHANGELOG.md
├── pyproject.toml
├── config/
│   ├── sources.yaml          # External source definitions
│   ├── sources.example.yaml  # Example source config
│   ├── suppression.yaml      # Global suppression rules
│   └── suppression.example.yaml  # Example suppression config
├── docs/
│   └── ARCHITECTURE.md       # Detailed architecture documentation
├── src/hardstop/
│   ├── retrieval/            # External source retrieval
│   ├── suppression/          # Suppression engine
│   ├── parsing/              # Event normalization and entity linking
│   ├── database/             # SQLite storage and migrations
│   ├── alerts/               # Alert generation and correlation
│   ├── output/               # Daily brief generation
│   ├── ops/                  # Operational utilities (run status)
│   └── runners/              # Executable workflows
└── tests/                    # Test suite
```

Dependency management lives in `pyproject.toml`, with a hashed `requirements.lock.txt` generated via `pip-compile` to guarantee reproducible installs.

## Key Documentation & Audits

- `docs/ARCHITECTURE.md` — deep dive into adapters, operators, and runtime boundaries.
- `docs/EXECUTION_PLAN.md` — living roadmap that explains which priority band (P0–P3) is currently active.
- `docs/P2_READINESS.md` — readiness checklist that ties release criteria back to deterministic guarantees.
- `docs/CSV_CONTRACT.md` — client network CSV format specification for facilities, lanes, and shipments.
- `docs/audit/Contract_Index.md` — index of the current "contracts" (README claims) mapped to enforcing code/tests.
- `docs/archive/audit/2026-01/` — archived reproducibility logs (`Repro_Log_*`), dependency reports, schema reviews, and the [`CLI_Contract_03_README_vs_Reality.md`](docs/archive/audit/2026-01/CLI_Contract_03_README_vs_Reality.md) gap analysis that validates every command documented here.
- `docs/specs/run-record.schema.json` — JSON Schema for emitted run records (useful for downstream tooling or CI validation).

Use these references when filing issues or extending the system so the README always stays in lock-step with the authoritative specs.

## Support & Troubleshooting

- Run `hardstop doctor` first; it validates PATH, config files, SQLite health, and source failure budgets in one pass.
- Use `hardstop sources health --explain-suppress <source_id>` to inspect deterministic suppression reasons before loosening rules.
- Capture golden artifacts with `hardstop demo --mode pinned` plus `tools/validate_run_records.py run_records/<file>.json` when reporting determinism regressions.
- Reference the audit logs under `docs/archive/audit/2026-01/` or rerun the scenarios in `Repro_Log_0*` to confirm whether an observed behavior is expected.
- When logging bugs, attach the relevant `run_records/` JSON and note whether the environment followed the locked install instructions above.

## Contributing

Contributions welcome! See the codebase for examples of:
- Adding new source adapters
- Extending suppression rules
- Adding new alert classification logic
- Improving health checks

## License

Hardstop is distributed under the [Hardstop Business License (SBL-1.0)](LICENSE).
You may evaluate, research, or personally experiment with the code at no cost,
but any production or revenue-generating use requires a commercial agreement
with WhatsYourWhy, Inc. On January 1, 2029 this codebase is scheduled to
dual-license under Apache 2.0. See [docs/LICENSING.md](docs/LICENSING.md) for
the full licensing strategy and monetization recommendations.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and detailed release notes.
