# HS-AUDIT-09 — Up-To-Date Report & Roadmap

## Ship Decision

**Hold until dependency pinning and README workflow fixes land.** Demo + CLI determinism proofs are green, but “up to date” requires an operator to be able to install, run, and replay Hardstop with documented steps and reproducible dependencies. The current state still relies on floating PyPI resolutions and undocumented bootstrap steps, so we cannot certify the system as “up to date” for external use.

## Definition of “Up To Date”

For Hardstop, we define “up to date” as the intersection of:

1. **Deterministic surfaces:** Demo runner and strict CLI workflows reproduce the documented alert envelope, RunRecords, and incident evidence when executed on the latest commit.  
2. **Executable documentation:** README + doctor guidance let a clean machine complete the daily workflow without hidden pre-reqs or inline code patches.  
3. **Schema + storage readiness:** RunRecord schema and SQLite migrations are aligned with docs/specs and idempotent across reruns.  
4. **Operational telemetry:** Source health signaling matches the documented budgets so operators can trust strict/best-effort exits.  
5. **Pinned dependencies:** Runtime and tooling dependencies are locked (or upper-bounded) so every install resolves to a vetted set of wheels.

Verdict: **Not met.** Criteria 1–4 are satisfied by HS-AUDIT-01…08 evidence, but criterion 5 fails (no lock file, all constraints are `>=`), and criterion 2 still leaks undocumented setup steps (PATH fixes, `python3-venv` package). Until those regressions are addressed, Hardstop can drift underneath the documented workflow.

## Health Scorecard

| Area | Evidence | Status | Notes |
| --- | --- | --- | --- |
| Determinism — demo | [`docs/audit/Determinism_Proof_04.md`](./Determinism_Proof_04.md) & `run_demo_diff.txt` show repeated runs yielding identical scoring + correlation with optional pinned mode. | ✅ Pass | HS-4.5 pinned mode freezes IDs/hashes for reproducible audits; live mode behaves deterministically aside from timestamps. |
| Determinism — CLI | [`docs/audit/Schema_and_RunRecords_05.md`](./Schema_and_RunRecords_05.md) validates strict CLI runs plus schema-hash verification for 15 RunRecords. | ✅ Pass | Strict runs emitted consistent RunRecords, and the validator enforces determinism metadata & schema fidelity. |
| README workflow correctness | [`docs/audit/Repro_Log_03_README_Workflow.md`](./Repro_Log_03_README_Workflow.md) exercises the documented workflow end-to-end but required manual PATH edits and a `Dict` import fix. | ⚠ Watch | Commands succeed once pre-reqs are known, yet README omits PATH guidance and assumes Python venv packages already exist. |
| RunRecord schema | [`docs/audit/Schema_and_RunRecords_05.md`](./Schema_and_RunRecords_05.md) + `tools/validate_run_records.py` | ✅ Pass | Validator proves every emitted record matches `docs/specs/run-record.schema.json`; determinism guardrails are in place. |
| DB / migrations | [`docs/audit/DB_and_Migrations_06.md`](./DB_and_Migrations_06.md) | ✅ Pass (with debt) | Fresh bootstrap, idempotent reruns, and demo proofs all succeed; remaining gap is lack of versioned migration manifest. |
| Source health signaling | [`docs/audit/Sources_Health_and_Suppression_07.md`](./Sources_Health_and_Suppression_07.md) | ✅ Pass | Health table, suppression explainers, and strict gating behave exactly as documented; only doc nit is “never run” sources defaulting to BLOCKED. |
| Dependency health | [`docs/audit/Dependency_Health_08.md`](./Dependency_Health_08.md) | ❌ Fail | All runtime/dev deps float on `>=` pins, there’s no lockfile, and `pip-audit` cannot be scoped to repo-owned deps. This undermines the determinism claims. |

## Top Risks

1. **Floating dependency graph (High).** Without a lockfile or upper bounds, every install resolves against the latest PyPI releases, so determinism proofs can silently break after publication. (`docs/audit/Dependency_Health_08.md`)  
2. **README bootstrap gaps (Medium).** Clean environments must install `python3-venv`, edit `$PATH`, and patch imports before the README workflow passes, contradicting the “no surprises” operator story. (`docs/audit/Repro_Log_02_CLI_Smoke.md`, `docs/audit/Repro_Log_03_README_Workflow.md`)  
3. **Migrations lack provenance (Medium).** Ad-hoc `ensure_*` helpers work today, but there’s no schema version registry or CI snapshot to prove future drift hasn’t occurred. (`docs/audit/DB_and_Migrations_06.md`)  
4. **Security signal noise (Low → Medium).** `pip-audit` flags host-level Ansible/Jinja2 CVEs because scans run outside a scoped venv; the resulting noise may mask genuine Hardstop issues. (`docs/audit/Dependency_Health_08.md`)

## Roadmap

### 1-week must-fix (blocking “up to date”)

1. **Introduce a pinned dependency set.** Use `pip-tools`, `uv pip compile`, or Poetry to generate a lock (runtime + dev) and update CI/documents to install via that lock. Enforce `pip check` + `pip-audit --requirement lockfile` so determinism proofs rest on immutable wheels.  
2. **Patch the README workflow to be self-contained.** Document the PATH requirement, add `python3-venv` (or equivalent) to prerequisites, and ship the `Dict` import fix by default so `hardstop sources health` never crashes on a clean checkout. Audit `hardstop doctor` output so newcomers know whether to run `init --force`.

### 1-month should-fix (sequenced after lock + doc fixes)

1. **Add a migration registry + CI schema snapshot.** Track an explicit `user_version`, emit schema dumps in CI, and gate merges on snapshot diffs to catch drift automatically.  
2. **Scope dependency security scans.** Automate `pip-audit` inside the locked virtualenv (or via `uv pip audit`) and publish SARIF artifacts so real CVEs are actionable without host noise.  
3. **Document “never run” source states and suppression budgets in README/INTEGRATIONS.** Call out that new sources appear as `BLOCKED` until first success and link to suppression explainers so operators can interpret watch/blocked budgets without reading the code.

With these actions, Hardstop can confidently upgrade from “hold” to “ship” while keeping prior determinism guarantees intact.

## HS-11 Update — 2026-01-02

- README bootstrap steps now call out Python 3.10+, the `python3-venv` package, PATH requirements for `$HOME/.local/bin`, the `hardstop init` → `doctor` → `run` sequence, and why “never run” sources show up as `BLOCKED` until the first successful fetch. Operators can follow the document verbatim on a clean Ubuntu image with no inline fixes.
- `hardstop doctor` surfaces PATH/CLI guidance, recommends `hardstop init` when configs are missing, and points newcomers toward `hardstop run --since 24h` to create the database. Messaging matches the README so the bootstrap story is consistent.
- With HS-11 the “Executable documentation” criterion from HS-AUDIT-09 is ready to move from ⚠ Watch to ✅ Pass pending reviewer confirmation, unblocking the Hold → Ship reevaluation.
