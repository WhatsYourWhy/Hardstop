import re
from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..database.schema import Facility, Lane, Shipment
from ..utils.logging import get_logger

logger = get_logger(__name__)


def attach_dummy_entities(event: Dict) -> Dict:
    """
    For the demo, pretend we matched the event to one facility and some shipments.

    In a real system, this would use NLP + DB context.
    """
    if not event.get("facilities"):
        event["facilities"] = ["PLANT-01"]
    if not event.get("shipments"):
        event["shipments"] = ["SHP-1001", "SHP-1002"]
    return event


def link_to_network(event: Dict, session: Session, days_ahead: int = 30) -> Dict:
    """
    Link an event to actual network data by:
    1. Looking up facilities by city/state or facility_id
    2. Finding upcoming shipments from those facilities
    
    Updates event["facilities"] and event["shipments"] with actual IDs.
    
    Args:
        event: Event dict with city, state, country, or facilities already set
        session: SQLAlchemy session
        days_ahead: How many days ahead to look for shipments (default 30)
    
    Returns:
        Updated event dict with facilities and shipments populated
    """
    matched_facility_ids = []
    
    # If facilities are already specified, use those
    if event.get("facilities"):
        matched_facility_ids = event["facilities"]
        logger.info(f"Using pre-specified facilities: {matched_facility_ids}")
    else:
        # Extract city/state from event or try to parse from raw_text
        city = event.get("city", "").strip() if event.get("city") else None
        state = event.get("state", "").strip() if event.get("state") else None
        country = event.get("country", "").strip() if event.get("country") else None
        
        # If not set, try to extract from raw_text (e.g., "Avon, Indiana")
        if not city and not state and event.get("raw_text"):
            text = event.get("raw_text", "")
            # Look for patterns like "City, State" or "City, State, Country"
            location_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
            match = re.search(location_pattern, text)
            if match:
                city = match.group(1)
                state = match.group(2)
                logger.info(f"Extracted location from text: {city}, {state}")
        
        if city or state:
            # Build query conditions
            conditions = []
            if city:
                conditions.append(Facility.city.ilike(f"%{city}%"))
            if state:
                conditions.append(Facility.state.ilike(f"%{state}%"))
            if country:
                conditions.append(Facility.country.ilike(f"%{country}%"))
            
            if conditions:
                query = session.query(Facility).filter(or_(*conditions))
                facilities = query.all()
                matched_facility_ids = [f.facility_id for f in facilities]
                logger.info(f"Matched {len(matched_facility_ids)} facilities by location: {city}, {state}, {country}")
        
        # Also try to extract facility IDs from raw text (simple heuristic)
        if not matched_facility_ids and event.get("raw_text"):
            # Look for patterns like "PLANT-01" or "FAC-123" in text
            text = event.get("raw_text", "")
            facility_pattern = r'\b([A-Z]+-\d+)\b'
            potential_ids = re.findall(facility_pattern, text)
            if potential_ids:
                # Verify they exist in DB
                existing = session.query(Facility).filter(
                    Facility.facility_id.in_(potential_ids)
                ).all()
                if existing:
                    matched_facility_ids = [f.facility_id for f in existing]
                    logger.info(f"Matched facilities from text: {matched_facility_ids}")
    
    # Update event with matched facilities
    if matched_facility_ids:
        event["facilities"] = matched_facility_ids
    else:
        logger.warning(f"Could not match event to any facilities. Event: {event.get('title', 'Unknown')}")
        event["facilities"] = []
    
    # Find upcoming shipments from matched facilities
    matched_shipment_ids = []
    if matched_facility_ids:
        # Calculate date threshold
        today = datetime.now().date()
        future_date = today + timedelta(days=days_ahead)
        
        # Find lanes originating from matched facilities
        lanes = session.query(Lane).filter(
            Lane.origin_facility_id.in_(matched_facility_ids)
        ).all()
        lane_ids = [l.lane_id for l in lanes]
        
        if lane_ids:
            # Find shipments on those lanes with upcoming ship_date or eta_date
            shipments = session.query(Shipment).filter(
                Shipment.lane_id.in_(lane_ids)
            ).all()
            
            # Filter by date (if ship_date or eta_date is set and within range)
            for shipment in shipments:
                include = False
                if shipment.ship_date:
                    try:
                        ship_dt = datetime.strptime(shipment.ship_date, "%Y-%m-%d").date()
                        if today <= ship_dt <= future_date:
                            include = True
                    except (ValueError, AttributeError):
                        pass
                if not include and shipment.eta_date:
                    try:
                        eta_dt = datetime.strptime(shipment.eta_date, "%Y-%m-%d").date()
                        if today <= eta_dt <= future_date:
                            include = True
                    except (ValueError, AttributeError):
                        pass
                # If no date filtering worked, include if status suggests it's active
                if not include and shipment.status and shipment.status.upper() in ["PENDING", "IN_TRANSIT", "SCHEDULED"]:
                    include = True
                
                if include:
                    matched_shipment_ids.append(shipment.shipment_id)
            
            logger.info(f"Found {len(matched_shipment_ids)} upcoming shipments from matched facilities")
        else:
            logger.info(f"No lanes found originating from facilities: {matched_facility_ids}")
    
    # Update event with matched shipments
    event["shipments"] = matched_shipment_ids
    
    # Also populate lanes if we found any
    if matched_facility_ids:
        lanes = session.query(Lane).filter(
            Lane.origin_facility_id.in_(matched_facility_ids)
        ).all()
        event["lanes"] = [l.lane_id for l in lanes]
    else:
        event["lanes"] = []
    
    return event

