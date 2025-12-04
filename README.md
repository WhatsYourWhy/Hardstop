# Sentinel Agent

**Sentinel** is a local-first, domain-agnostic event → risk → alert engine.

The initial domain pack focuses on **supply chain risk** (facilities, lanes, shipments), but the architecture is designed to work for other domains (security, finance, operations) by swapping out domain rules.

## Status

- v0.1 — Scaffolding & demo pipeline

- Local Python CLI prototype

- SQLite storage, CSV + JSON ingestion, basic alert generation

## Features (v1 scope)

- Ingest structured and semi-structured inputs (CSV, JSON, RSS later)

- Normalize into canonical `Event` objects

- Run an "agent" that classifies risk and builds `Alert` objects

- Render alerts and a simple daily brief as markdown/JSON

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
│       │   └── entity_extractor.py
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── sentinel_agent.py
│       │   ├── llm_client.py
│       │   └── prompts/
│       │       └── sentinel_v1_prompt.txt
│       ├── database/
│       │   ├── __init__.py
│       │   ├── schema.py
│       │   └── sqlite_client.py
│       ├── alerts/
│       │   ├── __init__.py
│       │   ├── alert_models.py
│       │   └── alert_builder.py
│       ├── output/
│       │   ├── __init__.py
│       │   ├── daily_brief.py
│       │   └── render_markdown.py
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

source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# run demo pipeline

python -m sentinel.runners.run_demo

```

## Usage

### Running the Demo Pipeline

The demo pipeline (`python -m sentinel.runners.run_demo`) demonstrates the core Sentinel workflow:

1. Loads a sample JSON event from `tests/fixtures/event_spill.json`
2. Normalizes the event into a canonical format
3. Attaches dummy entity associations (facilities, shipments)
4. Builds a basic risk alert using heuristics
5. Outputs the alert as formatted JSON

The demo provides a quick way to verify the installation and see the end-to-end flow from event ingestion to alert generation.
