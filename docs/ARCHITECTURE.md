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
  - `Event`: Ingested events (schema exists, persistence planned)
  - `Alert`: Generated risk alerts (with correlation and brief fields)
- **`sqlite_client.py`**: Session management and engine creation
- **`alert_repo.py`**: Repository functions for alert persistence and correlation queries
- **`migrate.py`**: Additive migration helper for schema evolution

**Key Design:**
- Local-first: Single SQLite file (`sentinel.db`)
- Auto-creates tables on first use
- No external dependencies (no cloud, no network)

### 4. Alerts (`sentinel/alerts/`)

**Purpose:** Generate structured risk alerts from events.

- **`alert_models.py`**: Pydantic models for `SentinelAlert`, `AlertScope`, `AlertImpactAssessment`, `AlertEvidence`
- **`alert_builder.py`**: Heuristic-based alert generation
  - Maps network impact score to alert classification (0=Interesting, 1=Relevant, 2=Impactful)
  - Populates scope from linked entities
  - Generates recommended actions
  - Separates decisions (classification, summary, scope) from evidence (diagnostics, linking notes)
  - Implements alert correlation logic to update existing alerts or create new ones based on a correlation key
- **`impact_scorer.py`**: Calculates network impact score (0-10) based on facility criticality, lane volume, shipment priority, event type, and ETA proximity
- **`correlation.py`**: Builds deterministic correlation keys for alert deduplication

**Key Design:**
- Structured output (JSON-serializable)
- Clear decision/evidence boundary (decisions vs. what system believes)
- Extensible for future LLM-based reasoning (LLM output goes in evidence, not decisions)
- Deterministic classification based on network impact scoring
- Supports alert correlation for deduplication and tracking evolving risks

### 5. Alert Correlation (`sentinel/alerts/correlation.py`)

**Purpose:** Deduplicate and update alerts based on correlation keys.

- **`correlation.py`**: Builds deterministic correlation keys from event type, facility, and lane
- **Correlation Logic**:
  - Key format: `BUCKET|FACILITY|LANE` (e.g., "SPILL|PLANT-01|LANE-001")
  - 7-day lookback window for finding existing alerts
  - Updates existing alerts instead of creating duplicates
  - Tracks `correlation_action` ("CREATED" vs "UPDATED") as a fact about ingest time

**Key Design:**
- Deterministic key generation (same event type + facility + lane = same key)
- Stores correlation metadata in database (key, action, timestamps)
- Updates scope and impact_score when alert is correlated
- Requires database session (correlation is a persistence feature)

### 6. Daily Brief (`sentinel/output/daily_brief.py`)

**Purpose:** Generate summaries of recent alerts for human consumption.

- **Query Logic**:
  - Finds alerts where `last_seen_utc >= cutoff OR first_seen_utc >= cutoff`
  - Sorts by: classification DESC, impact_score DESC, update_count DESC, last_seen_utc DESC
  - Filters by time window (24h, 72h, 7d)
  - Optionally excludes classification 0 alerts

- **Output Formats**:
  - Markdown: Human-readable with sections for top impact, updated, new alerts
  - JSON: Structured data for programmatic consumption

**Key Design:**
- Deterministic (no LLM, pure query + render)
- Fast (direct SQL queries with proper indexing)
- Requires database (queries stored alerts)

### 7. Database Migrations (`sentinel/database/migrate.py`)

**Purpose:** Additive schema changes for SQLite.

- **Strategy**: Additive-only migrations (add columns, never remove)
- **Storage**: ISO 8601 strings for datetime fields (lexicographically sortable)
- **Safety**: Checks for column existence before adding
- **Usage**: Called automatically before operations that need new columns

**Key Design:**
- Local-first: No external migration tools needed
- Safe: Idempotent (can run multiple times)
- Simple: Direct SQLite ALTER TABLE statements

### 8. Runners (`sentinel/runners/`)

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
   - Calculate network impact score (0-10)
   - Map score to classification (0=Interesting, 1=Relevant, 2=Impactful)
   - Build alert with scope (facilities, shipments, lanes)
   - Generate recommended actions
5. **Correlation**: 
   - Build correlation key from event type, facility, lane
   - Check for existing alerts within 7-day window
   - Update existing or create new alert
6. **Output**: Structured alert (JSON) or daily brief (Markdown/JSON)

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
- **RSS Ingestion**: Monitor news feeds automatically (planned v0.6)
- **JSON Event Ingestion**: Batch processing of JSON events (planned v0.6)
- **Event Storage**: Persist events to database for historical analysis (schema exists, not yet active)

