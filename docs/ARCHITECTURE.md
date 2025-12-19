# Sentinel Architecture

## Overview

Sentinel is a local-first, domain-agnostic event → risk → alert engine. It processes external events (news, alerts, reports) and generates actionable risk alerts by linking events to your operational network (facilities, lanes, shipments).

## System Flow

```
External Sources → Fetch → Raw Items → Normalize → Suppression → Entity Linking → Alert Generation → Output
     ↓              ↓          ↓           ↓            ↓              ↓                ↓              ↓
  RSS/NWS/FDA   Rate-Limited  Storage   Canonical    Rule Check    Database         Risk            JSON/
  API/Feeds     HTTP Client   (Dedup)   Event        (v0.8)        Queries          Assessment      Markdown
```

**External Pipeline (v0.6+):**
- Fetch raw items from configured sources
  - Create FETCH SourceRun records per source (v0.9)
  - Track status, status_code, error, duration, items_fetched, items_new
- Store in `raw_items` table with deduplication
- Normalize into canonical event format
- Evaluate suppression rules (v0.8)
- Link to network entities
- Generate alerts with trust tier weighting (v0.7)
  - Create INGEST SourceRun records per source (v0.9)
  - Track items_processed, items_suppressed, items_events_created, items_alerts_touched
  - Guarantee SourceRun creation even on failure (v1.0)
- Evaluate run status and exit with appropriate code (v1.0)
- Output to brief with tier-aware grouping

## Core Components

### 1. External Retrieval (`sentinel/retrieval/`) — v0.6+

**Purpose:** Fetch events from external public sources.

- **`adapters.py`**: Source adapters for different formats
  - `RSSAdapter`: RSS/Atom feed parsing
  - `NWSAdapter`: NWS Alerts API (CAP/Atom format)
  - `FEMAAdapter`: FEMA/IPAWS feeds (disabled by default)
- **`fetcher.py`**: Rate-limited HTTP client
  - Per-host rate limiting with jitter
  - Exponential backoff for retries
  - Graceful error handling (404s, network errors)

**Key Design:**
- Pluggable adapter system (easy to add new source types)
- Deduplication based on `canonical_id` and `content_hash`
- Time-based filtering (`--since` flag)
- Status tracking (NEW, NORMALIZED, FAILED, SUPPRESSED)

### 2. Source Health Tracking (`sentinel/database/source_run_repo.py`) — v0.9

**Purpose:** Monitor the health and reliability of external sources.

- **`SourceRun` Model**: Tracks fetch and ingest operations per source
  - `run_group_id`: UUID linking related FETCH and INGEST runs
  - `phase`: FETCH or INGEST
  - `status`: SUCCESS or FAILURE
  - `status_code`: HTTP status code (for FETCH phase)
  - `error`: Error message (truncated to 1000 chars)
  - `duration_seconds`: Operation duration
  - Metrics: `items_fetched`, `items_new`, `items_processed`, `items_suppressed`, `items_events_created`, `items_alerts_touched`
- **Repository Functions**:
  - `create_source_run()`: Create run records with metrics
  - `list_recent_runs()`: Query recent runs with filters
  - `get_source_health()`: Calculate health metrics for a source
  - `get_all_source_health()`: Calculate health for all sources

**Key Design:**
- Two-phase tracking: Separate FETCH and INGEST records per source
- `run_group_id` links related operations from a single `sentinel run` execution
- Health metrics: success rate, stale detection, last error, last status code
- Guaranteed records: Every fetch and ingest operation creates a SourceRun (v1.0)
- Zero items = SUCCESS: Quiet successes (0 items fetched) are still marked SUCCESS

**Health Metrics:**
- Success rate: Percentage of successful FETCH runs over last N runs
- Stale detection: Sources that haven't succeeded in X hours
- Last error: Most recent error message and status code
- Ingest summary: Items processed, suppressed, events created, alerts touched

### 3. Run Status Evaluation (`sentinel/ops/run_status.py`) — v1.0

**Purpose:** Self-evaluating runs with exit codes for automation and monitoring.

- **`evaluate_run_status()` Function**: Deterministic evaluation of run health
  - Returns exit code (0=healthy, 1=warning, 2=broken) and status messages
  - Checks config errors, schema drift, source failures, ingest crashes
  - Provides actionable status messages (top 1-3 for display)

**Exit Code Rules:**
- **Broken (2)** if:
  - Config parse error (sources.yaml or suppression.yaml)
  - Schema drift detected for required tables/columns
  - Zero sources enabled (misconfig)
  - All enabled sources failed fetch (no successes) AND none fetched quietly
  - Ingest crashed before processing any source
- **Warning (1)** if:
  - Some enabled sources failed fetch
  - Some enabled sources are stale (no success within threshold)
  - Ingest failure for one or more sources
  - Suppression config loads but has disabled state or duplicate IDs warning
