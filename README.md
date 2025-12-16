# Sentinel Agent

**Sentinel** is a local-first, domain-agnostic event → risk → alert engine.

The initial domain pack focuses on **supply chain risk** (facilities, lanes, shipments), but the architecture is designed to work for other domains (security, finance, operations) by swapping out domain rules.

## Status

- **v0.5** — Current implementation
  - Event normalization and entity linking
  - Deterministic alert generation with network impact scoring
  - Alert correlation (deduplication over 7-day window)
  - Daily brief generation (markdown/JSON)
  - Local SQLite storage with additive migrations

## Features

### Core Capabilities

- **Event Processing**: Normalize raw events into canonical format
- **Network Linking**: Automatically link events to facilities, lanes, and shipments
- **Alert Generation**: Deterministic risk assessment using network impact scoring
- **Alert Correlation**: Deduplicate and update alerts based on correlation keys
- **Daily Brief**: Generate summaries of recent alerts (markdown or JSON)

### Database Requirements

**Requires Database:**
- `sentinel demo` — Needs DB for network linking and alert correlation
- `sentinel brief` — Needs DB to query stored alerts
- `sentinel ingest` — Needs DB to store network data

**Works Without Database:**
- Alert generation can fall back to `severity_guess` if no session provided
- Event normalization (pure transformation, no DB needed)

## Project Structure

```
sentinel-agent/
├── README.md
├── pyproject.toml
├── requirements.txt
├── sentinel.config.yaml
├── .gitignore
├── docs/
│   ├── SPEC_SENTINEL_V1.md
│   └── ARCHITECTURE.md
├── src/
│   └── sentinel/
│       ├── __init__.py
│       ├── config/
│       │   ├── __init__.py
│       │   └── loader.py
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── file_ingestor.py
│       │   ├── json_ingestor.py
│       │   └── rss_ingestor.py
│       ├── parsing/
│       │   ├── __init__.py
│       │   ├── normalizer.py
│       │   ├── entity_extractor.py
│       │   └── network_linker.py
│       ├── database/
│       │   ├── __init__.py
│       │   ├── schema.py
│       │   ├── sqlite_client.py
│       │   ├── alert_repo.py
│       │   └── migrate.py
│       ├── alerts/
│       │   ├── __init__.py
│       │   ├── alert_models.py
│       │   ├── alert_builder.py
│       │   ├── impact_scorer.py
│       │   └── correlation.py
│       ├── output/
│       │   ├── __init__.py
│       │   └── daily_brief.py
│       ├── runners/
│       │   ├── __init__.py
│       │   └── run_demo.py
│       └── utils/
│           ├── __init__.py
│           ├── id_generator.py
│           └── logging.py
└── tests/
    ├── __init__.py
    ├── test_demo_pipeline.py
    └── fixtures/
        ├── facilities.csv
        ├── lanes.csv
        ├── shipments_snapshot.csv
        └── event_spill.json
```

## Quickstart

```bash
# create venv and install
python -m venv .venv

# Activate virtual environment
# On Linux/Mac:
source .venv/bin/activate

# On Windows (PowerShell):
# If you get an execution policy error, run this first:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

pip install -e .

# For contributors (includes pytest and other dev tools):
pip install -e ".[dev]"

# Load network data (required for demo and brief)
sentinel ingest

# Run demo pipeline
sentinel demo

# Generate daily brief
sentinel brief --today
```

## Usage

### CLI Commands

Sentinel provides a simple CLI interface:

```bash
# Run the demo pipeline (requires DB with network data)
sentinel demo

# Load network data from CSV files (requires DB)
sentinel ingest

# Generate daily brief (requires DB with alerts)
sentinel brief --today

# Brief with custom options
sentinel brief --today --since 72h --format json --limit 50
```

### Running the Demo Pipeline

The demo pipeline (`sentinel demo`) demonstrates the core Sentinel workflow:

1. Loads a sample JSON event from `tests/fixtures/event_spill.json`
2. Normalizes the event into a canonical format
3. Links the event to network data (facilities, lanes, shipments) from the database
4. Builds a risk alert using network impact scoring
5. Correlates with existing alerts (if any) or creates new alert
6. Outputs the alert as formatted JSON

**Prerequisites:** Run `sentinel ingest` first to load network data.

### Loading Network Data

Before running the demo or generating briefs, load your network data:

```bash
sentinel ingest
```

This reads CSV files from `tests/fixtures/` (or paths specified in `sentinel.config.yaml`) and loads them into SQLite. The demo will then use this real network data to link events to facilities and shipments.

### Daily Brief

Generate a summary of recent alerts:

```bash
# Basic usage (last 24 hours, markdown)
sentinel brief --today

# Custom time window
sentinel brief --today --since 72h

# JSON output
sentinel brief --today --format json

# Include classification 0 alerts
sentinel brief --today --include-class0

# Custom limit
sentinel brief --today --limit 50
```

The brief shows:
- Top impactful alerts (classification 2)
- Updated alerts (correlated to existing)
- New alerts (newly created)
- Summary counts by classification

**Note:** Brief requires alerts to be persisted (created via `sentinel demo` or alert builder with session).
