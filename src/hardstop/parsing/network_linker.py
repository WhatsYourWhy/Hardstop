from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Optional, Tuple

import us
from sqlalchemy import or_
from sqlalchemy.orm import Session

from hardstop.database.schema import Facility, Lane, Shipment


def _normalize_state(state_value: str | None) -> Optional[str]:
    """
    Normalize state input into a two-letter postal code.
    
    Returns:
        Two-letter postal code if recognized, otherwise None.
    """
    if not state_value:
        return None
    
    normalized_input = state_value.strip()
    if not normalized_input:
        return None
    
    match = us.states.lookup(normalized_input)
    if match:
        return match.abbr
    
    # Ensure strict two-letter code
    if len(normalized_input) == 2 and normalized_input.isalpha():
        normalized_input = normalized_input.upper()
        match = us.states.lookup(normalized_input)
        if match:
            return match.abbr
    
    return None


def _extract_city_state(text: str) -> Optional[Tuple[str, str]]:
    # matches "Avon, IN" or "Avon, Indiana"
    # More restrictive: city must be a single word or hyphenated word before comma
    # This avoids matching "facility in Avon" as the city
    m = re.search(r"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?),\s*([A-Za-z]{2}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", text)
    if not m:
        return None
    city = m.group(1).strip().strip(".")
    state = _normalize_state(m.group(2).strip().strip("."))
    if not state:
        return None
    return city, state


