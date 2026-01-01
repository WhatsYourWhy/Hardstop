# Retrieval layer

Purpose-built adapters and fetch orchestration. This layer produces `RawItemCandidate` objects only; all shaping/ingestion happens downstream.

## Responsibilities
- Load source config (`config/sources.yaml`) and normalize via `get_all_sources`.
- Fetch items using adapters in `adapters.py` (per source `type`) and rate-limited orchestration in `fetcher.py`.
- Capture best-effort metadata for RunRecords (`SourceFetcher.best_effort_metadata`).
- Perform lightweight dedupe helpers (`dedupe.py`) before ingesting.

## Stable entry points
- `SourceFetcher.fetch_all(...)` — canonical fetch loop with tier/enabled/since filters, jitter-aware rate limiting, and typed `FetchResult` payloads.
- `create_adapter(source_config, defaults, random_seed=...)` — factory for source-specific adapters returning `AdapterFetchResponse` and `RawItemCandidate` instances.

## Contracts
- **Inputs:** normalized source configs; optional `since` windows (`24h|72h|7d`); optional `max_items_per_source`.
- **Outputs:** `FetchResult` list with `items` of `RawItemCandidate`; jitter/seed metadata when not in strict mode.
- **Determinism:** Set `strict=True` (and optional `rng_seed`) to disable jitter and pin adapter seeds for deterministic runs.
- **Error semantics:** `status` and `status_code` are populated on failures; failures do not raise unless caller sets `fail_fast=True`.

## P3 readiness notes
- Surface adapter version strings (`adapter.adapter_version`) are tracked in `inputs_version`; keep this stable for export signatures.
- Ensure new adapters return minimal, normalized fields (id, title, summary/raw text, timestamps, url, source metadata) to keep downstream parsing deterministic.
