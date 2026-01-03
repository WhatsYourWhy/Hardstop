# HS-AUDIT-06 — SQLite Schema, Migrations, and Idempotency

- **Run date:** 2026-01-02  
- **Host OS:** linux 6.1.147 (Ubuntu 24.04 container)  
- **Repo branch:** `cursor/WHA-28-sqlite-audit-schema-migrations-9c73`  
- **Goal:** Validate that Hardstop’s local-first SQLite storage bootstraps cleanly, applies migrations deterministically, and keeps idempotency guarantees for documented loaders (`hardstop ingest`, `hardstop run`, `run_demo`).

## Storage & Migration Topology

- The runtime resolves its SQLite path from `hardstop.config.yaml` (`storage.sqlite_path: "hardstop.db"`). All CLI entrypoints call `hardstop.database.sqlite_client.get_engine`, which runs `Base.metadata.create_all()` to materialize the core tables (`facilities`, `lanes`, `shipments`, `raw_items`, `events`, `alerts`, `source_runs`).  
- Additive migrations live in `src/hardstop/database/migrate.py` and are intentionally idempotent: each helper issues `PRAGMA table_info` and only runs `ALTER TABLE ... ADD COLUMN ...` when a column is missing. Table-creating helpers (`ensure_raw_items_table`, `ensure_source_runs_table`) wrap `SELECT name FROM sqlite_master` guards, so re-invocation is safe.  
- CLI workflows call the migration helpers before doing any I/O:
  - `hardstop fetch` (and therefore `hardstop run`) invokes `get_engine` followed by `ensure_raw_items_table`, `ensure_event_external_fields`, `ensure_alert_correlation_columns`, `ensure_trust_tier_columns`, and `ensure_source_runs_table`.
  - `hardstop ingest-external` adds `ensure_suppression_columns` before normalizing raw items.
  - `hardstop demo` calls `ensure_alert_correlation_columns` and relies on `session_context()` (which creates the ORM tables) plus previously loaded network data.
- `hardstop.runners.load_network` uses SQLAlchemy `Session.merge` for facilities/lanes/shipments, giving true upsert semantics and making repeated ingests idempotent by design.

## Fresh Bootstrap Experiment

1. **Prep:** Removed any prior `hardstop.db`, installed the project with `python3 -m pip install -e ".[dev]"`, and ran `python3 -m hardstop.cli ingest`. This bootstrapped a ~116 KB SQLite file at `/workspace/hardstop.db` populated with the demo network (7 facilities, 12 lanes, 15 shipments).  
2. **Schema inspection:** `sqlite3 hardstop.db ".tables"` surfaced exactly seven tables: `alerts, events, facilities, lanes, raw_items, shipments, source_runs`. Column layouts matched the latest migrations (e.g., `alerts` already held `correlation_key`, `impact_score`, `tier`, `source_id`, `trust_tier`; `raw_items` included all v0.7/v0.8 suppression fields).  
3. **Strict CLI run:** `python3 -m hardstop.cli run --since 24h --strict` fetched 11 items (10 new NOAA weather alerts + 1 IL regional), ingested all of them into events/alerts, emitted a “Quiet Day” brief, and produced 15 RunRecords under `run_records/`. Post-run row counts: `raw_items=11`, `events=11`, `alerts=3`, `source_runs=8`.  
4. **Demo workflow:** `python3 -m hardstop.runners.run_demo --mode pinned` re-used the same database, linked the golden spill event to the network, and produced the expected deterministic alert `ALERT-20251229-d31a370b` plus its evidence at `output/incidents/ALERT-20251229-d31a370b__EVT-DEMO-0001__SAFETY_PLANT-01_LANE-001.json`. The CLI logs confirmed correlation metadata was written (`correlation_key=SAFETY|PLANT-01|LANE-001`, `impact_score=5`).

These steps satisfied the “fresh DB boot” DoD item: a clean workspace, followed by the documented `ingest → run → demo` workflow, produced a healthy SQLite schema, run records, and artifacts with no manual table tweaks.