- **Healthy (0)** if:
  - Config valid
  - Schema ok
  - At least one enabled source fetched successfully OR had "quiet success"
  - Ingest ran for at least one source without fatal error

**Key Design:**
- Deterministic: Same conditions = same exit code
- Actionable: Status messages explain what's wrong
- Strict mode: `--strict` flag treats warnings as broken (exit code 2)
- Integration: Called by `cmd_run()` after fetch and ingest phases

### 4. Suppression (`sentinel/suppression/`) — v0.8

**Purpose:** Filter noisy events using configurable rules.

- **`models.py`**: Pydantic models for suppression rules and results
  - `SuppressionRule`: Rule definition (keyword, regex, exact)
  - `SuppressionResult`: Evaluation result with matched rules
- **`engine.py`**: Rule evaluation logic
  - Field-specific matching (title, summary, raw_text, url, event_type, source_id, tier, any)
  - Case-sensitive and case-insensitive matching
  - Global rules evaluated first, then per-source rules
  - Collects all matched rules (not just first match)

**Key Design:**
- Deterministic evaluation (same input = same result)
- Transparent (suppressed items counted and reported)
- Auditable (all suppression metadata stored in DB)
- Composable (global + per-source rules both apply)
- Safe (suppression prevents alert creation but creates events for audit)

### 5. Ingestion (`sentinel/ingestion/`)

**Purpose:** Load structured data into the system.

- **`file_ingestor.py`**: Reads CSV files (facilities, lanes, shipments) and inserts into SQLite
- **`json_ingestor.py`**: (Planned) Ingest JSON events from APIs or files
- **`rss_ingestor.py`**: (Planned) Monitor RSS feeds for news events

**Key Design:**
- Idempotent operations (uses `merge()` to handle duplicates)
- Configurable file paths via `sentinel.config.yaml`
- Logs progress for debugging

### 6. Parsing (`sentinel/parsing/`)

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

### 7. Database (`sentinel/database/`)

**Purpose:** Local SQLite storage for network data and events.

- **`schema.py`**: SQLAlchemy models for:
  - `Facility`: Manufacturing plants, distribution centers
  - `Lane`: Shipping routes between facilities
  - `Shipment`: Active and upcoming shipments
  - `RawItem`: Fetched items from external sources (v0.6+)
  - `Event`: Ingested events (with external source metadata, trust tier, suppression metadata)
  - `Alert`: Generated risk alerts (with correlation, brief fields, tier, trust_tier, source_id)
  - `SourceRun`: Health tracking records for fetch and ingest operations (v0.9)
- **`sqlite_client.py`**: Session management and engine creation
- **`alert_repo.py`**: Repository functions for alert persistence and correlation queries
- **`event_repo.py`**: Repository functions for event persistence (v0.6+)
- **`raw_item_repo.py`**: Repository functions for raw item storage and retrieval (v0.6+)
- **`source_run_repo.py`**: Repository functions for source health tracking (v0.9)
- **`migrate.py`**: Additive migration helper for schema evolution

**Key Design:**
- Local-first: Single SQLite file (`sentinel.db`)
- Auto-creates tables on first use
- No external dependencies (no cloud, no network)

### 8. Alerts (`sentinel/alerts/`)

**Purpose:** Generate structured risk alerts from events.

- **`alert_models.py`**: Pydantic models for `SentinelAlert`, `AlertScope`, `AlertImpactAssessment`, `AlertEvidence`
  - `AlertEvidence` includes `source` field for external source metadata (v0.6+)
- **`alert_builder.py`**: Heuristic-based alert generation
  - Maps network impact score to alert classification (0=Interesting, 1=Relevant, 2=Impactful)
  - Applies trust tier modifiers and weighting bias (v0.7)
  - Enforces classification floor (v0.7)
  - Populates scope from linked entities
  - Generates recommended actions
  - Separates decisions (classification, summary, scope) from evidence (diagnostics, linking notes, source)
  - Implements alert correlation logic to update existing alerts or create new ones based on a correlation key
  - Stores tier, source_id, and trust_tier in alerts (v0.7)
- **`impact_scorer.py`**: Calculates network impact score (0-10)
  - Base score from facility criticality, lane volume, shipment priority, event type, ETA proximity
  - Trust tier modifier: +1 for tier 3, -1 for tier 1, 0 for tier 2 (v0.7)
  - Weighting bias: Per-source adjustment (-2 to +2) (v0.7)
  - Final score capped at 0-10 after all modifiers
  - Detailed breakdown for auditability
- **`correlation.py`**: Builds deterministic correlation keys for alert deduplication

