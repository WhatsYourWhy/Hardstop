# Repo ID Card — Hardstop

## Snapshot
- **Mission:** Deterministic, local-first event→risk→alert engine (`README.md`).
- **Maintainer signals:** Audit-focused docs in `docs/ARCHITECTURE.md`, `docs/EXECUTION_PLAN.md`, `docs/specs/run-record.schema.json`, `docs/LICENSING.md`, plus shipping history in `CHANGELOG.md`.
- **Packaging:** Published as `hardstop-agent` with CLI entry `hardstop = "hardstop.cli:main"` (`pyproject.toml`).
- **Primary runtime claim:** Strict-mode runs are replayable and produce identical RunRecord/artifact hashes when inputs + config match (`README.md` “Core Guarantees”; `docs/ARCHITECTURE.md#Deterministic-Kernel-Contract`).

## Key Surfaces & Entry Points

| Surface | Invocation | Path(s) | Notes |
| --- | --- | --- | --- |
| CLI (all commands) | `hardstop <command>` | `src/hardstop/cli.py` | Subcommands cover pipeline (`run`, `fetch`, `ingest-external`, `brief`), health (`doctor`, `sources health/test`), demos, init, exports. |
| Demo pipeline | `python3 -m hardstop.runners.run_demo` | `src/hardstop/runners/run_demo.py` | Reads fixtures under `tests/fixtures/`, builds a deterministic alert (documented in `README.md` Demo Pipeline). |
| Network loader | `python3 -m hardstop.runners.load_network` | `src/hardstop/runners/load_network.py` | Seeds SQLite with facilities/lanes/shipments CSVs shipped in `tests/fixtures/`. |
| External ingest runner | `python3 -m hardstop.runners.ingest_external` | `src/hardstop/runners/ingest_external.py` | Orchestrated by CLI `cmd_ingest_external`, transforms raw items into events/alerts. |
| Doctor | `hardstop doctor` | `src/hardstop/cli.py` (`cmd_doctor`) | Verifies DB schema, configs, suppression rules, source health budgets, and prints remediation steps. |
| Sources commands | `hardstop sources list|test|health` | `src/hardstop/cli.py` (`cmd_sources_*`) → `src/hardstop/retrieval/fetcher.py`, `src/hardstop/database/source_run_repo.py` | Manage per-source diagnostics, suppression explanations, and failure budgets. |
| Export APIs | `hardstop export <brief|alerts|sources>` | `src/hardstop/api/export.py`, `src/hardstop/api/*.py` | Read-only surfaces that reuse brief/alert/source repositories. |

## Directory Overview

```
repo root
├── README.md / CHANGELOG.md
├── pyproject.toml
├── config/ (source + suppression configs & examples)
├── docs/ (architecture, execution plan, specs, licensing, audits)
├── src/hardstop/
│   ├── cli.py (CLI entry)
│   ├── alerts/ (builder, correlation, scorer)
│   ├── api/ (export + HTTP-ready models)
│   ├── config/ (YAML loaders/defaults)
│   ├── database/ (SQLite schema + repos + migrations)
│   ├── ingestion/ (file ingestor helper)
│   ├── ops/ (run records, artifacts, run status, source health)
│   ├── output/ (daily brief + incident artifacts)
│   ├── parsing/ (canonicalization + entity linking)
│   ├── retrieval/ (adapters, fetcher, dedupe)
│   ├── runners/ (demo + ingest pipeline helpers)
│   ├── suppression/ (engine + models)
│   └── utils/ (id/time/log helpers)
└── tests/ (fixtures + regression suites locking determinism, health, CLI)
```

## Implementation Notes for Auditors
- **RunRecords + artifacts:** Emitted via `src/hardstop/ops/run_record.py` and stored in `run_records/` for every CLI surface (`cmd_fetch`, `cmd_ingest_external`, `cmd_brief`, `cmd_run`, `cmd_incidents_replay`).
- **SQLite schema:** Managed via `src/hardstop/database/migrate.py` helpers (e.g., `ensure_source_runs_table`, `ensure_trust_tier_columns`, `ensure_suppression_columns`), with repositories under `src/hardstop/database/*.py`.
- **Source telemetry:** `src/hardstop/ops/source_health.py` + `src/hardstop/database/source_run_repo.py` drive health scores and failure budgets surfaced by CLI + API.
- **Testing spine:** Determinism/contract coverage lives in `tests/test_golden_run.py`, `tests/test_demo_pipeline.py`, `tests/test_run_record.py`, `tests/test_source_health*.py`, `tests/test_cli_*.py`, anchoring guarantees referenced in documentation.

Keep claims tied to the referenced paths above when extending the audit.
