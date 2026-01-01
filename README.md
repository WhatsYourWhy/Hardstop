# Hardstop

**Hardstop** is a local-first, domain-agnostic event → risk → alert engine designed for personal daily driver use. It monitors external sources (RSS feeds, government APIs, alerts) and generates actionable risk alerts by linking events to your operational network.

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
- **Alert Generation**: Deterministic risk assessment using network impact scoring with trust tier modifiers
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

### Installation

```bash
# Create virtual environment
python -m venv .venv

# Activate (Linux/Mac)
source .venv/bin/activate

# Activate (Windows PowerShell)
# If you get an execution policy error, run this first:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

# Install Hardstop
pip install -e .

# For contributors (includes pytest and dev tools):
pip install -e ".[dev]"
```

### First-Time Setup

```bash
# Initialize configuration files from examples
hardstop init

# Review and customize config files
# - config/sources.yaml: Configure your sources
# - config/suppression.yaml: Configure suppression rules

# Load network data (required for network linking)
hardstop ingest

# Run your first fetch and ingest
hardstop run --since 24h

# Generate your first brief
hardstop brief --today --since 24h
```

### Demo Pipeline (P0 verification)

Use the baked-in demo workflow when you need a deterministic sanity check of the network linker + alert builder stack.

```bash
# Install runtime + tests (once per environment)
python3 -m pip install -e ".[dev]"

# Load the golden-path network data into SQLite (idempotent)
python3 -m hardstop.runners.load_network

# Execute the end-to-end demo pipeline (reads event fixture, links network, builds alert)
python3 -m hardstop.runners.run_demo
```

You should see a single alert emitted (currently `ALERT-20251229-bb25eb7a`) with:

- classification `2` / impact score `5`
- scope matching facility `PLANT-01`, lanes `LANE-001..003`, and six shipments
- linking notes that walk through facility → lane → shipment matching and correlation key `SAFETY|PLANT-01|LANE-001`

For a lighter-weight regression, you can run just the fixture-based unit test:

```bash
python3 -m pytest tests/test_demo_pipeline.py
```

Both commands are deterministic; if they diverge from the outputs above, capture the stdout and open an issue.

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
- **classification_floor**: Minimum alert classification (0-2, default 0)
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

### Source Health Monitoring

Hardstop tracks the health of all sources:

- **Fetch Success Rate**: Percentage of successful fetches over last N runs
- **Stale Detection**: Sources that haven't succeeded in X hours
- **Ingest Metrics**: Items processed, suppressed, events created, alerts touched
- **Error Tracking**: Last error message and status code
- **Health Score & Failure Budgets**: Each source receives a deterministic 0-100 score. Falling below the failure-budget threshold marks the source as `WATCH` (warning) or `BLOCKED` (gating downstream phases).
- **Suppression Analytics**: Reason codes and samples are captured per source so noisy rules can be tuned.

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

- Python 3.8+
- SQLite (included with Python)
- Network access for fetching external sources

## Project Structure

```
hardstop-agent/
├── README.md
├── CHANGELOG.md
├── pyproject.toml
├── requirements.txt
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