**Key Design:**
- Structured output (JSON-serializable)
- Clear decision/evidence boundary (decisions vs. what system believes)
- Extensible for future LLM-based reasoning (LLM output goes in evidence, not decisions)
- Deterministic classification based on network impact scoring
- Supports alert correlation for deduplication and tracking evolving risks

### 9. Alert Correlation (`sentinel/alerts/correlation.py`)

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

### 10. Daily Brief (`sentinel/output/daily_brief.py`)

**Purpose:** Generate summaries of recent alerts for human consumption.

- **Query Logic**:
  - Finds alerts where `last_seen_utc >= cutoff OR first_seen_utc >= cutoff`
  - Sorts by: classification DESC, impact_score DESC, update_count DESC, last_seen_utc DESC
  - Filters by time window (24h, 72h, 7d)
  - Optionally excludes classification 0 alerts
  - Calculates tier counts (Global, Regional, Local) (v0.7)
  - Queries suppressed items for reporting (v0.8)

- **Output Formats**:
  - Markdown: Human-readable with sections
    - Tier summary header (Global: X | Regional: Y | Local: Z) (v0.7)
    - Tier badges per alert (`[G]`, `[R]`, `[L]`) (v0.7)
    - Trust tier indicators `(T3)`, `(T2)`, `(T1)` (v0.7)
    - Grouping by tier within sections (v0.7)
    - Suppressed count with top rules (v0.8)
  - JSON: Structured data for programmatic consumption
    - Includes `tier_counts`, `tier`, `trust_tier` per alert (v0.7)
    - Includes `suppressed` object with counts and breakdowns (v0.8)

**Key Design:**
- Deterministic (no LLM, pure query + render)
- Fast (direct SQL queries with proper indexing)
- Requires database (queries stored alerts)
- Tier-aware grouping and counts (v0.7)
- Transparent suppression reporting (v0.8)

### 11. Database Migrations (`sentinel/database/migrate.py`)

**Purpose:** Additive schema changes for SQLite.

- **Strategy**: Additive-only migrations (add columns, never remove)
- **Storage**: ISO 8601 strings for datetime fields (lexicographically sortable)
- **Safety**: Checks for column existence before adding
- **Usage**: Called automatically before operations that need new columns

**Key Design:**
- Local-first: No external migration tools needed
- Safe: Idempotent (can run multiple times)
- Simple: Direct SQLite ALTER TABLE statements

### 12. Runners (`sentinel/runners/`)

**Purpose:** Executable scripts for common workflows.

- **`run_demo.py`**: End-to-end demo pipeline
- **`load_network.py`**: Load CSV data into database
- **`ingest_external.py`**: External ingestion pipeline (v0.6+)
  - Normalizes raw items into events
  - Evaluates suppression rules (v0.8)
  - Links events to network entities
  - Generates alerts with trust tier weighting (v0.7)
  - Handles correlation and updates
  - Creates INGEST SourceRun records per source (v0.9)
  - Guarantees SourceRun creation even on failure (v1.0)

**Key Design:**
- Each runner is a standalone `main()` function
- Can be run as modules (`python -m sentinel.runners.run_demo`) or via CLI (`sentinel demo`)
- `ingest_external` integrates suppression, trust tier, and correlation

## Data Flow

### External Source Processing Pipeline (v0.6+)

1. **Fetch**: `sentinel fetch` retrieves raw items from configured sources
   - Rate-limited HTTP requests with retry logic
   - Deduplication based on `canonical_id` and `content_hash`
   - Stores in `raw_items` table with status NEW
   - Creates FETCH SourceRun record per source with metrics (v0.9)
2. **Normalization**: `sentinel ingest-external` normalizes raw items
   - Converts to canonical event format
   - Extracts source metadata (source_id, tier, url, published_at)
   - Applies trust tier, classification floor, weighting bias from config (v0.7)
   - Stores in `events` table
3. **Suppression** (v0.8): Evaluate suppression rules
   - Global rules evaluated first, then per-source rules
   - If suppressed: mark raw_item and event as SUPPRESSED, skip alert creation
   - Suppression metadata stored for audit trail
4. **Entity Linking**: 
   - Extract location from text or use provided city/state
   - Query database for matching facilities
   - Find lanes originating from those facilities
   - Find upcoming shipments on those lanes
5. **Alert Generation**: 
   - Calculate network impact score (0-10)
   - Apply trust tier modifier (+1 for tier 3, -1 for tier 1) (v0.7)
   - Apply weighting bias (-2 to +2) (v0.7)
   - Cap score at 0-10
   - Map score to classification (0=Interesting, 1=Relevant, 2=Impactful)
   - Enforce classification floor (v0.7)
   - Build alert with scope (facilities, shipments, lanes)
   - Include source metadata in `evidence.source` (v0.6+)
   - Generate recommended actions