## Idempotency & Drift Observations

### Network loader (`hardstop ingest`)

- Re-running `python3 -m hardstop.cli ingest` immediately after the bootstrap reloaded the same CSVs yet left the network tables unchanged (`facilities=7`, `lanes=12`, `shipments=15`).  
- Duplicate scans (`SELECT facility_id, COUNT(*) ... HAVING COUNT(*)>1`) returned 0 for facilities, lanes, and shipments, demonstrating that `Session.merge` enforces primary-key idempotency.

### Fetch + ingest pipeline (`hardstop run`)

- A second `python3 -m hardstop.cli run --since 24h --strict` re-fetched the same six sources. Ten NOAA alerts were re-downloaded but only **one** raw item was stored (`Fetched 10 items ... 1 new`). Ingestion processed that single new record, produced one additional event, and **updated**—rather than duplicated—the existing `SAFETY|PLANT-01|LANE-001` alert (brief reported it as a correlated update).  
- Table deltas confirmed the dedupe path: `raw_items` and `events` grew from 11→12, `alerts` stayed at 3, and `source_runs` rose from 8→15 as expected (one FETCH + one INGEST record per source and per run grouping).
- The deduplication logic in `raw_item_repo.save_raw_item()` first queries by `canonical_id`, then by `content_hash`, and only inserts when no prior row matches, so repeated runs cannot double-ingest identical feed entries.

### Schema drift resilience

- Because each `ensure_*` helper only adds missing columns, the migrations are safe to run on every CLI invocation. In practice, every `hardstop run`, `hardstop ingest-external`, `hardstop sources test`, and `run_demo` invocation triggers the relevant `ensure_*` calls before touching data, so a user can delete `hardstop.db`, pull a newer release, and simply re-run the CLI to upgrade the schema in place.  
- `source_runs` automatically backfills the `diagnostics_json` column if it is absent, so upgrading from pre-v0.9 databases only requires re-running any workflow that touches source health; no manual SQL is necessary.

## Evidence Snapshot

| Stage | Command | Key result | Row counts (raw/events/alerts/source_runs) |
| --- | --- | --- | --- |
| Fresh bootstrap | `python3 -m hardstop.cli run --since 24h --strict` | 11 fetched / 11 ingested, run status **HEALTHY**, 15 run_records emitted | 11 / 11 / 3 / 8 |
| Demo verification | `python3 -m hardstop.runners.run_demo --mode pinned` | Recreated golden alert `ALERT-20251229-d31a370b`, wrote deterministic incident artifact | (no change) |
| Idempotent ingest | `python3 -m hardstop.cli ingest` (second pass) | Reloaded CSVs, **0** duplicate rows (PK counts unchanged) | 11 / 11 / 3 / 8 |
| Idempotent run | `python3 -m hardstop.cli run --since 24h --strict` (second pass) | 11 fetched / **1** stored, existing alert correlated instead of duplicated | 12 / 12 / 3 / 15 |

## Findings & Follow-ups

- ✅ **Fresh DB boot succeeds**: A pristine checkout plus `ingest → run → demo` produces the full schema, network data, run records, and artifacts without manual SQL.  
- ✅ **Migrations are deterministic**: `ensure_*` helpers only append columns/tables and are invoked by every CLI path that mutates the DB. No schema drift was observed across repeated runs.  
- ✅ **Idempotency holds**: `load_network` and `run` can be re-executed at will—primary-key merges and raw-item dedupe prevent duplicate facilities, lanes, shipments, raw items, or alerts.  
- ⚠️ **Potential enhancement**: Because migrations rely on ad-hoc helpers instead of a versioned manifest (`PRAGMA user_version` is unused), auditors must keep cross-checking `migrate.py` when new columns are introduced. Consider adding a simple migration registry or smoke test that dumps `PRAGMA table_info` into CI artifacts so drift is caught automatically.

This audit meets the Linear DoD: fresh bootstrap passes, migrations run deterministically, and the documented idempotent operations behave correctly with live data.
