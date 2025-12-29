# Sentinel

**Sentinel** is a local-first, domain-agnostic event → risk → alert engine designed for personal daily driver use. It monitors external sources (RSS feeds, government APIs, alerts) and generates actionable risk alerts by linking events to your operational network.

## What is Sentinel?

Sentinel solves the problem of information overload from multiple alert sources. Instead of manually checking dozens of feeds, Sentinel:

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

## Status

**v1.0** — Production-shaped for personal daily driver use
- Self-evaluating runs with exit codes (healthy/warning/broken)
- Source health tracking and monitoring
- Guaranteed failure reporting (no silent failures)
- Smooth first-time setup with `sentinel init`
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
- **Health Checks**: Comprehensive `sentinel doctor` command with actionable recommendations

### Exit Codes

Sentinel runs are self-evaluating and exit with appropriate codes:

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

# Install Sentinel
pip install -e .

# For contributors (includes pytest and dev tools):
pip install -e ".[dev]"
```

### First-Time Setup

```bash
# Initialize configuration files from examples
sentinel init

# Review and customize config files
# - config/sources.yaml: Configure your sources
# - config/suppression.yaml: Configure suppression rules

# Load network data (required for network linking)
sentinel ingest

# Run your first fetch and ingest
sentinel run --since 24h

# Generate your first brief
sentinel brief --today --since 24h
```

### Daily Workflow

```bash
# Fetch and process new events
sentinel run --since 24h

# Check system health
sentinel doctor

# View daily brief
sentinel brief --today --since 24h

# Monitor source health
sentinel sources health

# Test a specific source
sentinel sources test <source_id> --since 72h
```

## Usage

### CLI Commands

#### Source Management

```bash
# List all configured sources
sentinel sources list

# Test a specific source
sentinel sources test <source_id> [--since 24h] [--max-items 20] [--ingest]

# View source health table
sentinel sources health [--stale 48h] [--lookback 10]
```

#### Fetching and Ingestion

```bash
# Fetch items from all enabled sources
sentinel fetch [--tier global|regional|local] [--since 24h] [--max-items-per-source 10]

# Ingest fetched items into events and alerts
sentinel ingest-external [--since 24h] [--no-suppress] [--explain-suppress] [--fail-fast]

# Convenience: fetch + ingest in one command
sentinel run [--since 24h] [--stale 48h] [--strict] [--no-suppress] [--fail-fast]
```

#### Briefing

```bash
# Generate daily brief (markdown)
sentinel brief --today [--since 24h|72h|7d] [--limit 20] [--include-class0]

# Generate brief in JSON format
sentinel brief --today --format json

# Custom time window
sentinel brief --today --since 72h
```

#### Health and Diagnostics

```bash
# Run comprehensive health checks
sentinel doctor

# Initialize configuration files
sentinel init [--force]
```

### Configuration

#### Source Configuration (`config/sources.yaml`)

Define external sources with metadata:

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

Sentinel tracks the health of all sources:

- **Fetch Success Rate**: Percentage of successful fetches over last N runs
- **Stale Detection**: Sources that haven't succeeded in X hours
- **Ingest Metrics**: Items processed, suppressed, events created, alerts touched
- **Error Tracking**: Last error message and status code

**Commands:**
- `sentinel sources health`: View health table for all sources
- `sentinel sources test <id>`: Test a specific source and view results
- `sentinel doctor`: Includes source health checks and recommendations

### Exit Codes and Run Status

Sentinel runs are self-evaluating:

- **Exit Code 0 (Healthy)**: All systems functioning normally
- **Exit Code 1 (Warning)**: Some sources failing/stale, but pipeline functioning
- **Exit Code 2 (Broken)**: Critical issues (schema drift, config errors, all sources failed)

**Run Status Footer:**
After each `sentinel run`, you'll see:
```
==================================================
Run status: HEALTHY
Top issues:
  - All systems healthy
==================================================
```

Use `--strict` to treat warnings as broken (exit code 2).

## Architecture

Sentinel Runtime is built around a deterministic loop: adapters ingest bounded sets of signals, operators transform them with explicit read/write contracts, and the runtime emits fingerprinted artifacts plus run records for replay. Design goals:

- **Deterministic by default**: Strict mode disallows nondeterministic dependencies and guarantees replayability.
- **Explicit inputs/outputs**: Every operator declares the artifact types it touches and records those refs in a RunRecord.
- **Local-first + bounded**: SQLite storage, capped windows, and adapter rate limits prevent “firehose” behavior.
- **Auditable**: Artifacts, configuration hashes, and provenance are fingerprinted so the same inputs always yield the same outputs.

Layers used in practice:

1. **Ingestion Layer** – `sentinel/retrieval` adapters fetch and fingerprint signals.
2. **Decision Core** – canonicalization, noise control, correlation, and scoring operators under `sentinel/parsing`, `sentinel/suppression`, and `sentinel/alerts`.
3. **Artifact Layer** – SQLite repositories plus reporting (`sentinel/output`, `sentinel/api`) persist and render decision artifacts.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full runtime specification and operator taxonomy, and refer to [docs/specs/run-record.schema.json](docs/specs/run-record.schema.json) for the RunRecord contract used by every operator execution.

## Requirements

- Python 3.8+
- SQLite (included with Python)
- Network access for fetching external sources

## Project Structure

```
sentinel-agent/
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
├── src/sentinel/
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

[Add your license here]

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and detailed release notes.
