# Changelog

## [1.1.0] - 2025-XX-XX

### Added
- Canonical source registry with tier defaults
  - `tier_defaults` section folds trust tier, classification floor, and weighting bias per tier
  - Loader normalizes every source so CLI paths share the same schema
- Adapter diagnostics + fetch telemetry
  - RSS/NWS/FEMA adapters report HTTP status and bytes downloaded
  - `FetchResult` now captures `bytes_downloaded` for deterministic audit trails
- Structured source health scoring
  - New health score (0-100) plus failure-budget states (`HEALTHY`, `WATCH`, `BLOCKED`)
  - `hardstop sources health` surfaces scores, failure streaks, and suppression ratios
  - `hardstop doctor` and `hardstop run --strict` gate on exhausted budgets
- Suppression observability
  - Every suppression decision records a stable reason code
  - `hardstop sources health --explain-suppress <id>` prints reason counts with deterministic samples
- Database diagnostics
  - `source_runs.diagnostics_json` stores fetch/ingest envelopes (bytes, dedupe, suppression reasons)
  - Raw items/events include `suppression_reason_code` for trend queries

### Changed
- `cmd_fetch`/`cmd_sources_test` persist fetch diagnostics (bytes downloaded, dedupe counts)
- `ingest_external` aggregates suppression reason counts per SourceRun
- `evaluate_run_status` treats failure-budget blockers as exit code 2 and warnings in strict mode
- Doctor command now reports failure-budget warnings/blockers alongside stale counts

### Technical
- New helper `hardstop.ops.source_health.compute_health_score`
- `hardstop.config.loader` normalization utilities with tier-aware defaults
- `summarize_suppression_reasons()` helper for CLI explain output
- Tests cover health scoring, suppression summaries, and failure-budget gating
# Changelog

## [1.0.0] - 2024-XX-XX

### Added
- Self-evaluating runs with exit codes
  - Exit code 0 (Healthy): No critical issues
  - Exit code 1 (Warning): Some sources stale/failing, but pipeline functioning
  - Exit code 2 (Broken): Schema/config invalid, cannot fetch/ingest at all
  - `--strict` flag to treat warnings as broken
- Run status evaluation module (`hardstop/ops/run_status.py`)
  - Deterministic evaluation of run health
  - Checks config errors, schema drift, source failures, ingest crashes
  - Provides actionable status messages
- Guaranteed INGEST SourceRun rows on failure
  - All ingest operations (success or failure) create SourceRun records
  - Failure rows include error messages (truncated to 1000 chars)
  - No silent failures - every source batch gets a record
- `--fail-fast` flag for ingest operations
  - Stop processing on first source failure
  - Available in `hardstop ingest-external` and `hardstop run`
- Doctor command enhancements
  - "What would I do next?" section with priority-based recommendations
  - Last run group summary showing fetch/ingest statistics
  - Clear distinction between "quiet feeds, healthy" vs "quiet because broken"
- Starter configuration files
  - `config/sources.example.yaml` with explanatory comments
  - `config/suppression.example.yaml` with conservative defaults
  - `hardstop init` command to create config files from examples
  - `--force` flag to overwrite existing configs

### Changed
- `hardstop run` now evaluates status and exits with appropriate code
- `hardstop run` prints status footer with top issues
- Ingest pipeline guarantees SourceRun creation even on catastrophic failures
- Doctor command provides actionable next steps instead of just diagnostics

### Technical
- New module: `hardstop/ops/run_status.py` for status evaluation
- Enhanced `ingest_external.main()` with guaranteed SourceRun creation
- Improved error handling and reporting throughout pipeline
- All failure paths are now auditable via SourceRun records

## [0.9.0] - 2024-XX-XX

### Added
- Source health tracking system
  - `source_runs` table to track fetch and ingest operations
  - Two-phase monitoring (FETCH and INGEST phases)
  - `run_group_id` UUID linking related fetch and ingest runs
  - Health metrics: success rate, stale detection, last error, last status code
- Source health commands
  - `hardstop sources test <id>`: Test a single source with summary output
  - `hardstop sources health`: Display health table for all sources
  - `--stale` and `--lookback` flags for health queries
- SourceRun repository functions
  - `create_source_run()`: Create run records with metrics
  - `list_recent_runs()`: Query recent runs with filters
  - `get_source_health()`: Calculate health metrics for a source
  - `get_all_source_health()`: Calculate health for all sources
- Enhanced fetcher with structured results
  - `FetchResult` Pydantic model with status, status_code, error, duration
  - `SourceFetcher.fetch_all()` returns `List[FetchResult]`
  - `SourceFetcher.fetch_one()` for single-source fetching
  - Zero items fetched is treated as SUCCESS (quiet success)
