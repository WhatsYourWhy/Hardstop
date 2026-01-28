# Brief v2 & Export Bundle Specification (Outline)

**Status:** Draft (P3)
**Scope:** Reporting & integrations only
**Non-authority:** Briefs and exports are **read-only artifacts** and MUST NOT influence upstream decisions.

---

## 1. Purpose & Design Constraints

### Purpose

Brief v2 and Export Bundles provide a **stable, deterministic reporting surface** for humans and downstream tools (Slack, Linear, CI, dashboards) without exposing internal databases or operator state.

### Hard Constraints

- Read-only, artifact-driven
- Deterministic rendering (same inputs → same outputs)
- No DB access required by consumers
- Hash-stable payloads suitable for replay, diffing, and CI
- Derived artifacts only (never decision-authoritative)

### Non-Goals

- No live queries
- No streaming updates
- No embedded business logic
- No SaaS / webhook execution inside Hardstop

---

## 2. Artifact Lineage & Provenance

Brief v2 and Export Bundles MUST:

- Reference one or more **RunRecords**
- Include hashes for all source artifacts consumed
- Declare the **rendering operator version**
- Emit their own RunRecord (`ReportingOperator@v2`)

```text
Signals → Alerts → Incidents → Evidence → Brief v2 / Export Bundle
```

---

## 3. Brief v2 (Human-Readable)

### 3.1 Formats

- `brief.v2.md` (primary, human-facing)
- `brief.v2.json` (machine-readable mirror)

Markdown and JSON MUST be content-equivalent.

---

### 3.2 Brief Header (Deterministic Metadata)

Required fields:

- `brief_id`
- `generated_at` (pinned or replay-normalized)
- `run_group_id`
- `run_ids[]`
- `mode` (strict | best-effort)
- `config_hash`
- `hardstop_version`
- `operator_version`

---

### 3.3 Executive Summary

Deterministic counts and rollups only:

- Total alerts by classification (0/1/2)
- New vs ongoing incidents
- Blocked or degraded sources
- Suppression rate summary

No narrative logic beyond formatting.

---

### 3.4 Alert Sections

Each alert entry includes:

- `alert_id`
- `correlation.key`
- Classification
- Impact score (numeric)
- **Rationale summary** (rendered from `impact_score_rationale`)
- Facilities / lanes / shipments (sorted, stable order)
- Suppression context (if applicable)
- Evidence references (hash + path)

No recomputation; render-only.

---

### 3.5 Incident Sections

For merged alerts:

- Incident ID
- Merge summary (from `IncidentEvidence`)
- Root alerts (ordered deterministically)
- Time window
- Evidence artifact reference

---

### 3.6 Source Health Appendix

Snapshot from `sources health` at run time:

- Source ID
- Health state (HEALTHY / WATCH / BLOCKED)
- Suppression %
- Last successful fetch

---

## 4. Export Bundle (Machine-Readable)

### 4.1 Bundle Structure

Single directory or archive:

```text
export/
├── manifest.json
├── brief.v2.json
├── alerts.csv
├── incidents.csv
├── evidence/
│   ├── incident-evidence.<hash>.json
│   └── alert-evidence.<hash>.json
└── provenance/
    ├── run-records.json
    └── config.json
```

---

### 4.2 manifest.json (Required)

Fields:

- `bundle_version`
- `generated_at`
- `hardstop_version`
- `operator_version`
- `config_hash`
- `run_ids[]`
- `artifact_hashes[]`
- `checksums` (SHA-256 for every file)

---

### 4.3 alerts.csv

One row per alert:

- alert_id
- correlation_key
- classification
- impact_score
- trust_tier
- facility_ids (semicolon-separated, sorted)
- lane_ids
- shipment_ids
- suppressed (true/false)
- evidence_ref (hash)

No nested logic. Flat, deterministic.

---

### 4.4 incidents.csv

One row per incident:

- incident_id
- correlation_key
- alert_ids (sorted)
- start_time
- end_time
- evidence_ref (hash)

---

### 4.5 Evidence Payloads

Raw JSON copies of:

- `IncidentEvidence`
- `AlertEvidence`

Unmodified except for canonical formatting.

---

## 5. Determinism Rules

- All lists sorted
- All timestamps normalized (or pinned)
- Canonical JSON serialization
- Hashes computed post-normalization
- Rendering failures emit RunRecords with error state

---

## 6. CLI Surface

### Commands

```bash
hardstop brief --today --format md|json --out output/
hardstop export --today --format bundle --out export/
```

### Exit Codes

- `0` – success
- `1` – warnings (e.g. degraded sources)
- `2` – broken (missing artifacts, blocked sources in strict mode)

---

## 7. Integration Contract (Explicit Boundary)

Integrations MUST:

- Read only `brief.v2.json` or export bundles
- Never query SQLite
- Never invoke operators

Supported sinks (examples only):

- Slack (summary + top alerts)
- Linear (issues keyed by correlation.key)
- CI (exit codes + artifact upload)

---

## 8. Versioning & Backward Compatibility

- `brief.v1` remains supported but frozen
- `brief.v2` required for all new integrations
- Export bundle schema versioned independently
- Breaking changes require:
  - New schema version
  - Updated docs
  - Migration note in `EXECUTION_PLAN.md`

---

## 9. Acceptance Criteria (P3 Exit)

P3 is complete when:

- Brief v2 renders deterministically from golden fixtures
- Export bundle hashes are regression-locked
- Slack + Linear examples consume artifacts without DB access
- CI workflow can fail builds based on exit codes alone

---

## 10. Explicit Non-Goals (Again, On Purpose)

- No REST API
- No push-based integrations
- No real-time updates
- No decision logic in reporting
