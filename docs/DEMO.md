# Hardstop demo walkthrough

This is a short, deterministic story you can run locally. All names and weather
details below are **synthetic / fictional** — nothing here is a real company,
person, or weather bulletin.

## The story

1. A fictional supplier plant sits in **Avon, Indiana** (`PLANT-01`,
   “Avon Chemical Manufacturing” in the demo network CSVs).
2. A synthetic winter-storm event mentions that city/state.
3. Hardstop loads the network, links the event to `PLANT-01` (and its lanes /
   shipments), scores why an alert should fire, and writes preserved incident
   evidence under `output/incidents/`.

## Run it

From the repo root (after install — see the README Quick Start):

```bash
hardstop ingest
hardstop demo --mode pinned
```

Pinned mode freezes time and IDs so the output is reproducible:

- timestamp: `2025-12-29T17:00:00Z`
- seed: `demo-pinned-seed.v1`
- run id: `demo-golden-run.v1`

Optional: point at the weather fixture explicitly (same default in
`hardstop.config.yaml`):

```bash
hardstop demo --mode pinned --event tests/fixtures/event_weather.json
```

## What to look for

On a successful pinned run you should see:

| Piece | What it means |
| --- | --- |
| `risk_type: WEATHER` | Event classified as weather |
| `scope.facilities: ["PLANT-01"]` | Linked to the fictional Avon supplier plant |
| `evidence.diagnostics.impact_score_breakdown` | Why the score fired (facility criticality, lane volume, priority shipments) |
| `evidence.linking_notes` | City/state → facility → lanes → shipments |
| `evidence.incident_evidence.artifact_path` | Preserved evidence JSON + hash |

## Sample output (captured from a real pinned run)

Trimmed from `hardstop demo --mode pinned` stdout (full JSON is longer):

```json
{
  "alert_id": "ALERT-20251229-d31a370b",
  "risk_type": "WEATHER",
  "classification": 2,
  "summary": "[SYNTHETIC] Winter storm warning near Avon, Indiana supplier facility",
  "scope": {
    "facilities": ["PLANT-01"],
    "lanes": ["LANE-001", "LANE-002", "LANE-003"],
    "shipments": ["SHP-1001", "SHP-1002", "SHP-1005", "SHP-1004", "SHP-1003", "SHP-1006"]
  },
  "reasoning": [
    "Event type: WEATHER",
    "Classification: 2 (from network_impact_score=4, quality_cap=2)",
    "Scope derived from network entity matching."
  ],
  "evidence": {
    "diagnostics": {
      "impact_score": 4,
      "impact_score_breakdown": [
        "+2: Facility criticality_score >= 7 (PLANT-01=8)",
        "+1: Lane volume_score >= 7 (LANE-001=8)",
        "+1: Priority shipments found (3 total)"
      ],
      "link_provenance": {
        "facility": "CITY_STATE",
        "lanes": "FACILITY_RELATION",
        "shipments": "LANE_RELATION"
      }
    },
    "linking_notes": [
      "Facility match by city/state: Avon, IN -> ['PLANT-01']",
      "Linked lanes via facility match: ['LANE-001', 'LANE-002', 'LANE-003']",
      "Linked shipments via lanes: 6 shipments",
      "Created new correlated alert via key=WEATHER|PLANT-01|LANE-001"
    ],
    "incident_evidence": {
      "artifact_hash": "e7a61c0bc07242aec3db14d4ba998d688207925d0a97dfb27a37508d351ecd3e",
      "artifact_path": "output/incidents/ALERT-20251229-d31a370b__EVT-DEMO-0001__WEATHER_PLANT-01_LANE-001.json"
    }
  }
}
```

Log lines from the same run also print the pinned context and linking notes.

## Fixtures used

| Role | Path |
| --- | --- |
| Event | `tests/fixtures/event_weather.json` |
| Facilities / lanes / shipments | `tests/fixtures/facilities.csv`, `lanes.csv`, `shipments_snapshot.csv` |

An older spill fixture (`tests/fixtures/event_spill.json`) still backs golden /
determinism regression tests; it is not the default demo story.
