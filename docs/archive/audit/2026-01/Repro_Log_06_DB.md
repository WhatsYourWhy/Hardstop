# Repro Log 06 — SQLite DB & Migration Audit

- **Run date:** 2026-01-02  
- **Host OS:** linux 6.1.147 (Ubuntu 24.04 container)  
- **Repo branch:** `cursor/WHA-28-sqlite-audit-schema-migrations-9c73`  
- **Goal:** Reproduce HS-AUDIT-06 by bootstrapping a fresh `hardstop.db`, exercising CLI + demo workflows, and proving the documented idempotency claims.

## Environment Prep

### 1. Install runtime + dev extras
```bash
python3 -m pip install -e ".[dev]"
```
**Exit:** 0  
**Excerpt:** Installed `hardstop-agent==0.3.0` plus SQLAlchemy 2.0.45, pydantic 2.12.5, pytest 9.0.2, jsonschema 4.25.1. Console noted the `hardstop` script lives in `$HOME/.local/bin`.

### 2. Reset SQLite state
```bash
rm -f hardstop.db
```
**Exit:** 0  
**Notes:** Ensures subsequent steps exercise the bootstrap path instead of reusing a previous database.

## Fresh Bootstrap

### 3. Load demo network into a new DB
```bash
python3 -m hardstop.cli ingest
```
**Exit:** 0  
**Excerpt:**
```
Loaded 7 facilities, 12 lanes, 15 shipments
```
**Notes:** A new `/workspace/hardstop.db` (~116 KB) appeared.

### 4. Inspect schema and columns
```bash
sqlite3 hardstop.db ".tables"
sqlite3 hardstop.db "PRAGMA table_info(alerts);"
```
**Exit:** 0 / 0  
**Excerpt:**
```
alerts       facilities   raw_items    source_runs
events       lanes        shipments
...
13|update_count|INTEGER|0||0
14|root_event_ids_json|TEXT|0||0
15|impact_score|INTEGER|0||0
16|scope_json|TEXT|0||0
17|tier|VARCHAR|0||0
18|source_id|VARCHAR|0||0
19|trust_tier|INTEGER|0||0
```
**Notes:** All migration-era columns (correlation, trust tier, suppression) exist out of the box, confirming `ensure_*` runs during ingest.

### 5. Run strict fetch+ingest workflow
```bash
python3 -m hardstop.cli run --since 24h --strict
```
**Exit:** 0  
**Excerpt:**
```
Fetch complete: 11 items fetched, 11 stored
Ingestion complete: ... Processed: 11 ... Alerts: 11 ... Errors: 0
Run status: HEALTHY
```
**Notes:** Generated 15 RunRecords under `run_records/` and produced a “Quiet Day” brief. Table counts afterwards:

| Table | Rows after first run |
| --- | --- |
| raw_items | 11 |
| events | 11 |
| alerts | 3 |
| source_runs | 8 |

### 6. Produce deterministic demo alert
```bash
python3 -m hardstop.runners.run_demo --mode pinned
```
**Exit:** 0  
**Excerpt:**
```
Built alert (mode=pinned) ... alert_id: ALERT-20251229-d31a370b ... impact_score: 5
```
**Notes:** Wrote `output/incidents/ALERT-20251229-d31a370b__EVT-DEMO-0001__SAFETY_PLANT-01_LANE-001.json` with the expected hash `e36dbe8c...`.

## Idempotency & Drift Checks

### 7. Re-run load_network (should be a no-op)
```bash
python3 -m hardstop.cli ingest
sqlite3 hardstop.db "SELECT 'facilities' tbl, COUNT(*) FROM facilities UNION ALL SELECT 'lanes', COUNT(*) FROM lanes UNION ALL SELECT 'shipments', COUNT(*) FROM shipments;"
```
**Exit:** 0 / 0  
**Excerpt:**
```
Loaded 7 facilities, 12 lanes, 15 shipments
tbl         COUNT(*)
----------  --------
facilities  7
lanes       12
shipments   15
```
**Notes:** Counts matched the initial ingest. Follow-up duplicate scans (`SELECT ... HAVING COUNT(*)>1`) returned `0` for facilities, lanes, and shipments.

### 8. Strict run against a warm DB
```bash
python3 -m hardstop.cli run --since 24h --strict
```
**Exit:** 0  
**Excerpt:**
```
Fetch complete: 11 items fetched, 1 stored
Ingestion complete: ... Processed: 1 ... Alerts: 1
## Top Impact ... Hydrochloric acid spill ... Correlation key matched existing alert
```
**Notes:** Only one newly fetched NOAA alert cleared dedupe; the rest were recognized as already ingested. The brief shows the alert as an update rather than a duplicate. RunRecord count increased to 20 files (`ls run_records | wc -l`).

### 9. Post-run table counts & duplicates
```bash
sqlite3 -header -column hardstop.db "SELECT 'raw_items' tbl, COUNT(*) rows FROM raw_items UNION ALL SELECT 'events', COUNT(*) FROM events UNION ALL SELECT 'alerts', COUNT(*) FROM alerts UNION ALL SELECT 'source_runs', COUNT(*) FROM source_runs;"
sqlite3 hardstop.db "SELECT COUNT(*) FROM (SELECT facility_id, COUNT(*) c FROM facilities GROUP BY facility_id HAVING c>1);"
```
**Exit:** 0 / 0  
**Excerpt:**
```
tbl          rows
-----------  ----
raw_items    12
events       12
alerts       3
source_runs  15
0
```
**Notes:** Raw items/events rose by one (the new NOAA record); alerts stayed at 3 thanks to correlation; source_runs grew to 15 (one fetch + one ingest row per source/run_id). Duplicate checks remained at zero.

## Summary

- Fresh bootstrap succeeds with the documented CLI path (`ingest → run → demo`).
- Migration helpers populate every modern column automatically; no manual SQL was required.
- `load_network` is idempotent (replays do not double-insert facilities/lanes/shipments).
- `hardstop run` dedupes raw items via canonical ID/content hash; the second run fetched 11 items but stored only one, then updated an existing alert through correlation.
- RunRecords (20 JSON files) and incident artifacts were created as expected, satisfying the HS-AUDIT-06 deliverables.
