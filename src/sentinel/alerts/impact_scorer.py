"""Network impact scoring for alert classification."""

from typing import Dict

from sqlalchemy.orm import Session

from ..database.schema import Facility, Lane, Shipment


def calculate_network_impact_score(event: Dict, session: Session) -> int:
    """
    Calculate network impact score based on linked facilities, lanes, and shipments.
    
    Scoring rules:
    - +2 if any facility criticality_score ≥ 4
    - +1 if any lane volume_score ≥ 4
    - +1 if any shipment priority_flag = 1 (true)
    - +1 if shipment_count ≥ 10
    - +1 if event_type in {SPILL, STRIKE, CLOSURE}
    
    Returns:
        Impact score (0-6+)
    """
    score = 0
    
    # Check facility criticality
    facility_ids = event.get("facilities", [])
    if facility_ids:
        facilities = session.query(Facility).filter(
            Facility.facility_id.in_(facility_ids)
        ).all()
        for facility in facilities:
            if facility.criticality_score and facility.criticality_score >= 4:
                score += 2
                break  # Only count once
    
    # Check lane volume
    lane_ids = event.get("lanes", [])
    if lane_ids:
        lanes = session.query(Lane).filter(
            Lane.lane_id.in_(lane_ids)
        ).all()
        for lane in lanes:
            if lane.volume_score and lane.volume_score >= 4:
                score += 1
                break  # Only count once
    
    # Check shipment priority
    shipment_ids = event.get("shipments", [])
    if shipment_ids:
        shipments = session.query(Shipment).filter(
            Shipment.shipment_id.in_(shipment_ids)
        ).all()
        for shipment in shipments:
            if shipment.priority_flag == 1:
                score += 1
                break  # Only count once
        
        # Check shipment count
        shipment_count = len(shipment_ids)
        if shipment_count >= 10:
            score += 1
    
    # Check event type (check both event_type field and title/raw_text for keywords)
    event_type = event.get("event_type", "").upper()
    text = f"{event.get('title', '')} {event.get('raw_text', '')}".upper()
    high_impact_types = {"SPILL", "STRIKE", "CLOSURE"}
    high_impact_keywords = {"SPILL", "STRIKE", "CLOSURE", "CLOSED", "SHUTDOWN"}
    
    if event_type in high_impact_types:
        score += 1
    elif any(keyword in text for keyword in high_impact_keywords):
        score += 1
    
    return score


def map_score_to_priority(impact_score: int) -> int:
    """
    Map impact score to alert priority.
    
    - Score 0-1 → priority 0 (low)
    - Score 2-3 → priority 1 (medium)
    - Score 4+ → priority 2 (high)
    """
    if impact_score >= 4:
        return 2
    elif impact_score >= 2:
        return 1
    else:
        return 0