6. **Correlation**: 
   - Build correlation key from event type, facility, lane
   - Check for existing alerts within 7-day window
   - Update existing or create new alert
   - Update tier, source_id, trust_tier from latest event (v0.7)
7. **SourceRun Creation** (v0.9, v1.0):
   - Creates INGEST SourceRun record per source after processing
   - Tracks items_processed, items_suppressed, items_events_created, items_alerts_touched
   - Guaranteed creation even on catastrophic failure (v1.0)
   - Error messages truncated to 1000 chars for database safety
8. **Run Status Evaluation** (v1.0):
   - Evaluates fetch results, ingest runs, doctor findings, stale sources
   - Determines exit code (0=healthy, 1=warning, 2=broken)
   - Provides actionable status messages
   - Prints status footer with top issues
9. **Output**: Structured alert (JSON) or daily brief (Markdown/JSON)
   - Brief includes tier counts, badges, grouping (v0.7)
   - Brief includes suppressed counts and breakdowns (v0.8)

### Event Processing Pipeline (Legacy/Demo)

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

## Configuration

### Source Configuration (`config/sources.yaml`)

Defines external sources with metadata:
- **id**: Unique source identifier
- **type**: Source adapter type (rss, nws_alerts)
- **tier**: Global, Regional, or Local
- **url**: Source endpoint URL
- **enabled**: Whether source is active
- **tags**: Categorization tags
- **trust_tier**: Reliability tier (1-3, default 2) (v0.7)
- **classification_floor**: Minimum alert classification (0-2, default 0) (v0.7)
- **weighting_bias**: Impact score adjustment (-2 to +2, default 0) (v0.7)
- **suppress**: Per-source suppression rules (v0.8)

**Example Files:**
- `config/sources.example.yaml`: Example configuration with explanatory comments
- Use `sentinel init` to create `config/sources.yaml` from example (v1.0)

### Suppression Configuration (`config/suppression.yaml`) (v0.8)

Defines global suppression rules:
- **enabled**: Master switch for suppression
- **rules**: List of suppression rules
  - **id**: Unique rule identifier
  - **kind**: Match type (keyword, regex, exact)
  - **field**: Field to match (title, summary, raw_text, url, event_type, source_id, tier, any)
  - **pattern**: Pattern to match
  - **case_sensitive**: Whether matching is case-sensitive
  - **note**: Human-readable note
  - **reason_code**: Short code for reporting

**Example Files:**
- `config/suppression.example.yaml`: Example configuration with conservative defaults
- Use `sentinel init` to create `config/suppression.yaml` from example (v1.0)

## Operational Features (v1.0)

### Starter Configuration

- **`sentinel init`**: Initialize configuration files from examples
  - Creates `config/sources.yaml` from `config/sources.example.yaml`
  - Creates `config/suppression.yaml` from `config/suppression.example.yaml`
  - Refuses to overwrite existing files unless `--force` flag used
  - Enables smooth first-time setup for new users

### Run Status Evaluation

- **Self-Evaluating Runs**: `sentinel run` evaluates its own health
  - Exit code 0 (Healthy): No critical issues
  - Exit code 1 (Warning): Some sources stale/failing, but pipeline functioning
  - Exit code 2 (Broken): Schema/config invalid, cannot fetch/ingest at all
- **Status Footer**: Prints run status and top issues after each run
- **Strict Mode**: `--stale` and `--strict` flags for fine-grained control

### Guaranteed Failure Reporting

- **No Silent Failures**: All ingest operations create SourceRun records
  - Success: Creates SourceRun with status=SUCCESS and metrics
  - Failure: Creates SourceRun with status=FAILURE and error message
  - Zero items: Creates SourceRun with status=SUCCESS and items_processed=0
- **Error Tracking**: Error messages truncated to 1000 chars for database safety
- **Fail-Fast Option**: `--fail-fast` flag stops processing on first source failure

### Doctor Command Enhancements

- **"What would I do next?"**: Priority-based recommendations
  - Schema drift → "Delete sentinel.db and rerun `sentinel run --since 24h`"
  - Stale sources → "Run `sentinel sources test <id> --since 72h`"
  - All fetch failing → "Check network / user agent / endpoint URLs"
  - Suppression invalid → "Fix suppression.yaml regex: <rule id>"
- **Last Run Group Summary**: Shows most recent run_group_id statistics
  - Fetch: X success / Y fail / Z quiet success
  - Ingest: X success / Y fail
  - Alerts touched: total
  - Suppressed: total

## Future Enhancements

- **LLM Agent**: Replace heuristic alert builder with LLM-based reasoning
- **JSON Event Ingestion**: Batch processing of JSON events from files
- **UI Foundation**: Read-only console for browsing alerts and sources
- **Automated Learning**: ML-based suppression rule suggestions
- **Event Storage**: Enhanced event persistence for historical analysis

