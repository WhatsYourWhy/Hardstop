# Repro Log 03 — README Workflow Verification

- **Run date:** 2026-01-01
- **Host OS:** linux 6.1.147 (Ubuntu 24.04 container)
- **Repo branch:** `cursor/WHA-25-readme-workflow-verification-2593`
- **Goal:** Execute the README "Daily Workflow" and "Usage" commands and capture reality vs documentation.

## Environment Prep

### 1. README ingest attempt before install
```bash
hardstop ingest
```
**Exit:** 127  
**Excerpt:**
```
--: line 1: hardstop: command not found
```
**Notes:** Fresh containers do not have `$HOME/.local/bin` on PATH, so the `hardstop` console script was unavailable.

### 2. Install Hardstop in editable mode
```bash
pip install -e .
```
**Exit:** 0  
**Excerpt:** Built and installed `hardstop-agent==0.3.0` plus dependencies (`SQLAlchemy 2.0.45`, `pydantic 2.12.5`, etc.). Installer warned that scripts were placed in `/home/ubuntu/.local/bin`.

### 3. Run ingest with PATH override
```bash
PATH="$HOME/.local/bin:$PATH" hardstop ingest
```
**Exit:** 0  
**Excerpt:**
```
Loaded 7 facilities, 12 lanes, 15 shipments
```

## README Daily Workflow

### 4. Run pipeline
```bash
PATH="$HOME/.local/bin:$PATH" hardstop run --since 24h
```
**Exit:** 0  
**Excerpt:** Fetched 11 items from 6 sources, ingested them into 11 events/alerts, generated a quiet-day brief, and reported `Run status: HEALTHY`.

### 5. Generate brief
```bash
PATH="$HOME/.local/bin:$PATH" hardstop brief --today --since 24h
```
**Exit:** 0  
**Excerpt:** Quiet-day brief showing zero alerts for the selected window.

## README Usage — Sources

### 6. List sources
```bash
PATH="$HOME/.local/bin:$PATH" hardstop sources list
```
**Exit:** 0  
**Excerpt:** Eight configured sources displayed (six enabled) with tiers, enablement, types, and tags.

### 7. Source health (initial failure)
```bash
PATH="$HOME/.local/bin:$PATH" hardstop sources health
```
**Exit:** 1  
**Excerpt:**
```
NameError: name 'Dict' is not defined
```
**Notes:** `cmd_sources_health` defines a `sort_key` helper annotated with `Dict[str, Any]` but the symbol was not imported.

### 8. Patch CLI typing import
File: `src/hardstop/cli.py`
```diff
-from typing import Any, Iterable, List, Optional
+from typing import Any, Dict, Iterable, List, Optional
```

### 9. Source health (retry)
```bash
PATH="$HOME/.local/bin:$PATH" hardstop sources health
```
**Exit:** 0  
**Excerpt:** Health table rendered with scores ranging from 30 (blocked, disabled sources) to 100 (healthy, enabled sources).

### 10. Source test
```bash
PATH="$HOME/.local/bin:$PATH" hardstop sources test nws_active_us --since 72h
```
**Exit:** 0  
**Excerpt:** HTTP 200 success, 20 items fetched (10 stored), sample titles printed (`Test Message`, `Air Stagnation Advisory...`, `Winter Weather Advisory...`).

## Artifacts and Follow-ups

- `hardstop run` created/updated the local SQLite database (`hardstop.db`), raw item cache, and run records under `run_records/`.
- The missing `Dict` import fix is required for all environments; without it the README `sources health` command crashes.
- README should mention ensuring `$HOME/.local/bin` (or the venv `bin/`) is on PATH so the `hardstop` console script is discoverable.

