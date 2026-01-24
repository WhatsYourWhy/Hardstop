from datetime import datetime, timezone

from hardstop.database.schema import Facility, Lane, Shipment
from hardstop.parsing.entity_extractor import link_to_network


def test_link_to_network_uses_pinned_time(session):
    facility = Facility(
        facility_id="PLANT-01",
        name="Plant 01",
        type="PLANT",
        city="Avon",
        state="Indiana",
        country="USA",
    )
    lane = Lane(
        lane_id="LANE-1",
        origin_facility_id="PLANT-01",
        dest_facility_id="PLANT-02",
    )
    shipment_in_window = Shipment(
        shipment_id="SHIP-1",
        lane_id="LANE-1",
        ship_date="2025-01-05",
        status="PENDING",
    )
    shipment_outside_window = Shipment(
        shipment_id="SHIP-2",
        lane_id="LANE-1",
        ship_date="2025-02-10",
        status="DELIVERED",
    )
    session.add_all([facility, lane, shipment_in_window, shipment_outside_window])
    session.commit()

    event = {"facilities": ["PLANT-01"], "title": "Test event"}
    pinned_now = datetime(2025, 1, 1, tzinfo=timezone.utc)

    first = link_to_network(dict(event), session, now=pinned_now)
    second = link_to_network(dict(event), session, now=pinned_now)

    assert first == second
    assert first["shipments"] == ["SHIP-1"]
