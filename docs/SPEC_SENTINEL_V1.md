# Sentinel v1 Specification

## Scope

Sentinel v1 is a **local-first, domain-agnostic event → risk → alert engine** with a focus on supply chain risk management.

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

- **Risk Assessment**: Map event severity to alert priority
- **Scope Definition**: Identify affected facilities, shipments, lanes
- **Action Recommendations**: Generate suggested next steps

### 4. CLI Interface

- `sentinel demo`: Run end-to-end demo pipeline
- `sentinel ingest`: Load network data from CSV files
- `sentinel brief --today`: Generate daily brief (stub in v1)

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
    "priority": int,          # 1-5
    "status": str,            # "OPEN", "CLOSED", etc.
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
    "confidence_score": float | None
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

### `sentinel.config.yaml`

```yaml
storage:
  sqlite_path: "sentinel.db"

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

### `sentinel demo`

Runs the end-to-end demo pipeline:
1. Loads sample event from config
2. Normalizes event
3. Links to network data
4. Generates alert
5. Prints JSON output

**Usage:**
```bash
sentinel demo
```

### `sentinel ingest`

Loads network data from CSV files into SQLite.

**Usage:**
```bash
sentinel ingest
```

**Options:**
- `--fixtures`: Explicitly use fixture files (optional, default behavior)

### `sentinel brief --today`

Generates daily brief (stub in v1).

**Usage:**
```bash
sentinel brief --today
```

**Status:** Stub implementation in v1. Will show placeholder message.

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

## Out of Scope for v1

- LLM-based reasoning (heuristic alerts only)
- RSS feed monitoring
- Web UI or API server
- Multi-user support
- Cloud storage integration
- Real-time event streaming
- Advanced NLP for entity extraction
- Alert persistence to database (alerts are generated on-demand)

## Future Considerations

- **v1.1**: LLM agent for alert generation
- **v1.2**: RSS ingestion and daily brief
- **v1.3**: Alert persistence and historical analysis
- **v2.0**: Multi-domain support with pluggable domain packs

