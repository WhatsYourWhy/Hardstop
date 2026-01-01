# Reporting & export runbook (P3)

Use this runbook when reporting/export surfaces fail or when source health blocks downstream renders.

## Symptoms and checks
- Brief/export missing or empty:
  - Check exit codes from the last run (`hardstop run` / `hardstop brief`). Exit code `1` = warning, `2` = broken.
  - Inspect `run_records/` for the brief/export operator; confirm config fingerprint matches expected snapshot.
- Evidence hashes missing in briefs/exports:
  - Verify incident evidence artifacts under `output/incidents/` exist and match `artifact_hash` references.
  - Re-run correlation/evidence operators in strict mode to regenerate artifacts if hashes are stale.
- Suppression rollups look wrong:
  - Run `hardstop sources health --explain-suppress <id>` and review suppression reason counts.
  - Inspect suppression config (`config/suppression.yaml`) for recent changes; re-run in strict mode.
- Source health blocking reports:
  - Run `hardstop sources health` and check `health_budget_state`; unblock failing sources or override schedule.
  - If stale, adjust fetch window (`--since`) or restore network connectivity before rerunning.

## Remediation steps
1) **Re-run in strict mode** to eliminate nondeterminism and regenerate artifacts:
   ```
   hardstop run --since 24h --strict
   hardstop brief --today --format json --strict
   ```
2) **Validate artifacts and hashes**:
   - Compare emitted `artifact_hash` values with files in `output/incidents/` (use `sha256sum` if needed).
   - If missing, rerun the correlation/evidence step or the full pipeline with pinned `filename_basename`.
3) **Inspect RunRecords**:
   - Check `run_records/` for the brief/export operator; ensure `input_refs` include the expected alert/evidence artifacts.
   - If config drifted, reconcile the config hash (merge defaults + overrides) and rerun.
4) **Recover from suppression/health issues**:
   - Tune noisy rules (or temporarily disable) if suppression ratio spikes; rerun and verify rollups.
   - Resolve blocked sources or temporarily exclude them to unblock reporting; document the change in the run summary.
5) **Re-emit exports**:
   - Regenerate brief/export bundles with `filename_basename` to keep deterministic filenames for CI artifacts.
   - Upload regenerated artifacts to your integration endpoints (Slack/Linear/CI) using the standard payload templates.

## When to escalate
- Repeated hash drift in strict mode.
- RunRecords missing `input_refs`/`output_refs` for reporting operators.
- Incident evidence artifacts failing validation against schema (`docs/specs/run-record.schema.json`).
