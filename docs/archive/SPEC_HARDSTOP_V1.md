# Hardstop v1 Specification

## Scope

Hardstop v1 is a **local-first, domain-agnostic event → risk → alert engine** with a focus on supply chain risk management.

## Core Features

### 1. Data Ingestion

- **CSV Ingestion**: Load facilities, lanes, and shipments from CSV files
- **JSON Event Ingestion**: Process individual events from JSON files
- **Idempotent Loading**: Safe to re-run ingestion (handles duplicates)

### 2. Event Processing

- **Normalization**: Convert raw events to canonical format
- **Entity Linking**: Automatically link events to:
  - Facilities (by location or ID)
  - Lanes (routes from affected facilities)
  - Shipments (upcoming shipments on those lanes)
- **Location Extraction**: Parse city/state from event text

### 3. Alert Generation

- **Risk Assessment**: Map network impact score to alert classification (0=Interesting, 1=Relevant, 2=Impactful)
- **Scope Definition**: Identify affected facilities, shipments, lanes
- **Action Recommendations**: Generate suggested next steps
- **Correlation**: Deduplicate alerts based on correlation keys (7-day window)
- **Persistence**: Alerts are persisted to database by default (v0.4+)
- **Decision/Evidence Boundary**: Clear separation between decisions (classification, summary, scope) and evidence (diagnostics, linking notes, correlation metadata)

### 4. CLI Interface

- `hardstop demo`: Run end-to-end demo pipeline
- `hardstop ingest`: Load network data from CSV files
- `hardstop brief --today`: Generate daily brief (stub in v1)

## Data Models

### Event

```python
{
    "event_id": str,           # Unique identifier
    "source_type": str,        # "NEWS", "API", etc.
    "source_name": str,        # Source identifier
    "title": str,              # Event title
    "raw_text": str,           # Full event text
    "event_type": str,         # "SAFETY_AND_OPERATIONS", etc.
    "severity_guess": int,     # 1-5 severity scale
    "city": str,               # Optional: city
    "state": str,              # Optional: state
    "country": str,            # Optional: country
    "facilities": [str],       # Linked facility IDs
    "lanes": [str],           # Linked lane IDs
    "shipments": [str]        # Linked shipment IDs
}
```

### Alert

```python
{
    "alert_id": str,
    "risk_type": str,
    "classification": int,      # 0=Interesting, 1=Relevant, 2=Impactful (canonical)
    "priority": int,            # DEPRECATED: Use classification. Mirrors classification for backward compatibility. Will be removed in v0.4.
    "status": str,             # "OPEN", "CLOSED", etc.
    "summary": str,
    "root_event_id": str,
    "scope": {
        "facilities": [str],
        "lanes": [str],
        "shipments": [str]
    },
    "impact_assessment": {
        "time_risk_days": int | None,
        "revenue_at_risk": float | None,
        "customers_affected": [str],
        "qualitative_impact": [str]
    },
    "reasoning": [str],
    "recommended_actions": [
        {
            "id": str,
            "description": str,
            "owner_role": str,
            "due_within_hours": int
        }
    ],
    "model_version": str,
    "confidence_score": float | None,
    "evidence": {              # Non-decisional evidence (what system believes)
        "diagnostics": {
            "link_confidence": dict[str, float],
            "link_provenance": dict[str, str],
            "shipments_total_linked": int,
            "shipments_truncated": bool,
            "impact_score": int,
            "impact_score_breakdown": list[str]
        },
        "linking_notes": [str]
    },
    "diagnostics": {...}        # DEPRECATED: Use evidence.diagnostics. Will be removed in v0.4.
}
```

### Facility

- `facility_id`: Primary key
- `name`: Facility name
- `type`: "PLANT", "DC", etc.
- `city`, `state`, `country`: Location
- `lat`, `lon`: Coordinates
- `criticality_score`: 1-10 importance

### Lane

- `lane_id`: Primary key
- `origin_facility_id`: Foreign key to Facility
- `dest_facility_id`: Foreign key to Facility
- `mode`: "TRUCK", "RAIL", etc.
- `carrier_name`: Carrier identifier
- `avg_transit_days`: Typical transit time
- `volume_score`: 1-10 volume indicator

### Shipment

- `shipment_id`: Primary key
- `order_id`: Related order
- `lane_id`: Foreign key to Lane
- `sku_id`: Product identifier
- `qty`: Quantity
- `status`: "PENDING", "IN_TRANSIT", "SCHEDULED", etc.
- `ship_date`: ISO date string
- `eta_date`: ISO date string
- `customer_name`: Customer identifier
- `priority_flag`: 0 or 1

