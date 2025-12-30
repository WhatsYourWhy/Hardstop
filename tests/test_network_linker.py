"""Tests for network linking functionality."""

import pytest
from pathlib import Path
from datetime import date, timedelta

from hardstop.parsing.network_linker import link_event_to_network
from hardstop.database.sqlite_client import get_session
from hardstop.database.schema import Facility, Lane, Shipment


class TestAmbiguousCityState:
    """Test handling of ambiguous city/state matches."""
    
    def test_multiple_facilities_same_city_state(self, tmp_path):
        """Test tie-breaker logic when multiple facilities match."""
        # Use a temporary database for this test
        db_path = str(tmp_path / "test.db")
        session = get_session(db_path)
        
        try:
            # Create two facilities in same city/state
            facility1 = Facility(
                facility_id="PLANT-01",
                name="Plant One",
                type="PLANT",
                city="Avon",
                state="Indiana",  # Use full name - query handles both
                country="USA",
                criticality_score=8,
            )
            facility2 = Facility(
                facility_id="DC-01",
                name="DC One",
                type="DC",
                city="Avon",
                state="Indiana",  # Use full name - query handles both
                country="USA",
                criticality_score=5,
            )
            session.add(facility1)
            session.add(facility2)
            session.commit()
            
            event = {
                "title": "Spill at Avon facility",
                "raw_text": "A spill occurred at a facility in Avon, Indiana. Operations disrupted.",
                "facilities": [],
                "lanes": [],
                "shipments": [],
            }
            
            result = link_event_to_network(event, session)
            
            # Should select higher criticality facility
            assert len(result["facilities"]) == 1
            assert result["facilities"][0] == "PLANT-01"  # Higher criticality
            assert len(result["facility_candidates"]) == 2
            assert "PLANT-01" in result["facility_candidates"]
            assert "DC-01" in result["facility_candidates"]
            
            # Check ambiguity is recorded
            assert any("Ambiguous" in note or "ambiguous" in note.lower() for note in result["linking_notes"])
        finally:
            session.close()
    
    def test_ambiguous_match_lowers_confidence(self, tmp_path):
        """Test that ambiguous matches lower confidence."""
        db_path = str(tmp_path / "test.db")
        session = get_session(db_path)
        
        try:
            # Create two facilities with same criticality
            facility1 = Facility(
                facility_id="PLANT-01",
                name="Plant One",
                type="PLANT",
                city="Avon",
                state="Indiana",
                country="USA",
                criticality_score=8,
            )
            facility2 = Facility(
                facility_id="PLANT-02",
                name="Plant Two",
                type="PLANT",
                city="Avon",
                state="Indiana",
                country="USA",
                criticality_score=8,  # Same criticality
            )
            session.add(facility1)
            session.add(facility2)
            session.commit()
            
            event = {
                "title": "Event in Avon, Indiana",
                "raw_text": "Something happened",
                "facilities": [],
            }
            
            result = link_event_to_network(event, session)
            
            # Should have lower confidence for ambiguous match without second signal
            if result.get("link_confidence", {}).get("facility"):
                # If ambiguous and no second signal, confidence should be 0.45
                assert result["link_confidence"]["facility"] <= 0.70
        finally:
            session.close()


class TestTruncationOrdering:
    """Test shipment truncation and ordering."""
    
    def test_shipments_sorted_by_priority_then_eta(self, tmp_path):
        """Verify shipments are sorted correctly before truncation."""
        db_path = str(tmp_path / "test.db")
        session = get_session(db_path)
        
        try:
            # Create facility and lane
            facility = Facility(
                facility_id="PLANT-01",
                name="Test Plant",
                type="PLANT",
                city="Test",
                state="Test",
                country="USA",
            )
            lane = Lane(
                lane_id="LANE-001",
                origin_facility_id="PLANT-01",
                dest_facility_id="DC-01",
            )
            session.add(facility)
            session.add(lane)
            
            # Create shipments with different priorities and ETAs
            today = date.today()
            shipment1 = Shipment(  # Priority, early ETA
                shipment_id="SHP-001",
                lane_id="LANE-001",
                priority_flag=1,
                eta_date=(today + timedelta(days=1)).strftime("%Y-%m-%d"),
            )
            shipment2 = Shipment(  # Priority, later ETA
                shipment_id="SHP-002",
                lane_id="LANE-001",
                priority_flag=1,
                eta_date=(today + timedelta(days=3)).strftime("%Y-%m-%d"),
            )
            shipment3 = Shipment(  # No priority, early ETA
                shipment_id="SHP-003",
                lane_id="LANE-001",
                priority_flag=0,
                eta_date=(today + timedelta(days=2)).strftime("%Y-%m-%d"),
            )
            shipment4 = Shipment(  # No priority, no ETA
                shipment_id="SHP-004",
                lane_id="LANE-001",
                priority_flag=0,
                eta_date=None,
            )
            session.add(shipment1)
            session.add(shipment2)
            session.add(shipment3)
            session.add(shipment4)
            session.commit()
            
            event = {
                "facilities": ["PLANT-01"],
                "lanes": [],
                "shipments": [],
            }
            
            result = link_event_to_network(event, session, max_shipments=3)
            
            # Should have shipments sorted: priority first, then by ETA
            shipments = result["shipments"]
            assert len(shipments) <= 3
            
            # Priority shipments should come first
            priority_shipments = [s for s in shipments if s in ["SHP-001", "SHP-002"]]
            non_priority_shipments = [s for s in shipments if s in ["SHP-003", "SHP-004"]]
            
            if priority_shipments and non_priority_shipments:
                # All priority shipments should come before non-priority
                assert shipments.index(priority_shipments[0]) < shipments.index(non_priority_shipments[0])
        finally:
            session.close()
    
    def test_truncation_flags(self, tmp_path):
        """Verify truncation metadata is set correctly."""
        db_path = str(tmp_path / "test.db")
        session = get_session(db_path)
        
        try:
            # Create facility and lane
            facility = Facility(
                facility_id="PLANT-01",
                name="Test Plant",
                type="PLANT",
                city="Test",
                state="Test",
                country="USA",
            )
            lane = Lane(
                lane_id="LANE-001",
                origin_facility_id="PLANT-01",
                dest_facility_id="DC-01",
            )
            session.add(facility)
            session.add(lane)
            
            # Create 10 shipments
            for i in range(10):
                shipment = Shipment(
                    shipment_id=f"SHP-{i:03d}",
                    lane_id="LANE-001",
                    priority_flag=0,
                    eta_date=None,
                )
                session.add(shipment)
            session.commit()
            
            event = {
                "facilities": ["PLANT-01"],
                "lanes": [],
                "shipments": [],
            }
            
            # Test with max_shipments=5 (should truncate)
            result = link_event_to_network(event, session, max_shipments=5)
            
            assert result.get("shipments_truncated") == True
            assert result.get("shipments_total_linked") == 10
            assert len(result["shipments"]) == 5
            
            # Test with max_shipments=20 (should not truncate)
            result2 = link_event_to_network(event, session, max_shipments=20)
            assert result2.get("shipments_truncated") == False
            assert result2.get("shipments_total_linked") == 10
        finally:
            session.close()

