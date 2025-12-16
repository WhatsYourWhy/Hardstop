"""Tests for network impact scoring."""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock

from sentinel.alerts.impact_scorer import (
    calculate_network_impact_score,
    map_score_to_classification,
)
from sentinel.database.schema import Facility, Lane, Shipment


class TestMapScoreToClassification:
    """Test classification mapping from impact scores."""
    
    def test_score_0_maps_to_classification_0(self):
        assert map_score_to_classification(0) == 0
        assert map_score_to_classification(1) == 0
    
    def test_score_2_maps_to_classification_1(self):
        assert map_score_to_classification(2) == 1
        assert map_score_to_classification(3) == 1
    
    def test_score_4_plus_maps_to_classification_2(self):
        assert map_score_to_classification(4) == 2
        assert map_score_to_classification(5) == 2
        assert map_score_to_classification(10) == 2


class TestCalculateNetworkImpactScore:
    """Test network impact score calculation."""
    
    def test_uses_db_values_not_input_severity(self):
        """Verify scoring uses DB-driven values, not input severity_guess."""
        # Create mock session with high-impact facility
        session = Mock()
        facility = Mock(spec=Facility)
        facility.facility_id = "PLANT-01"
        facility.criticality_score = 8  # High criticality
        
        session.query.return_value.filter.return_value.all.return_value = [facility]
        session.query.return_value.filter.return_value.in_.return_value = None
        
        event = {
            "facilities": ["PLANT-01"],
            "lanes": [],
            "shipments": [],
            "event_type": "GENERAL",
            "severity_guess": 0,  # Low input severity
        }
        
        score, breakdown = calculate_network_impact_score(event, session)
        
        # Should score based on facility criticality, not input severity
        assert score >= 2  # At least +2 for high criticality facility
        assert any("criticality_score" in b for b in breakdown)
    
    def test_facility_criticality_scoring(self):
        """Test facility criticality scoring with 1-10 scale."""
        session = Mock()
        
        # High criticality facility (>=7)
        high_facility = Mock(spec=Facility)
        high_facility.facility_id = "PLANT-01"
        high_facility.criticality_score = 8
        
        # Low criticality facility (<7)
        low_facility = Mock(spec=Facility)
        low_facility.facility_id = "DC-01"
        low_facility.criticality_score = 5
        
        def query_side_effect(model):
            if model == Facility:
                mock_query = Mock()
                mock_query.filter.return_value.all.return_value = [high_facility]
                return mock_query
            return Mock()
        
        session.query.side_effect = query_side_effect
        
        event = {
            "facilities": ["PLANT-01"],
            "lanes": [],
            "shipments": [],
            "event_type": "GENERAL",
        }
        
        score, breakdown = calculate_network_impact_score(event, session)
        
        # High criticality should add +2
        assert score >= 2
        assert any(">= 7" in b and "PLANT-01" in b for b in breakdown)
        
        # Test with low criticality
        def query_side_effect_low(model):
            if model == Facility:
                mock_query = Mock()
                mock_query.filter.return_value.all.return_value = [low_facility]
                return mock_query
            return Mock(filter=lambda **kw: Mock(all=lambda: []))
        
        session.query.side_effect = query_side_effect_low
        score2, _ = calculate_network_impact_score(event, session)
        assert score2 < score  # Lower score for low criticality
    
    def test_lane_volume_scoring(self):
        """Test lane volume scoring with 1-10 scale."""
        session = Mock()
        
        high_lane = Mock(spec=Lane)
        high_lane.lane_id = "LANE-001"
        high_lane.volume_score = 8
        
        def query_side_effect(model):
            if model == Lane:
                mock_query = Mock()
                mock_query.filter.return_value.all.return_value = [high_lane]
                return mock_query
            mock_query = Mock()
            mock_query.filter.return_value.all.return_value = []
            return mock_query
        
        session.query.side_effect = query_side_effect
        
        event = {
            "facilities": [],
            "lanes": ["LANE-001"],
            "shipments": [],
            "event_type": "GENERAL",
        }
        
        score, breakdown = calculate_network_impact_score(event, session)
        
        # High volume should add +1
        assert score >= 1
        assert any("volume_score" in b and ">= 7" in b for b in breakdown)
    
    def test_shipment_priority_scoring(self):
        """Test enhanced shipment priority scoring."""
        session = Mock()
        
        # Create priority shipments
        priority_ship1 = Mock(spec=Shipment)
        priority_ship1.shipment_id = "SHP-001"
        priority_ship1.priority_flag = 1
        priority_ship1.eta_date = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        priority_ship2 = Mock(spec=Shipment)
        priority_ship2.shipment_id = "SHP-002"
        priority_ship2.priority_flag = 1
        priority_ship2.eta_date = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
        
        def query_side_effect(model):
            if model == Shipment:
                mock_query = Mock()
                mock_query.filter.return_value.all.return_value = [priority_ship1, priority_ship2]
                return mock_query
            mock_query = Mock()
            mock_query.filter.return_value.all.return_value = []
            return mock_query
        
        session.query.side_effect = query_side_effect
        
        event = {
            "facilities": [],
            "lanes": [],
            "shipments": ["SHP-001", "SHP-002"],
            "event_type": "GENERAL",
        }
        
        score, breakdown = calculate_network_impact_score(event, session)
        
        # Should have at least +1 for priority shipments
        assert score >= 1
        assert any("Priority shipments" in b for b in breakdown)
    
    def test_event_type_keyword_scoring(self):
        """Test event type and keyword detection."""
        session = Mock()
        session.query.return_value.filter.return_value.all.return_value = []
        
        # Test keyword in text
        event = {
            "facilities": [],
            "lanes": [],
            "shipments": [],
            "event_type": "GENERAL",
            "title": "Chemical spill at facility",
            "raw_text": "",
        }
        
        score, breakdown = calculate_network_impact_score(event, session)
        
        # Should detect "spill" keyword
        assert score >= 1
        assert any("keyword" in b.lower() or "spill" in b.lower() for b in breakdown)