- Doctor command enhancements
  - Source health table check
  - Stale source count and recommendations
  - Source runs table validation

### Changed
- `cmd_fetch()` now creates FETCH phase SourceRun records
- `ingest_external.main()` now creates INGEST phase SourceRun records per source
- `cmd_run()` generates and passes `run_group_id` to link related operations
- Health metrics computed from SourceRun records instead of ad-hoc queries

### Technical
- Database schema: Added `SourceRun` model with comprehensive metrics
- Migration: `ensure_source_runs_table()` function
- Repository: `source_run_repo.py` with health calculation logic
- Fetcher: Enhanced error capture and duration tracking

## [0.8.0] - 2024-XX-XX

### Added
- Suppression system for filtering noisy events
  - Global suppression rules in `config/suppression.yaml`
  - Per-source suppression rules in `config/sources.yaml`
  - Keyword, regex, and exact match patterns
  - Field-specific matching (title, summary, raw_text, url, event_type, source_id, tier, any)
  - Case-sensitive and case-insensitive matching
- Suppression metadata storage
  - `raw_items.suppression_status`, `suppression_primary_rule_id`, `suppression_rule_ids_json`, `suppressed_at_utc`, `suppression_stage`
  - `events.suppression_primary_rule_id`, `suppression_rule_ids_json`, `suppressed_at_utc`
- Suppression reporting in daily brief
  - Suppressed count with top rules and sources
  - Markdown and JSON output formats
- CLI flags for suppression control
  - `--no-suppress`: Bypass suppression rules (for debugging)
  - `--explain-suppress`: Log suppression decisions
- Doctor command enhancements
  - Suppression config validation
  - Duplicate rule ID detection
  - Suppressed item counts

### Changed
- Suppressed items skip alert creation but create events for audit trail
- `get_raw_items_for_ingest()` filters out suppressed items by default
- Suppression evaluation occurs after normalization, before alert building

### Technical
- Database schema: Added suppression columns to `raw_items` and `events` tables
- Migration: `ensure_suppression_columns()` function
- Suppression engine: Deterministic rule evaluation with precedence (global rules first, then per-source)
- All suppression metadata stored for full auditability

## [0.7.0] - 2024-XX-XX

### Added
- Source trust tier system (1-3 scale)
  - Trust tier 3: +1 impact score modifier
  - Trust tier 1: -1 impact score modifier
  - Trust tier 2: No modifier (default)
- Classification floor enforcement
  - Per-source minimum classification level
  - Prevents downgrading alerts below floor
  - Reasoning includes "Classification floor" note
- Weighting bias configuration
  - Per-source bias (-2 to +2) applied to impact score
  - Allows fine-tuning of source priority
- Tier-aware briefing
  - Tier counts in header (Global: X | Regional: Y | Local: Z)
  - Tier badges per alert (`[G]`, `[R]`, `[L]`)
  - Trust tier indicators `(T3)`, `(T2)`, `(T1)`
  - Grouping by tier within sections
  - Tier and trust_tier in JSON output
- Database columns for tier tracking
  - `raw_items.trust_tier`, `events.trust_tier`, `alerts.trust_tier`
  - `alerts.tier`, `alerts.source_id` (for brief efficiency)

### Changed
- Impact scoring now includes trust tier bonus and weighting bias
- Impact score capped at 0-10 after all modifiers
- Classification enforced after scoring (max of computed and floor)
- Alert tier reflects "last updater" tier during correlation
- Brief output shows tier-aware grouping and counts

### Technical
- Database schema: Added trust_tier, tier, source_id columns
- Migration: `ensure_trust_tier_columns()` function
- Config: `trust_tier`, `classification_floor`, `weighting_bias` in `sources.yaml`
- Impact scorer: Detailed breakdown includes trust tier and bias lines
- Alert builder: Extracts tier/trust from event (not config) for consistency

## [0.6.0] - 2024-XX-XX

### Added
- External source retrieval system
  - RSS/Atom feed adapter
  - NWS Alerts API adapter (CAP/Atom format)
  - FEMA/IPAWS adapter (disabled by default)
  - Source configuration in `config/sources.yaml`
- Source tiers (Global, Regional, Local)
  - Tier classification for sources
  - Used for tier-aware processing and briefing
- Raw items storage
  - `raw_items` table for fetched items before normalization
  - Deduplication based on `canonical_id` and `content_hash`
  - Status tracking (NEW, NORMALIZED, FAILED)
- Rate limiting and error handling
  - Per-host rate limiting with jitter
  - Exponential backoff for retries
  - Graceful handling of 404s and network errors
