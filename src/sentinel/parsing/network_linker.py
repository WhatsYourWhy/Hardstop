from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from sentinel.database.schema import Facility, Lane, Shipment


US_STATE_TO_ABBR = {
    "indiana": "IN",
    "illinois": "IL",
    "ohio": "OH",
    "michigan": "MI",
    "kentucky": "KY",
    # expand as needed
}


def _normalize_state(s: str) -> str:
    s = s.strip()
    if len(s) == 2:
        return s.upper()
    return US_STATE_TO_ABBR.get(s.lower(), s.upper())


def _extract_city_state(text: str) -> Optional[Tuple[str, str]]:
    # matches "Avon, IN" or "Avon, Indiana"
    m = re.search(r"\b([A-Z][a-zA-Z.\- ]+?),\s*([A-Za-z]{2}|[A-Za-z ]{3,})\b", text)
    if not m:
        return None
    city = m.group(1).strip().strip(".")
    state = _normalize_state(m.group(2).strip().strip("."))
    return city, state


def link_event_to_network(event: Dict, session: Session, max_shipments: int = 50) -> Dict:
    """
    Attach facilities/lanes/shipments to the event using SQLite context.
    Adds event["linking_notes"] so you can see why matches happened.
    """
    text = f"{event.get('title','')} {event.get('raw_text','')}".strip()

    event.setdefault("facilities", [])
    event.setdefault("lanes", [])
    event.setdefault("shipments", [])
    event.setdefault("linking_notes", [])

    # 1) Try city/state match from text
    cs = _extract_city_state(text)
    if cs and not event["facilities"]:
        city, state = cs
        # Check both normalized abbreviation and original state name
        # (database might have "Indiana" while we normalized to "IN")
        state_conditions = [
            Facility.state == state,
            Facility.state.ilike(state),
        ]
        # If state is an abbreviation, also check for full name
        if len(state) == 2:
            # Find full state name from abbreviation (reverse lookup)
            for full_name, abbr in US_STATE_TO_ABBR.items():
                if abbr == state:
                    state_conditions.append(Facility.state.ilike(full_name))
                    break
        
        hits = (
            session.query(Facility)
            .filter(Facility.city.isnot(None))
            .filter(Facility.city.ilike(city))
            .filter(or_(*state_conditions))
            .all()
        )
        if hits:
            ids = [h.facility_id for h in hits]
            event["facilities"] = sorted(set(event["facilities"] + ids))
            event["linking_notes"].append(f"Facility match by city/state: {city}, {state} -> {ids}")
        else:
            event["linking_notes"].append(f"No facility match for city/state: {city}, {state}")

    # 2) If facilities found, link lanes
    if event["facilities"]:
        fac_ids = event["facilities"]
        lanes = (
            session.query(Lane)
            .filter(or_(Lane.origin_facility_id.in_(fac_ids), Lane.dest_facility_id.in_(fac_ids)))
            .all()
        )
        lane_ids = [l.lane_id for l in lanes]
        if lane_ids:
            event["lanes"] = sorted(set(event["lanes"] + lane_ids))
            event["linking_notes"].append(f"Linked lanes via facility match: {lane_ids}")

        # 3) If lanes found, link shipments
        if lane_ids:
            shipments = (
                session.query(Shipment)
                .filter(Shipment.lane_id.in_(lane_ids))
                .limit(max_shipments)
                .all()
            )
            shipment_ids = [s.shipment_id for s in shipments]
            if shipment_ids:
                event["shipments"] = sorted(set(event["shipments"] + shipment_ids))
                event["linking_notes"].append(f"Linked shipments via lanes: {shipment_ids}")

    return event

