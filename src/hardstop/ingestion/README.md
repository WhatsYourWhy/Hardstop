# Ingestion layer

Transforms fetched items into canonical DB rows (events, alerts) and loads network data for linking.

## Responsibilities
- Persist network datasets (facilities, lanes, shipments) via CSV loaders in `file_ingestor.py`.
- Provide thin ingestion helpers that prepare data for downstream parsing/linking (network-aware alert building happens later).

## Stable entry points
- `load_facilities_from_csv`, `load_lanes_from_csv`, `load_shipments_from_csv` — idempotent CSV loaders using `session.merge`.
- `ingest_all_csvs` — convenience wrapper that loads all three datasets and returns per-entity counts.

## Contracts
- **Inputs:** CSV files with documented columns; SQLAlchemy session.
- **Outputs:** DB rows for facilities/lanes/shipments; int counts per loader.
- **Determinism:** CSV ordering is preserved by iterating rows; callers should supply stable CSVs for reproducible linking.
- **Error semantics:** Missing files log warnings and return zero; loaders commit after processing each file.

## P3 readiness notes
- Ensure network datasets are loaded before running parsing/linking so briefs and incident evidence include scope.
- Future ingest helpers should continue to emit counts (for run status and reporting) and avoid side effects beyond DB writes.