## Configuration

### `hardstop.config.yaml`

```yaml
storage:
  sqlite_path: "hardstop.db"

logging:
  level: "INFO"

domain:
  active_pack: "supply_chain"

demo:
  facilities_csv: "tests/fixtures/facilities.csv"
  lanes_csv: "tests/fixtures/lanes.csv"
  shipments_csv: "tests/fixtures/shipments_snapshot.csv"
  event_json: "tests/fixtures/event_spill.json"
```

## CLI Surface

### `hardstop demo`

Runs the end-to-end demo pipeline:
1. Loads sample event from config
2. Normalizes event
3. Links to network data
4. Generates alert
5. Prints JSON output

**Usage:**
```bash
hardstop demo
```

### `hardstop ingest`

Loads network data from CSV files into SQLite.

**Usage:**
```bash
hardstop ingest
```

**Options:**
- `--fixtures`: Explicitly use fixture files (optional, default behavior)

### `hardstop brief --today`

Generates daily brief of recent alerts.

**Usage:**
```bash
hardstop brief --today
```

**Options:**
- `--since 24h|72h|7d`: Time window (default: 24h)
- `--format md|json`: Output format (default: md)
- `--limit N`: Maximum alerts per section (default: 20)
- `--include-class0`: Include classification 0 alerts

**Status:** Implemented in v0.5. Queries alerts created or updated within the specified window.

## CSV File Formats

### `facilities.csv`

Required columns:
- `facility_id`, `name`, `type`, `city`, `state`, `country`, `lat`, `lon`, `criticality_score`

### `lanes.csv`

Required columns:
- `lane_id`, `origin_facility_id`, `dest_facility_id`, `mode`, `carrier_name`, `avg_transit_days`, `volume_score`

### `shipments_snapshot.csv`

Required columns:
- `shipment_id`, `order_id`, `lane_id`, `sku_id`, `qty`, `status`, `ship_date`, `eta_date`, `customer_name`, `priority_flag`

## Out of Scope for v1.0 Target

- LLM-based reasoning (heuristic alerts only)
- RSS feed monitoring (planned v0.6)
- JSON event ingestor (planned v0.6)
- Web UI or API server
- Multi-user support
- Cloud storage integration
- Real-time event streaming
- Advanced NLP for entity extraction

## Current Implementation Status (v0.5)

### Implemented
- ✅ Event normalization
- ✅ Entity linking (network_linker)
- ✅ Alert generation (heuristic-based, deterministic)
- ✅ Alert correlation (v0.4)
- ✅ Daily brief (v0.5)
- ✅ Alert persistence (alerts stored in database)
- ✅ Decision/evidence boundary (structured evidence model)
- ✅ Robust ETA parsing with timezone handling
- ✅ Additive database migrations

### Planned for v0.6
- JSON event ingestor (batch processing)
- RSS feed monitoring
- Enhanced error handling and validation

### v1.0 Target Criteria

Hardstop will be considered v1.0 when:
- All core features are stable and well-tested
- Documentation is complete and accurate
- Migration path from v0.x is clear
- API surface is stable (no planned breaking changes)
- Performance characteristics are documented
- Test coverage meets quality thresholds

## Future Considerations

- **v0.6**: External event retrieval (JSON ingestor, RSS monitoring)
- **v1.0**: Stable API, complete documentation, production-shaped for personal use
- **v1.1+**: LLM agent for alert generation (optional enhancement)
- **v2.0**: Multi-domain support with pluggable domain packs

## Alignment with Execution Plan

The v1 scope ties directly to the execution priorities defined in
[`docs/EXECUTION_PLAN.md`](EXECUTION_PLAN.md):

- **P0** items (RunRecord coverage, deterministic fixtures) are hard
  prerequisites for declaring v1 readiness because they guarantee replayability.
- **P1** work (source health + suppression analytics) feeds the CLI health gates
  described earlier in this spec.
- **P2** improvements (canonicalization v2, impact scoring rationale, correlation
  evidence) ensure the Event and Alert schemas above stay stable.
- **P3** integrations (brief v2, export bundles) map to the CLI surface area and
  keep the CLI commands in this spec aligned with the actual artifact contracts.

As phases complete, update this specification alongside the execution plan to
capture any schema or CLI adjustments.

