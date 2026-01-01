# Determinism Proof 04 — P0 Demo Pipeline

- **Run date:** 2026-01-01
- **Host OS:** linux 6.1.147 (Ubuntu 24.04 container)
- **Branch:** `cursor/WHA-26-audit-demo-pipeline-repeatability-3304`
- **Goal:** Show that the documented P0 demo workflow produces the expected alert envelope and behaves deterministically across repeated invocations in the same environment.

## Scope & Inputs

Commands executed from `/workspace` with `PYTHONPATH=/workspace/src` unless noted:

1. `python3 -m pip install -e .[dev]`
2. `rm -f hardstop.db output/incidents/*.json` (reset state between proofs)
3. `python3 -m hardstop.runners.load_network`
4. `python3 -m hardstop.runners.run_demo` (baseline run)
5. `python3 -m hardstop.runners.run_demo` (repeat run without cleaning state)
6. `diff -u output/incidents/proof_run1.json output/incidents/proof_run2.json`
7. `python3 -m pytest tests/test_demo_pipeline.py`

## Expected vs Actual Alert Output

README section “Demo Pipeline (P0 verification)” documents the expected alert (`ALERT-20251229-bb25eb7a`) plus its classification, impact score, and scope. The first clean run emitted `ALERT-20260101-606fe98c`, which matches every behavioral contract aside from the timestamped ID.

| Field | README expectation | Observed run 1 value | Notes |
| --- | --- | --- | --- |
| Alert ID | `ALERT-20251229-bb25eb7a` | `ALERT-20260101-606fe98c` | IDs are derived from `datetime.utcnow()` + UUID (`src/hardstop/utils/id_generator.py`), so only the suffix differs over time. |
| Classification | `2` | `2` | Derived from the deterministic impact score pipeline. |
| Impact score | `5` | `5` | Breakdown: facility +2, lane +1, three priority shipments +1, keyword SPILL +1. |
| Correlation key | `SAFETY|PLANT-01|LANE-001` | `SAFETY|PLANT-01|LANE-001` | Printed in both runs. |
| Facility scope | `["PLANT-01"]` | `["PLANT-01"]` | Facility linker matches Avon, IN → PLANT-01. |
| Lane scope | `["LANE-001","LANE-002","LANE-003"]` | Same | All three outbound lanes from PLANT-01 included. |
| Shipment scope | 6 linked shipments | `["SHP-1001","SHP-1002","SHP-1005","SHP-1004","SHP-1003","SHP-1006"]` | Matches README narrative (six linked shipments, no truncation). |

All other serialized fields (risk type, summary, recommended action) mirror the documentation.

## Repeatability Evidence

| Run | Correlation action | Incident artifact hash | Artifact copy |
| --- | --- | --- | --- |
| Baseline (after clean slate) | `CREATED` | `7979a6b993f12e67d937732b3d23c9aa1a57b028a48e10e7cc21e8cf7a0eaac2` | `output/incidents/proof_run1.json` |
| Repeat (without cleaning DB) | `UPDATED` | `bd0e59f2a25124039d3ef78d17ceb8790a6b55780a14440c823915beae329c09` | `output/incidents/proof_run2.json` |

- The alert ID, classification, impact score, and scope are identical between runs, proving deterministic scoring given the same event.
- The second run deterministically correlates to the alert inserted by the first run (same correlation key), so the evidence artifact now captures merge facts (`Existing alert seen within 168h`, shared facilities/lanes).  
- `docs/audit/run_demo_diff.txt` records the full JSON difference between both incident evidence artifacts for future audits.

## Artifact & RunRecord Locations

- Incident evidence artifacts: `output/incidents/ALERT-*/` (emitted by `build_incident_evidence_artifact` in `src/hardstop/output/incidents/evidence.py`). Proof copies live at `output/incidents/proof_run{1,2}.json`.
- RunRecords: CLI surfaces write JSON records under `run_records/` via `src/hardstop/ops/run_record.py`. (The demo runner is read-only and does not emit RunRecords, but the contractually correct location is documented here per HS-AUDIT-04.)

## Test Coverage

`python3 -m pytest tests/test_demo_pipeline.py` passes, confirming the fixture-level demo pipeline contract is still satisfied.
