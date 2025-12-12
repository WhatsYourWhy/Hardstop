# Sentinel Architecture

## Overview

Sentinel is a local-first, domain-agnostic event → risk → alert engine. It processes external events (news, alerts, reports) and generates actionable risk alerts by linking events to your operational network (facilities, lanes, shipments).

## System Flow

```
Event Input → Normalization → Entity Linking → Alert Generation → Output
     ↓              ↓              ↓                ↓              ↓
  JSON/CSV      Canonical      Database         Risk            JSON/
  RSS (future)  Event Format   Queries         Assessment      Markdown
```

## Core Components

### 1. Ingestion (`sentinel/ingestion/`)

**Purpose:** Load structured data into the system.

- **`file_ingestor.py`**: Reads CSV files (facilities, lanes, shipments) and inserts into SQLite
- **`json_ingestor.py`**: (Planned) Ingest JSON events from APIs or files
- **`rss_ingestor.py`**: (Planned) Monitor RSS feeds for news events

**Key Design:**
- Idempotent operations (uses `merge()` to handle duplicates)
- Configurable file paths via `sentinel.config.yaml`
- Logs progress for debugging

### 2. Parsing (`sentinel/parsing/`)

**Purpose:** Transform raw events into canonical format and link to network data.

- **`normalizer.py`**: Converts raw JSON events into canonical `Event` dict format
- **`entity_extractor.py`**: 
  - Links events to facilities by location (city/state) or facility ID
  - Finds related shipments and lanes from the database
  - Populates `event["facilities"]`, `event["shipments"]`, `event["lanes"]`

**Key Design:**
- Location extraction from text (e.g., "Avon, Indiana")
- Fuzzy matching for facility lookup
- Date-aware shipment filtering (upcoming shipments only)

### 3. Database (`sentinel/database/`)

**Purpose:** Local SQLite storage for network data and events.

- **`schema.py`**: SQLAlchemy models for:
  - `Facility`: Manufacturing plants, distribution centers
  - `Lane`: Shipping routes between facilities
  - `Shipment`: Active and upcoming shipments
  - `Event`: Ingested events
  - `Alert`: Generated risk alerts
- **`sqlite_client.py`**: Session management and engine creation

**Key Design:**
- Local-first: Single SQLite file (`sentinel.db`)
- Auto-creates tables on first use
- No external dependencies (no cloud, no network)

### 4. Alerts (`sentinel/alerts/`)

**Purpose:** Generate structured risk alerts from events.

- **`alert_models.py`**: Pydantic models for `SentinelAlert`, `AlertScope`, `AlertImpactAssessment`
- **`alert_builder.py`**: Heuristic-based alert generation (v1)
  - Maps event severity to alert priority
  - Populates scope from linked entities
  - Generates recommended actions

**Key Design:**
- Structured output (JSON-serializable)
- Extensible for future LLM-based reasoning
- Clear separation between data models and business logic

### 5. Runners (`sentinel/runners/`)

**Purpose:** Executable scripts for common workflows.

- **`run_demo.py`**: End-to-end demo pipeline
- **`load_network.py`**: Load CSV data into database

**Key Design:**
- Each runner is a standalone `main()` function
- Can be run as modules (`python -m sentinel.runners.run_demo`) or via CLI (`sentinel demo`)

## Data Flow

### Event Processing Pipeline

1. **Input**: Raw event JSON (e.g., from news feed, API, manual entry)
2. **Normalization**: Convert to canonical format with standard fields
3. **Entity Linking**: 
   - Extract location from text or use provided city/state
   - Query database for matching facilities
   - Find lanes originating from those facilities
   - Find upcoming shipments on those lanes
4. **Alert Generation**: 
   - Assess risk based on event type and severity
   - Build alert with scope (facilities, shipments, lanes)
   - Generate recommended actions
5. **Output**: Structured alert (JSON, future: Markdown brief)

### Network Data Loading

1. **CSV Files**: Facilities, lanes, shipments in standard format
2. **Ingestion**: `file_ingestor.py` reads and validates
3. **Database**: Inserts/updates SQLite tables
4. **Verification**: Logs counts and any errors

## Design Principles

### Local-First

- All data stored locally in SQLite
- No cloud dependencies
- Fast iteration and testing
- Easy to embed in other systems

### Domain-Agnostic

- Core engine is domain-neutral
- Domain-specific logic in "domain packs" (currently: supply chain)
- Easy to extend for other domains (security, finance, operations)

### Modular

- Clear separation of concerns
- Each component can be tested independently
- Easy to swap implementations (e.g., heuristic alerts → LLM-based alerts)

### Extensible

- Schema supports new event types
- Alert models can grow without breaking changes
- Runners can be added for new workflows

## Future Enhancements

- **LLM Agent**: Replace heuristic alert builder with LLM-based reasoning
- **RSS Ingestion**: Monitor news feeds automatically
- **Daily Brief**: Summarize alerts and events
- **Markdown Output**: Human-readable alert reports
- **Event Storage**: Persist events to database for historical analysis

