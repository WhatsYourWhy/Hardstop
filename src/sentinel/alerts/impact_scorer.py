"""Network impact scoring for alert classification."""

from datetime import datetime, timedelta
from typing import Dict, Tuple

from sqlalchemy.orm import Session

from ..database.schema import Facility, Lane, Shipment


def calculate_network_impact_score(event: Dict, session: Session) -> Tuple[int, list[str]]:
    """
    Calculate network impact score based on linked facilities, lanes, and shipments.
    
    Scoring rules (using 1-10 scale):
    - +2 if any facility criticality_score ≥ 7
    - +1 if any lane volume_score ≥ 7
    - +1 if any shipment priority_flag = 1 (true)
    - +1 more if >=5 priority shipments
    - +1 more if any priority shipment ETA within 48h
    - +1 if shipment_count ≥ 10
    - +1 if event_type in {SPILL, STRIKE, CLOSURE}
    
    Returns:
        Tuple of (impact_score, breakdown_list)
    """
    score = 0
    breakdown = []
    
    # Check facility criticality
    facility_ids = event.get("facilities", [])
    if facility_ids:
        facilities = session.query(Facility).filter(
            Facility.facility_id.in_(facility_ids)
        ).all()
        for facility in facilities:
            if facility.criticality_score and facility.criticality_score >= 7:
                score += 2
                breakdown.append(f"+2: Facility criticality_score >= 7 ({facility.facility_id}={facility.criticality_score})")
                break  # Only count once
    
    # Check lane volume
    lane_ids = event.get("lanes", [])
    if lane_ids:
        lanes = session.query(Lane).filter(
            Lane.lane_id.in_(lane_ids)
        ).all()
        for lane in lanes:
            if lane.volume_score and lane.volume_score >= 7:
                score += 1
                breakdown.append(f"+1: Lane volume_score >= 7 ({lane.lane_id}={lane.volume_score})")
                break  # Only count once
    
    # Check shipment priority (enhanced scoring)
    shipment_ids = event.get("shipments", [])
    if shipment_ids:
        shipments = session.query(Shipment).filter(
            Shipment.shipment_id.in_(shipment_ids)
        ).all()
        
        priority_shipments = [s for s in shipments if s.priority_flag == 1]
        priority_count = len(priority_shipments)
        
        if priority_count > 0:
            score += 1
            breakdown.append(f"+1: Priority shipments found ({priority_count} total)")
            
            # Additional points for multiple priority shipments
            if priority_count >= 5:
                score += 1
                breakdown.append(f"+1: >=5 priority shipments ({priority_count})")
            
            # Check for near-term ETA (within 48h)
            today = datetime.now().date()
            cutoff = today + timedelta(days=2)
            near_term_count = 0
            for shipment in priority_shipments:
                if shipment.eta_date:
                    try:
                        eta = datetime.strptime(shipment.eta_date, "%Y-%m-%d").date()
                        if today <= eta <= cutoff:
                            near_term_count += 1
                    except (ValueError, AttributeError):
                        pass
            
            if near_term_count > 0:
                score += 1
                breakdown.append(f"+1: Priority shipment ETA within 48h ({near_term_count} shipments)")
        
        # Check shipment count
        shipment_count = len(shipment_ids)
        if shipment_count >= 10:
            score += 1
            breakdown.append(f"+1: Shipment count >= 10 ({shipment_count})")
    
    # Check event type (check both event_type field and title/raw_text for keywords)
    event_type = event.get("event_type", "").upper()
    text = f"{event.get('title', '')} {event.get('raw_text', '')}".upper()
    high_impact_types = {"SPILL", "STRIKE", "CLOSURE"}
    high_impact_keywords = {"SPILL", "STRIKE", "CLOSURE", "CLOSED", "SHUTDOWN"}
    
    if event_type in high_impact_types:
        score += 1
        breakdown.append(f"+1: Event type in high-impact types ({event_type})")
    elif any(keyword in text for keyword in high_impact_keywords):
        score += 1
        matched_keyword = next((k for k in high_impact_keywords if k in text), "unknown")
        breakdown.append(f"+1: High-impact keyword detected ({matched_keyword})")
    
    if not breakdown:
        breakdown.append("No impact factors detected")
    
    return score, breakdown


def map_score_to_classification(impact_score: int) -> int:
    """
    Map impact score to alert classification (risk tier).
    
    - Score 0-1 → classification 0 (Interesting)
    - Score 2-3 → classification 1 (Relevant)
    - Score 4+ → classification 2 (Impactful)
    """
    if impact_score >= 4:
        return 2
    elif impact_score >= 2:
        return 1
    else:
        return 0