- New CLI commands
  - `hardstop sources list`: List configured sources
  - `hardstop fetch`: Fetch items from external sources
  - `hardstop ingest-external`: Normalize and ingest raw items
  - `hardstop run`: Convenience command (fetch + ingest)
  - `hardstop doctor`: Health checks for schema and config
- Event persistence for external events
  - External events stored in `events` table
  - Source metadata in `evidence.source` field
  - URL, source_id, tier, published_at tracking
- Time-based filtering
  - `--since` flag for fetch and ingest commands
  - Filters by `fetched_at_utc` and `published_at_utc`

### Changed
- Event normalization extended for external sources
  - `normalize_external_event()` function
  - Handles RSS, NWS, and other source types
  - Preserves source metadata in event dict
- Alert evidence includes source metadata
  - `evidence.source` field with source_id, tier, url, etc.
  - Source metadata separated from correlation data
- Database migration functions enhanced
  - `ensure_raw_items_table()` migration function
  - `ensure_event_external_fields()` migration function
  - Base table creation before migrations

### Technical
- Database schema: Added `RawItem` model and external fields to `Event` model
- Repository: `raw_item_repo.py` for raw item persistence
- Repository: `event_repo.py` for event persistence
- Adapters: Pluggable adapter system for different source types
- Fetcher: Rate-limited HTTP client with retry logic
- Normalizer: Extended to handle external source formats

## [0.5.1] - 2024-XX-XX

### Fixed
- Correlation action now stored as fact (not inferred from status)
- Scope JSON updated on alert correlation (keeps scope current)
- Improved graceful degradation for correlation without session

## [0.5.0] - 2024-XX-XX

### Added
- Daily brief generation (`hardstop brief --today`)
- Brief query logic with time window filtering (24h, 72h, 7d)
- Markdown and JSON output formats for briefs
- `impact_score` column in alerts table
- `scope_json` column in alerts table
- `correlation_action` column in alerts table
- CLI options: `--since`, `--format`, `--limit`, `--include-class0`
- `query_recent_alerts()` function in alert_repo

### Changed
- Alert builder now stores impact_score and scope_json in database
- Brief generator uses stored correlation_action (preferred over inference)

### Technical
- Database schema: Added impact_score, scope_json, correlation_action columns
- Brief generation: Deterministic query + render (no LLM)
- ISO 8601 timestamp storage for consistent date comparisons

## [0.4.0] - 2024-XX-XX

### Added
- Alert correlation system (deduplication over 7-day window)
- Correlation key builder (`correlation.py`)
- Alert repository functions (`alert_repo.py`)
- Migration helper (`migrate.py`) for additive schema changes
- Correlation metadata: `correlation_key`, `first_seen_utc`, `last_seen_utc`, `update_count`, `root_event_ids_json`
- Structured correlation field in `AlertEvidence` model
- Session context manager for proper lifecycle management

### Changed
- Alert builder now checks for existing alerts before creating new ones
- Alerts are persisted to database by default (when session provided)
- Updated alerts increment `update_count` and refresh `last_seen_utc`

### Technical
- Database schema: Added correlation columns with proper indexing
- ISO 8601 string storage for datetime fields (lexicographically sortable)
- Additive migration strategy (safe for local-first SQLite)

## [0.3.0] - 2024-XX-XX

### Added
- `classification` field (canonical) for alert risk tier (0=Interesting, 1=Relevant, 2=Impactful)
- `evidence` field to separate non-decisional evidence from decisions
- `AlertEvidence` model to contain diagnostics and linking notes
- Robust ETA parsing with timezone handling and bad date tolerance
- Database schema now includes `classification` column

### Changed
- Network impact scoring now uses 1-10 scale (normalized from previous approach)
- ETA "within 48h" check now uses actual 48-hour window (not calendar days)
- Date-only ETA values treated as end-of-day UTC consistently
- Alert model structure: `diagnostics` moved to `evidence.diagnostics`

### Deprecated
- `priority` field: Use `classification` instead. Will be removed in v0.6.
- `diagnostics` field: Use `evidence.diagnostics` instead. Will be removed in v0.6.

### Fixed
- ETA parsing no longer crashes on invalid/missing dates
- Timezone drift issues in ETA comparisons resolved
- Parsing failures gracefully skip subscores without breaking pipeline

### Technical
- Database schema: Added `classification` column, `priority` kept for backward compatibility (nullable)
- Clear separation between decisions (what system asserts) and evidence (what system believes)
- Backward compatibility maintained via computed properties for deprecated fields

## [0.1.0] - Initial release

- Basic event ingestion and normalization
- Network entity linking (facilities, lanes, shipments)
- Alert generation with heuristic-based scoring
- Local SQLite storage
- Demo pipeline

