# Canonicalization Operator Spec

The canonicalization stage converts raw external items into deterministic, replayable
canonical event payloads and enriches them with facility/route context. Both
operators emit RunRecords that conform to `docs/specs/run-record.schema.json` and
hash their input/output artifacts with canonical JSON serialization.

## Operators

### canonicalization.normalize@1.0.0
- **Inputs**: `RawItemCandidate` (id: `raw-item:<source_id>:<raw_id>`, schema `raw-items/v1`)
- **Outputs**: `SignalCanonical` (id: `event:<event_id>`, schema `signals/v1`)
- **Behavior**:
  - Deterministically derive `event_id` from caller-provided `event_id`/`canonical_id`/`raw_id` (in that order) or generate a new id.
  - Compute `event_type` via `extract_event_type` heuristics and record `location_hint` + `entities_json` from payload/metadata.
  - Serialize the original payload into `event_payload_json` with stable key ordering and capture `trust_tier`, `classification_floor`, and `weighting_bias` defaults from source config.
  - Emit a RunRecord containing `input_refs`/`output_refs`, `config_hash` (from resolved runtime/sources/suppression snapshot), and `bytes` for the serialized canonical event.

### canonicalization.entity_link@1.0.0
- **Inputs**: `SignalCanonical` (id: `event:<event_id>`, schema `signals/v1`)
- **Outputs**: `SignalCanonicalEnriched` (id: `event:<event_id>:linked`, schema `signals/enriched/v1`)
- **Behavior**:
  - Link facilities/lanes/shipments when a database session is provided, bounded by the configured `days_ahead` window.
  - Deterministically fall back to empty facilities/lanes/shipments when network context is unavailable; correlation keys still resolve via `NONE` placeholders.
  - Emit a RunRecord capturing `input_refs`/`output_refs`, `config_hash`, and artifact byte counts.

## Hashing and determinism
- Artifact hashes use `hardstop.ops.run_record.artifact_hash`, which applies canonical JSON serialization (sorted keys, compact separators, UTF-8).
- RunRecords must record the resolved configuration fingerprint (`config_hash`) alongside declared inputs/outputs to enable replay and provenance checks.
- Callers may supply `run_id`, `started_at`, and `ended_at` plus `canonicalize_time` for deterministic replays and fixture generation.

## Fixtures
- `tests/fixtures/normalized_event_spill.json` is the canonical output for the demo spill payload and is pinned via `tests/test_golden_run.py`.
- Correlation tests verify that canonical payload hashes and partial-data fallbacks remain stable.
