# Changelog

## [0.5.1] - 2024-XX-XX

### Fixed
- Correlation action now stored as fact (not inferred from status)
- Scope JSON updated on alert correlation (keeps scope current)
- Improved graceful degradation for correlation without session

## [0.5.0] - 2024-XX-XX

### Added
- Daily brief generation (`sentinel brief --today`)
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

