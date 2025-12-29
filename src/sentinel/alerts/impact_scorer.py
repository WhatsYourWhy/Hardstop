"""Network impact scoring for alert classification."""

from functools import lru_cache
from datetime import datetime, timedelta, time, timezone
from typing import Dict, List, Tuple, Optional

from sqlalchemy.orm import Session

from ..config.loader import load_keywords_config
from ..database.schema import Facility, Lane, Shipment


DEFAULT_RISK_KEYWORDS: List[Dict[str, int]] = [
    {"term": "SPILL", "weight": 1},
    {"term": "STRIKE", "weight": 1},
    {"term": "CLOSURE", "weight": 1},
    {"term": "CLOSED", "weight": 1},
    {"term": "SHUTDOWN", "weight": 1},
]


@lru_cache(maxsize=1)
def _load_risk_keywords() -> List[Dict[str, int]]:
    """
    Load risk keywords from config with fallback defaults.
    """
    try:
        config = load_keywords_config()
        keywords = config.get("risk_keywords", [])
        if keywords:
            return keywords
    except FileNotFoundError:
        pass
    except ValueError:
        pass
    return DEFAULT_RISK_KEYWORDS


def parse_eta_date_safely(eta_date_str: Optional[str]) -> Optional[datetime]:
    """
    Safely parse an ETA date string into a datetime object.
    
    Handles:
    - Date-only strings (YYYY-MM-DD) - treated as end-of-day UTC
    - Datetime strings (YYYY-MM-DD HH:MM:SS) - parsed as-is
    - Invalid/missing dates - returns None
    
    Args:
        eta_date_str: Date string to parse, or None
        
    Returns:
        datetime object in UTC, or None if parsing fails
    """
    if not eta_date_str:
        return None
    
    # Handle non-string types gracefully
    if not isinstance(eta_date_str, str):
        return None
    
    eta_date_str = eta_date_str.strip()
    if not eta_date_str:
        return None
    
    try:
        # Try parsing as date-only (YYYY-MM-DD)
        if len(eta_date_str) == 10 and eta_date_str.count('-') == 2:
            date_obj = datetime.strptime(eta_date_str, "%Y-%m-%d").date()
            # Treat date-only as end-of-day UTC for consistency
            # Use 23:59:59 to represent end of day
            return datetime.combine(date_obj, time(23, 59, 59), tzinfo=timezone.utc)
        
        # Try parsing as datetime (YYYY-MM-DD HH:MM:SS or variants)
        # Common formats
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S%z",
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(eta_date_str, fmt)
                # If no timezone info, assume UTC
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        
        # If all parsing attempts fail, return None
        return None
        
    except (ValueError, AttributeError, TypeError) as e:
        # Log the error but don't crash - just skip this date
        # In production, you might want to log this for monitoring
        return None


def is_eta_within_48h(eta_date_str: Optional[str], now: Optional[datetime] = None) -> bool:
    """
    Check if an ETA date is within the 48h forward window or 7d lookback.
    
    Args:
        eta_date_str: ETA date string to check
        now: Current datetime (defaults to now in UTC). Used for testing.
        
    Returns:
        True if ETA is within 48 hours, False otherwise (or if parsing fails)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        # If now is naive, assume UTC
        now = now.replace(tzinfo=timezone.utc)
    
    eta_dt = parse_eta_date_safely(eta_date_str)
    if eta_dt is None:
        return False
    
    # Ensure both datetimes are timezone-aware
    if eta_dt.tzinfo is None:
        eta_dt = eta_dt.replace(tzinfo=timezone.utc)
    
    # Calculate time difference
    time_diff = eta_dt - now
    
    # Consider late shipments up to 7 days back and 48h forward
    return timedelta(days=-7) <= time_diff <= timedelta(hours=48)


def calculate_network_impact_score(
    event: Dict,
    session: Session,
    trust_tier: Optional[int] = None,
    weighting_bias: Optional[int] = None,
) -> Tuple[int, list[str]]:
    """
    Calculate network impact score based on linked facilities, lanes, and shipments.
    
    Scoring rules (using 0-10 scale):
    - Base network impact score (from facilities, lanes, shipments, event type)
    - Trust tier bonus: +1 for tier 3, 0 for tier 2, -1 for tier 1
    - Weighting bias: add bias value (manual nudge)
    - Final score capped at 0-10
    
    Args:
        event: Event dict with facilities, lanes, shipments
        session: SQLAlchemy session for network queries
        trust_tier: Optional trust tier (1|2|3). Default 2 if None.
        weighting_bias: Optional weighting bias (-2..+2). Default 0 if None.
    
    Returns:
        Tuple of (impact_score, breakdown_list)
        Breakdown shows each step in order for auditability
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
            # Use robust parsing that handles timezone drift and bad dates
            near_term_count = 0
            for shipment in priority_shipments:
                if is_eta_within_48h(shipment.eta_date):
                    near_term_count += 1
            
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
    text = f"{event.get('title', '')} {event.get('raw_text', '')}"
    text_upper = text.upper()
    high_impact_types = {"SPILL", "STRIKE", "CLOSURE"}
    
    if event_type in high_impact_types:
        score += 1
        breakdown.append(f"+1: Event type in high-impact types ({event_type})")
    else:
        keyword_matches = [entry for entry in _load_risk_keywords() if entry["term"] in text_upper]
        if keyword_matches:
            total_weight = sum(entry.get("weight", 1) for entry in keyword_matches)
            score += total_weight
            matched_terms = ", ".join(entry["term"] for entry in keyword_matches)
            breakdown.append(f"+{total_weight}: High-impact keywords detected ({matched_terms})")
    
    if not breakdown:
        breakdown.append("No impact factors detected")
    
    # Apply v0.7 trust tier bonus and weighting bias (in order)
    base_score = score
    
    # Apply trust tier bonus
    if trust_tier is None:
        trust_tier = 2  # Default
    
    if trust_tier == 3:
        score += 1
        breakdown.append("+1: Trust tier 3 bonus (official/government source)")
    elif trust_tier == 1:
        score -= 1
        breakdown.append("-1: Trust tier 1 penalty (lower trust source)")
    # trust_tier == 2: no change (default)
    
    # Apply weighting bias
    if weighting_bias is None:
        weighting_bias = 0  # Default
    
    if weighting_bias != 0:
        score += weighting_bias
        breakdown.append(f"{'+' if weighting_bias > 0 else ''}{weighting_bias}: Weighting bias (manual adjustment)")
    
    # Cap final score at 0-10
    original_score = score
    score = max(0, min(10, score))
    if score != original_score:
        if original_score > 10:
            breakdown.append(f"Capped at 10 (was {original_score})")
        elif original_score < 0:
            breakdown.append(f"Capped at 0 (was {original_score})")
    
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

