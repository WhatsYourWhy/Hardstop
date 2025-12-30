import csv
from pathlib import Path
from typing import Dict

from sqlalchemy.orm import Session

from ..database.schema import Facility, Lane, Shipment
from ..utils.logging import get_logger

logger = get_logger(__name__)


def load_facilities_from_csv(csv_path: Path, session: Session) -> int:
    """
    Load facilities from CSV and insert into database.
    
    Expected CSV columns: facility_id, name, type, city, state, country, lat, lon, criticality_score
    """
    if not csv_path.exists():
        logger.warning(f"CSV file not found: {csv_path}")
        return 0
    
    count = 0
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Handle empty/missing values
            facility = Facility(
                facility_id=row.get("facility_id", "").strip(),
                name=row.get("name", "").strip(),
                type=row.get("type", "").strip(),
                city=row.get("city", "").strip() or None,
                state=row.get("state", "").strip() or None,
                country=row.get("country", "").strip() or None,
                lat=float(row["lat"]) if row.get("lat") and row["lat"].strip() else None,
                lon=float(row["lon"]) if row.get("lon") and row["lon"].strip() else None,
                criticality_score=int(row["criticality_score"]) if row.get("criticality_score") and row["criticality_score"].strip() else None,
            )
            session.merge(facility)  # Use merge to handle duplicates
            count += 1
    
    session.commit()
    logger.info(f"Loaded {count} facilities from {csv_path}")
    return count


def load_lanes_from_csv(csv_path: Path, session: Session) -> int:
    """
    Load lanes from CSV and insert into database.
    
    Expected CSV columns: lane_id, origin_facility_id, dest_facility_id, mode, carrier_name, avg_transit_days, volume_score
    """
    if not csv_path.exists():
        logger.warning(f"CSV file not found: {csv_path}")
        return 0
    
    count = 0
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lane = Lane(
                lane_id=row.get("lane_id", "").strip(),
                origin_facility_id=row.get("origin_facility_id", "").strip(),
                dest_facility_id=row.get("dest_facility_id", "").strip(),
                mode=row.get("mode", "").strip() or None,
                carrier_name=row.get("carrier_name", "").strip() or None,
                avg_transit_days=float(row["avg_transit_days"]) if row.get("avg_transit_days") and row["avg_transit_days"].strip() else None,
                volume_score=int(row["volume_score"]) if row.get("volume_score") and row["volume_score"].strip() else None,
            )
            session.merge(lane)
            count += 1
    
    session.commit()
    logger.info(f"Loaded {count} lanes from {csv_path}")
    return count


def load_shipments_from_csv(csv_path: Path, session: Session) -> int:
    """
    Load shipments from CSV and insert into database.
    
    Expected CSV columns: shipment_id, order_id, lane_id, sku_id, qty, status, ship_date, eta_date, customer_name, priority_flag
    """
    if not csv_path.exists():
        logger.warning(f"CSV file not found: {csv_path}")
        return 0
    
    count = 0
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            shipment = Shipment(
                shipment_id=row.get("shipment_id", "").strip(),
                order_id=row.get("order_id", "").strip() or None,
                lane_id=row.get("lane_id", "").strip(),
                sku_id=row.get("sku_id", "").strip() or None,
                qty=float(row["qty"]) if row.get("qty") and row["qty"].strip() else None,
                status=row.get("status", "").strip() or None,
                ship_date=row.get("ship_date", "").strip() or None,
                eta_date=row.get("eta_date", "").strip() or None,
                customer_name=row.get("customer_name", "").strip() or None,
                priority_flag=int(row["priority_flag"]) if row.get("priority_flag") and row["priority_flag"].strip() else None,
            )
            session.merge(shipment)
            count += 1
    
    session.commit()
    logger.info(f"Loaded {count} shipments from {csv_path}")
    return count


def ingest_all_csvs(
    facilities_path: Path,
    lanes_path: Path,
    shipments_path: Path,
    session: Session,
) -> Dict[str, int]:
    """
    Load all three CSV files into the database.
    
    Returns a dict with counts: {"facilities": X, "lanes": Y, "shipments": Z}
    """
    counts = {
        "facilities": load_facilities_from_csv(facilities_path, session),
        "lanes": load_lanes_from_csv(lanes_path, session),
        "shipments": load_shipments_from_csv(shipments_path, session),
    }
    return counts

