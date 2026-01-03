# Component Map — Hardstop Runtime

This map links architectural domains from `docs/ARCHITECTURE.md` to concrete modules under `src/hardstop/`. Reference the paths below when tracing behavior or validating contracts.

## Entrypoints & Orchestration
- **CLI spine:** `src/hardstop/cli.py` wires subcommands to operators, emits RunRecords (`hardstop fetch|ingest-external|run|brief|doctor|sources ...`).
- **Runners/demos:** `src/hardstop/runners/run_demo.py`, `load_network.py`, `ingest_external.py` provide python module entrypoints invoked by CLI and README workflows.
- **APIs/exporters:** `src/hardstop/api/*.py` adapt internal repos into programmatic surfaces (brief/alerts/sources export, HTTP-ready models).

## Component Breakdown

| Domain | Responsibilities | Key Modules / Paths | Notes & Tests |
| --- | --- | --- | --- |
| Retrieval | Adapter registry, tier-aware fetch loop, SourceRun telemetry, deterministic hashing of raw batches. | `src/hardstop/retrieval/adapters.py`, `fetcher.py`, `dedupe.py`; CLI glue in `cmd_fetch`; persistence via `src/hardstop/database/raw_item_repo.py`. | `tests/test_fetcher.py`, `tests/test_cli_sources.py`, `tests/test_source_health*.py` cover adapter contracts, `cmd_sources_test` uses same fetcher. |
| Suppression / Noise Control | Deterministic filtering with rule provenance, suppression explainability, config loading. | `src/hardstop/suppression/engine.py`, `models.py`; configs in `config/suppression.yaml`; CLI `--no-suppress/--explain-suppress` flows through `cmd_ingest_external`. | `tests/test_suppression_engine.py`, `tests/test_suppression_integration.py`; suppression metadata stored via `raw_item_repo.py` and `event_repo.py`. |
| Parsing / Canonicalization | Normalize raw items, extract entities, link to network graph before scoring. | `src/hardstop/parsing/normalizer.py`, `entity_extractor.py`, `network_linker.py`; fixtures in `tests/fixtures/normalized_event_spill.json`. | Guarded by `tests/test_network_linker.py`, `tests/test_correlation.py`, `tests/test_demo_pipeline.py`. |
| Database / Storage | SQLite schema + ORM models, migrations, repositories for raw items/events/alerts/source runs. | `src/hardstop/database/schema.py`, `sqlite_client.py`, `migrate.py`, `alert_repo.py`, `event_repo.py`, `raw_item_repo.py`, `source_run_repo.py`. | Schema drift + telemetry validated by `cmd_doctor`, `tests/test_run_status.py`, `tests/test_source_health_integration.py`. |
| Alerts & Decision Core | Impact scoring, alert models, correlation/dedup, incident evidence. | `src/hardstop/alerts/alert_builder.py`, `impact_scorer.py`, `correlation.py`, `alert_models.py`; evidence stored under `src/hardstop/output/incidents/evidence.py`. | Determinism locked by `tests/test_impact_scorer.py`, `tests/test_correlation.py`, `tests/test_demo_pipeline.py`, `tests/test_golden_run.py`. |
| Output & Reporting | Daily brief renderer (Markdown/JSON), export bundles, incident evidence artifacts. | `src/hardstop/output/daily_brief.py`, `output/incidents/`, `src/hardstop/api/export.py`, CLI `cmd_brief`, `cmd_export`. | Regression tests in `tests/test_output_renderer_only.py`, `tests/test_export_api.py`. |
| Ops / Provenance | RunRecord emission, artifact hashing, run status evaluation, source health scoring. | `src/hardstop/ops/run_record.py`, `artifacts.py`, `run_status.py`, `source_health.py`; CLI `cmd_run`, `cmd_doctor`, `cmd_sources_health`. | `docs/specs/run-record.schema.json` + `tests/test_run_record.py`, `tests/test_cli_run_records.py`, `tests/test_run_status.py` enforce contracts. |
| Runners & Pipelines | Reusable workflows for ingest/demo plus helper CLIs for init/export. | `src/hardstop/runners/run_demo.py`, `load_network.py`, `ingest_external.py`; CLI commands `demo`, `ingest`, `ingest-external`, `run`. | Demo + golden fixtures validated through `tests/test_demo_pipeline.py`, `tests/test_golden_run.py`. |

## How Components Interact
1. **Retrieval → DB → Source health:** `SourceFetcher` saves raw items via `raw_item_repo.save_raw_item()` and writes `SourceRun` rows through `source_run_repo.create_source_run()` (seen inside `cmd_fetch` and `cmd_sources_test`).
2. **Suppression hooks:** During ingest (`cmd_ingest_external` / `runners.ingest_external.main`), suppression config from `config/suppression.yaml` flows into `suppression.engine.evaluate()` and stamps audit metadata on `RawItem`/`Event` rows.
3. **Parsing → Alerts:** Canonicalized events feed `alerts.alert_builder` and `alerts.impact_scorer`, which produce deterministic diagnostics before `output.daily_brief` renders Markdown/JSON.
4. **Ops feedback loop:** RunRecords emitted via `ops.run_record.emit_run_record()` for each CLI surface; `ops.run_status.evaluate_run_status()` consumes fetch/ingest telemetry plus doctor findings to produce exit codes echoed in README exit-code rules.
5. **Artifact replay:** Incident evidence JSON under `output/incidents/` plus RunRecords are replayed through `cmd_incidents_replay`, enforcing the contracts defined in `docs/specs/run-record.schema.json`.

Use this map alongside `docs/ARCHITECTURE.md` when tracing data flow or validating that components satisfy their documented contracts.
