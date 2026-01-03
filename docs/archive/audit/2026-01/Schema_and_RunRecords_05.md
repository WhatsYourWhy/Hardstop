# HS-AUDIT-05 — RunRecord Schema Validation

- **Run date:** 2026-01-01
- **Host OS:** linux 6.1.147 (Ubuntu container)
- **Repo branch:** `cursor/WHA-27-run-record-schema-audit-a92f`
- **Goal:** Verify CLI-emitted RunRecords match `docs/specs/run-record.schema.json` and provide rerunnable validation tooling.

## Environment Prep

### 1. Install project with dev extras
```bash
python3 -m pip install -e ".[dev]"
```
**Exit:** 0  
**Notes:** Installs runtime dependencies plus `jsonschema`/`pytest` for schema validation.

## CLI RunRecord Capture

### 2. Run strict pipeline to emit RunRecords
```bash
python3 -m hardstop.cli run --since 12h --strict
```
**Exit:** 0  
**Notes:** Fetch + ingest pulled 11 signals (NWS global + IL regional), brief produced the expected “Quiet Day” summary, and `run_records/` now holds 15 JSON artifacts (fetch, ingest, brief, run-status, plus 11 `canonicalization.normalize@1.0.0` records). All operators ran in `strict` mode with consistent config fingerprint `71f91e61…`.

## Schema Validation Tooling

### 3. Validate RunRecords
```bash
python3 tools/validate_run_records.py --records-dir run_records
```
**Exit:** 0  
**Output:**
```
Validated 15/15 RunRecords in run_records
  Modes: strict=15
  Records with determinism metadata: 0
```

The validator enforces the JSON Schema (Draft 2020-12 with format checking) and adds a determinism guard that flags `best_effort` metadata when `mode != "best-effort"`. The tool exits non-zero if the directory is missing, a record is unreadable, or validation fails, so other auditors can rerun it verbatim.

## Findings & Notes

- All 15 RunRecords conform to `docs/specs/run-record.schema.json`; diagnostics collections were present (empty arrays in this healthy run) and every artifact ref declared the required `id`/`kind`/`hash` tuple.
- Canonicalization produced 11 per-item RunRecords referencing `RawItemCandidate` inputs and fingerprinted `SignalCanonical` outputs. Fetch, ingest, brief, and run-status each emitted a single record tied back to the shared `run_group_id`.
- CLI currently writes `best_effort: {}` even for strict-mode runs, so the validator treats empty objects as “not present” to avoid false positives. No determinism metadata surfaced in this sample, which matches expectations for a fully strict run.
- No schema drift observed—hash fields, timestamps, execution modes, and diagnostics all match the spec. Follow-up: keep monitoring future runs for populated `best_effort` fields so we can confirm replay metadata once best-effort workflows are exercised.
- Re-run instructions: ensure dependencies are installed (`python3 -m pip install -e ".[dev]"` on a clean checkout), capture CLI runs that populate `run_records/`, then execute `python3 tools/validate_run_records.py --records-dir run_records`. The script reports per-mode counts plus determinism coverage and fails fast on the first invalid record if desired (`--fail-fast`).