def link_event_to_network(event: Dict, session: Session, max_shipments: int = 50) -> Dict:
    """
    Attach facilities/lanes/shipments to the event using SQLite context.
    Adds event["linking_notes"], event["link_confidence"], and event["link_provenance"]
    so you can see why matches happened and how confident we are.
    """
    text = f"{event.get('title','')} {event.get('raw_text','')}".strip()

    event.setdefault("facilities", [])
    event.setdefault("lanes", [])
    event.setdefault("shipments", [])
    event.setdefault("linking_notes", [])
    event.setdefault("link_confidence", {})
    event.setdefault("link_provenance", {})
    event.setdefault("facility_candidates", [])
    event.setdefault("lane_matches", [])

    facility_confidence = 0.0
    facility_provenance = None

    # 1) Try exact facility_id match in text (highest confidence)
    all_facility_ids = [r[0] for r in session.query(Facility.facility_id).all()]
    matched_ids = [fid for fid in all_facility_ids if fid and fid in text]
    if matched_ids:
        event["facilities"] = sorted(set(event["facilities"] + matched_ids))
        facility_confidence = 0.95
        facility_provenance = "FACILITY_ID_EXACT"
        event["linking_notes"].append(f"Facility match by exact ID in text: {matched_ids}")

    # 2) Try facility name substring match (medium-high confidence)
    if not event["facilities"]:
        facilities = session.query(Facility).all()
        name_hits = []
        text_l = text.lower()
        for f in facilities:
            if f.name and f.name.lower() in text_l:
                name_hits.append(f.facility_id)
        if name_hits:
            event["facilities"] = sorted(set(event["facilities"] + name_hits))
            facility_confidence = 0.85
            facility_provenance = "FACILITY_NAME_SUBSTRING"
            event["linking_notes"].append(f"Facility match by name substring: {name_hits}")

    # 3) Try city/state match from text (medium confidence)
    if not event["facilities"]:
        cs = _extract_city_state(text)
        if cs:
            city, state = cs
            # Check both normalized abbreviation and original state name
            # (database might have "Indiana" while we normalized to "IN")
            state_conditions = [
                Facility.state == state,
                Facility.state.ilike(state),
            ]
            state_match = us.states.lookup(state)
            if state_match:
                state_conditions.append(Facility.state.ilike(state_match.name))
            
            hits = (
                session.query(Facility)
                .filter(Facility.city.isnot(None))
                .filter(Facility.city.ilike(city))
                .filter(or_(*state_conditions))
                .all()
            )
            if hits:
                # Store all candidates
                event["facility_candidates"] = [h.facility_id for h in hits]
                
                # Tie-breaker logic for ambiguous matches
                if len(hits) > 1:
                    # Sort by: criticality_score (desc), then type priority (PLANT > DC > PORT)
                    def facility_sort_key(f):
                        criticality = f.criticality_score or 0
                        # Type priority: PLANT=3, DC=2, PORT=1, other=0
                        type_priority = {"PLANT": 3, "DC": 2, "PORT": 1}.get(f.type.upper() if f.type else "", 0)
                        return (-criticality, -type_priority)
                    
                    sorted_hits = sorted(hits, key=facility_sort_key)
                    top_facility = sorted_hits[0]
                    
                    # Check if we have a second signal (facility_id or name in text)
                    has_second_signal = False
                    text_l = text.lower()
                    for f in hits:
                        if f.facility_id in text or (f.name and f.name.lower() in text_l):
                            has_second_signal = True
                            top_facility = f  # Use the one with second signal
                            break
                    
                    if not has_second_signal:
                        # Ambiguous match - lower confidence and don't link shipments yet
                        facility_confidence = 0.45
                        facility_provenance = "CITY_STATE_AMBIGUOUS"
                        event["linking_notes"].append(
                            f"Ambiguous city/state match: {city}, {state} -> {len(hits)} facilities. "
                            f"Selected {top_facility.facility_id} (highest criticality/type). "
                            f"Confidence lowered due to ambiguity."
                        )
                    else:
                        facility_confidence = 0.70
                        facility_provenance = "CITY_STATE_WITH_SIGNAL"
                        event["linking_notes"].append(
                            f"Facility match by city/state with second signal: {city}, {state} -> {top_facility.facility_id}"
                        )
                    
                    # Only link the top facility
                    event["facilities"] = sorted(set(event["facilities"] + [top_facility.facility_id]))
                else:
                    # Single match - unambiguous
                    ids = [h.facility_id for h in hits]
                    event["facilities"] = sorted(set(event["facilities"] + ids))
                    facility_confidence = 0.70
                    facility_provenance = "CITY_STATE"
                    event["linking_notes"].append(f"Facility match by city/state: {city}, {state} -> {ids}")
            else:
                event["linking_notes"].append(f"No facility match for city/state: {city}, {state}")

    # Store facility confidence and provenance
    if event["facilities"]:
        event["link_confidence"]["facility"] = facility_confidence
        event["link_provenance"]["facility"] = facility_provenance

    # 2) If facilities found, link lanes
    if event["facilities"]:
        fac_ids = event["facilities"]
        fac_id_set = set(fac_ids)
        lanes = (
            session.query(Lane)
            .filter(or_(Lane.origin_facility_id.in_(fac_ids), Lane.dest_facility_id.in_(fac_ids)))
            .all()
        )
        lane_ids = [l.lane_id for l in lanes]
        if lane_ids:
            event["lanes"] = sorted(set(event["lanes"] + lane_ids))
            
            existing_lane_matches = [
                match for match in event.get("lane_matches", []) if isinstance(match, dict) and match.get("lane_id")
            ]
            lane_match_map = {match["lane_id"]: match for match in existing_lane_matches}
            
            for lane in lanes:
                match_sources = []
                if lane.origin_facility_id in fac_id_set:
                    match_sources.append("ORIGIN")
                if lane.dest_facility_id in fac_id_set:
                    match_sources.append("DESTINATION")
                
                if not match_sources:
                    continue
                
                match_type = "BOTH" if len(match_sources) == 2 else match_sources[0]
                lane_match_map[lane.lane_id] = {
                    "lane_id": lane.lane_id,
                    "match_type": match_type,
                }
            
            event["lane_matches"] = list(lane_match_map.values())
            # Lane confidence is 0.70 (inherited from facility relationship)
            event["link_confidence"]["lanes"] = 0.70
            event["link_provenance"]["lanes"] = "FACILITY_RELATION"
            event["linking_notes"].append(f"Linked lanes via facility match: {lane_ids}")

        # 3) If lanes found, link shipments
        if lane_ids:
            # Get all shipments (don't limit yet - we need to sort first)
            all_shipments = (
                session.query(Shipment)
                .filter(Shipment.lane_id.in_(lane_ids))
                .all()
            )
            
            if all_shipments:
                # Sort by priority_flag (descending: 1 before 0), then by eta_date (ascending: earliest first)
                def sort_key(shipment: Shipment) -> Tuple[int, str]:
                    # Priority: 1 (high) comes before 0 (low), so negate it
                    priority = -(shipment.priority_flag or 0)
                    # ETA date: use a far future date if missing, so missing dates sort last
                    eta = shipment.eta_date or "9999-12-31"
                    return (priority, eta)
                
                sorted_shipments = sorted(all_shipments, key=sort_key)
                
                # Track total before truncation
                total_linked = len(sorted_shipments)
                
                # Take top N
                top_shipments = sorted_shipments[:max_shipments]
                shipment_ids = [s.shipment_id for s in top_shipments]
                
                # Deduplicate and add to existing (preserve sort order)
                existing_shipments = set(event.get("shipments", []))
                new_shipment_ids = [sid for sid in shipment_ids if sid not in existing_shipments]
                # Preserve the sorted order (don't re-sort alphabetically)
                event["shipments"] = list(event.get("shipments", [])) + new_shipment_ids
                
                # Add truncation metadata if needed
                if total_linked > max_shipments:
                    event["shipments_truncated"] = True
                    event["shipments_total_linked"] = total_linked
                else:
                    event["shipments_truncated"] = False
                    event["shipments_total_linked"] = total_linked
                
                # Shipment confidence is 0.60 (lower confidence for indirect relationship)
                event["link_confidence"]["shipments"] = 0.60
                event["link_provenance"]["shipments"] = "LANE_RELATION"
                event["linking_notes"].append(
                    f"Linked shipments via lanes: {len(event['shipments'])} shipments"
                    + (f" (truncated from {total_linked})" if total_linked > max_shipments else "")
                )

    return event

