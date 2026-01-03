# Repro Log 04 — P0 Demo Determinism

- **Run date:** 2026-01-01
- **Host OS:** linux 6.1.147 (Ubuntu 24.04 container)
- **Branch:** `cursor/WHA-26-audit-demo-pipeline-repeatability-3304`
- **Goal:** Execute the README demo workflow, repeat it twice in the same environment, and capture any deltas plus supporting hashes.

## Environment Prep

### 1. Install runtime + dev dependencies
```bash
python3 -m pip install -e .[dev]
```
**Exit:** 0  
**Excerpt:** Installed `hardstop-agent==0.3.0` plus SQLAlchemy 2.0.45, pydantic 2.12.5, pytest 9.0.2, etc. Scripts were placed in `/home/ubuntu/.local/bin`.

### 2. Reset local state for deterministic proof
```bash
rm -f hardstop.db output/incidents/*.json
```
**Exit:** 0  
**Notes:** Ensures the sqlite correlation store and incident artifacts start from a clean slate before measuring repeatability.

### 3. Load the golden-path network snapshot
```bash
python3 -m hardstop.runners.load_network
```
**Exit:** 0  
**Excerpt:** `Loaded 7 facilities, 12 lanes, 15 shipments` from `tests/fixtures/*.csv`.

## Demo Runs

### 4. Baseline demo run
```bash
python3 -m hardstop.runners.run_demo
```
**Exit:** 0  
**Excerpt:**
```
alert_id=ALERT-20260101-606fe98c
classification=2 (impact score=5)
scope.facilities=['PLANT-01']
scope.lanes=['LANE-001','LANE-002','LANE-003']
scope.shipments=6 ids
incident artifact hash=7979a6b993f12e67d937732b3d23c9aa1a57b028a48e10e7cc21e8cf7a0eaac2
```
**Artifacts:** Copied to `output/incidents/proof_run1.json` (`sha256: ce04b3c96d5d60ae533247cf57d98f82766b08ea61b360b8a8da5ee1cb6def3f`).

### 5. Repeat demo run (no cleaning)
```bash
python3 -m hardstop.runners.run_demo
```
**Exit:** 0  
**Excerpt:**
```
alert_id=ALERT-20260101-606fe98c (same as run 1)
correlation action=UPDATED (existing alert seen within 168h)
linking notes now include shared facilities/lanes
incident artifact hash=bd0e59f2a25124039d3ef78d17ceb8790a6b55780a14440c823915beae329c09
```
**Artifacts:** Copied to `output/incidents/proof_run2.json` (`sha256: 38405e3850ca44ba802f907bd5fbcd3ae5ee4c628b0135f220b3ae686b7f397f`).

### 6. Artifact diff
```bash
diff -u output/incidents/proof_run1.json output/incidents/proof_run2.json
```
**Exit:** 1 (expected for non-empty diff)  
**Artifact:** Stored unified diff at `docs/audit/run_demo_diff.txt`, showing that only the merge evidence (existing alert metadata, shared facilities/lanes, hashes/timestamps) diverged between runs.

## Tests

### 7. Demo pipeline unit test
```bash
python3 -m pytest tests/test_demo_pipeline.py
```
**Exit:** 0  
**Excerpt:** `1 passed in 0.07s`.

## Outputs & Paths

- Incident evidence lives in `output/incidents/` (generated via `build_incident_evidence_artifact`). Proof copies: `proof_run1.json`, `proof_run2.json`.
- RunRecords for CLI workflows are written to `run_records/` by `src/hardstop/ops/run_record.py` and remain untouched by this demo runner.
- Diff evidence: `docs/audit/run_demo_diff.txt` (run-to-run artifact comparison for HS-AUDIT-04).
