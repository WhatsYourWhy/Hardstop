# Parsing & linking layer

Normalizes raw items into canonical events and links them to network entities for alert generation.

## Responsibilities
- Normalize source-specific payloads (`normalizer.py`).
- Extract entities (`entity_extractor.py`) to populate facilities/lanes/shipments fields.
- Link events to the network graph and prepare correlation inputs (`network_linker.py`).

## Stable entry points
- Functions in `normalizer.py`, `entity_extractor.py`, and `network_linker.py` as used by the pipeline operators to create link-ready events.

## Contracts
- **Inputs:** `RawItemCandidate` objects from retrieval, network data from ingestion, suppression decisions (where applicable).
- **Outputs:** canonical events with populated scope (facilities/lanes/shipments), correlation keys, and impact-ready attributes that flow into alert building and briefs.
- **Determinism:** Maintain stable hashing/ordering of linked entities; correlation key construction should be reproducible for replay and evidence generation.

## P3 readiness notes
- Ensure scope fields stay synchronized with incident evidence artifacts (`output/incidents/evidence.py`) so briefs can surface merge rationale.
- When adding new entity extractors or link heuristics, document their inputs/outputs and keep correlation key rules backward compatible.
