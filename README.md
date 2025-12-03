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

## Quickstart

```bash

# create venv and install

python -m venv .venv

source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# run demo pipeline

python -m sentinel.runners.run_demo

```
