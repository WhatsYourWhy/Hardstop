# Client Network CSV Contract

This document defines the CSV format required for loading client network data (facilities, lanes, shipments) into Hardstop.

## Overview

Hardstop loads network data from three CSV files:
- `facilities.csv` - Facility definitions
- `lanes.csv` - Transportation lanes between facilities
- `shipments_snapshot.csv` - Active shipments on lanes

Use the `hardstop ingest` command to load these files into the SQLite database.

## Facilities CSV

**File**: `facilities.csv`

**Required Columns**:
- `facility_id` (string, required) - Unique facility identifier (e.g., "PLANT-01", "DC-02")
- `name` (string, required) - Facility name
- `type` (string, required) - Facility type (e.g., "PLANT", "DC", "PORT", "WAREHOUSE")
- `city` (string, optional) - City name
- `state` (string, optional) - State name or two-letter code
- `country` (string, optional) - Country name or code
- `lat` (float, optional) - Latitude coordinate
- `lon` (float, optional) - Longitude coordinate
- `criticality_score` (integer, optional) - Criticality score (0-10, higher = more critical)

**ID Format**: Facility IDs should be unique, alphanumeric strings. Common patterns: "PLANT-01", "DC-02", "FACILITY-001"

**Example**:
```csv
facility_id,name,type,city,state,country,lat,lon,criticality_score
PLANT-01,Avon Chemical Manufacturing,PLANT,Avon,Indiana,USA,39.7606,-86.3956,8
DC-01,Memphis Logistics Hub,DC,Memphis,Tennessee,USA,35.1495,-90.0490,7
```

## Lanes CSV

**File**: `lanes.csv`

**Required Columns**:
- `lane_id` (string, required) - Unique lane identifier (e.g., "LANE-001")
- `origin_facility_id` (string, required) - Origin facility ID (must exist in facilities.csv)
- `dest_facility_id` (string, required) - Destination facility ID (must exist in facilities.csv)
- `mode` (string, optional) - Transportation mode (e.g., "TRUCK", "RAIL", "AIR", "OCEAN")
- `carrier_name` (string, optional) - Carrier name
- `avg_transit_days` (float, optional) - Average transit time in days
- `volume_score` (integer, optional) - Volume score (0-10, higher = more volume)

**ID Format**: Lane IDs should be unique, alphanumeric strings. Common patterns: "LANE-001", "LANE-ORIGIN-DEST"

**Foreign Key Constraints**: `origin_facility_id` and `dest_facility_id` must reference existing `facility_id` values from facilities.csv.

**Example**:
```csv
lane_id,origin_facility_id,dest_facility_id,mode,carrier_name,avg_transit_days,volume_score
LANE-001,PLANT-01,DC-01,TRUCK,FedEx Logistics,2.5,8
LANE-002,DC-01,DC-02,RAIL,BNSF Railway,3.0,7
```

## Shipments CSV

**File**: `shipments_snapshot.csv`

**Required Columns**:
- `shipment_id` (string, required) - Unique shipment identifier (e.g., "SHIP-001")
- `order_id` (string, optional) - Order identifier
- `lane_id` (string, required) - Lane ID (must exist in lanes.csv)
- `sku_id` (string, optional) - SKU identifier
- `qty` (float, optional) - Quantity
- `status` (string, optional) - Shipment status (e.g., "IN_TRANSIT", "DELIVERED", "PENDING")
- `ship_date` (string, optional) - Ship date (ISO 8601 format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)
- `eta_date` (string, optional) - Estimated arrival date (ISO 8601 format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)
- `customer_name` (string, optional) - Customer name
- `priority_flag` (integer, optional) - Priority flag (0 = normal, 1 = priority)

**ID Format**: Shipment IDs should be unique, alphanumeric strings. Common patterns: "SHIP-001", "ORDER-12345-SHIP-1"

**Foreign Key Constraints**: `lane_id` must reference an existing `lane_id` value from lanes.csv.

**Date Format**: Dates should be in ISO 8601 format. Date-only values (YYYY-MM-DD) are treated as end-of-day UTC.

**Example**:
```csv
shipment_id,order_id,lane_id,sku_id,qty,status,ship_date,eta_date,customer_name,priority_flag
SHIP-001,ORD-12345,LANE-001,SKU-ABC,100.0,IN_TRANSIT,2025-01-15,2025-01-17,Acme Corp,1
SHIP-002,ORD-12346,LANE-001,SKU-XYZ,50.0,IN_TRANSIT,2025-01-16,2025-01-18,Widget Inc,0
```

## Loading Data

1. Prepare your three CSV files following the formats above
2. Run `hardstop ingest` to load the data into SQLite
3. Verify loading with `hardstop doctor` (checks database health)

## Notes

- All CSV files must use UTF-8 encoding
- Headers are case-sensitive (must match column names exactly)
- Empty values are allowed for optional columns
- Duplicate IDs are handled via merge (last write wins)
- Facility IDs are used for network linking in event processing
- Lane IDs link shipments to transportation routes
- Shipment ETA dates are used for near-term risk assessment (48-hour window)

