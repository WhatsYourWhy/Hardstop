"""Tests for network impact scoring."""

import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

from sentinel.alerts.impact_scorer import (
    calculate_network_impact_score,
    map_score_to_classification,
    parse_eta_date_safely,
    is_eta_within_48h,
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
    
    def test_eta_within_48h_scoring(self):
        """Test ETA within 48h scoring with various date scenarios."""
        session = Mock()
        
        # Create priority shipments with different ETA scenarios
        now = datetime.now(timezone.utc)
        
        # Shipment within 48h (tomorrow end-of-day)
        near_ship = Mock(spec=Shipment)
        near_ship.shipment_id = "SHP-NEAR"
        near_ship.priority_flag = 1
        near_ship.eta_date = (now.date() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Shipment beyond 48h (3 days out)
        far_ship = Mock(spec=Shipment)
        far_ship.shipment_id = "SHP-FAR"
        far_ship.priority_flag = 1
        far_ship.eta_date = (now.date() + timedelta(days=3)).strftime("%Y-%m-%d")
        
        # Shipment with bad date
        bad_ship = Mock(spec=Shipment)
        bad_ship.shipment_id = "SHP-BAD"
        bad_ship.priority_flag = 1
        bad_ship.eta_date = "invalid-date-format"
        
        # Shipment with None ETA
        no_eta_ship = Mock(spec=Shipment)
        no_eta_ship.shipment_id = "SHP-NO-ETA"
        no_eta_ship.priority_flag = 1
        no_eta_ship.eta_date = None
        
        def query_side_effect(model):
            if model == Shipment:
                mock_query = Mock()
                mock_query.filter.return_value.all.return_value = [
                    near_ship, far_ship, bad_ship, no_eta_ship
                ]
                return mock_query
            mock_query = Mock()
            mock_query.filter.return_value.all.return_value = []
            return mock_query
        
        session.query.side_effect = query_side_effect
        
        event = {
            "facilities": [],
            "lanes": [],
            "shipments": ["SHP-NEAR", "SHP-FAR", "SHP-BAD", "SHP-NO-ETA"],
            "event_type": "GENERAL",
        }
        
        score, breakdown = calculate_network_impact_score(event, session)
        
        # Should have +1 for priority shipments
        assert score >= 1
        assert any("Priority shipments" in b for b in breakdown)
        
        # Should have +1 for ETA within 48h (only near_ship should count)
        assert any("within 48h" in b for b in breakdown)
        # Verify it only counted the near-term shipment
        for b in breakdown:
            if "within 48h" in b:
                assert "1 shipments" in b  # Only near_ship should be within 48h
    
    def test_bad_date_handling(self):
        """Test that bad dates don't crash the pipeline."""
        session = Mock()
        
        # Create shipments with various bad date formats
        bad_dates = [
            "not-a-date",
            "2024-13-45",  # Invalid month/day
            "2024/01/01",  # Wrong separator
            "",  # Empty string
            "   ",  # Whitespace only
            12345,  # Non-string type
            None,  # None value
        ]
        
        shipments = []
        for i, bad_date in enumerate(bad_dates):
            ship = Mock(spec=Shipment)
            ship.shipment_id = f"SHP-BAD-{i}"
            ship.priority_flag = 1
            ship.eta_date = bad_date
            shipments.append(ship)
        
        def query_side_effect(model):
            if model == Shipment:
                mock_query = Mock()
                mock_query.filter.return_value.all.return_value = shipments
                return mock_query
            mock_query = Mock()
            mock_query.filter.return_value.all.return_value = []
            return mock_query
        
        session.query.side_effect = query_side_effect
        
        event = {
            "facilities": [],
            "lanes": [],
            "shipments": [s.shipment_id for s in shipments],
            "event_type": "GENERAL",
        }
        
        # Should not crash, should just skip bad dates
        score, breakdown = calculate_network_impact_score(event, session)
        
        # Should still score for priority shipments
        assert score >= 1
        assert any("Priority shipments" in b for b in breakdown)
        
        # Should not have 48h score since all dates are bad
        assert not any("within 48h" in b for b in breakdown)


class TestEtaParsing:
    """Test ETA date parsing functions."""
    
    def test_parse_date_only_string(self):
        """Test parsing date-only strings (YYYY-MM-DD)."""
        result = parse_eta_date_safely("2024-01-15")
        assert result is not None
        assert result.date() == date(2024, 1, 15)
        # Should be end-of-day UTC (23:59:59)
        assert result.hour == 23
        assert result.minute == 59
        assert result.second == 59
        assert result.microsecond == 0  # time(23, 59, 59) has no microseconds
        assert result.tzinfo == timezone.utc
    
    def test_parse_datetime_string(self):
        """Test parsing datetime strings."""
        result = parse_eta_date_safely("2024-01-15 14:30:00")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 30
        assert result.tzinfo == timezone.utc  # Should default to UTC
    
    def test_parse_invalid_dates(self):
        """Test that invalid dates return None without crashing."""
        bad_dates = [
            "not-a-date",
            "2024-13-45",
            "2024/01/01",
            "",
            "   ",
            None,
        ]
        
        for bad_date in bad_dates:
            result = parse_eta_date_safely(bad_date)
            assert result is None, f"Expected None for {bad_date}, got {result}"
    
    def test_parse_non_string_types(self):
        """Test that non-string types are handled gracefully."""
        assert parse_eta_date_safely(12345) is None
        assert parse_eta_date_safely([]) is None
        assert parse_eta_date_safely({}) is None
    
    def test_is_eta_within_48h_date_only(self):
        """Test 48h check with date-only strings."""
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        # Tomorrow (within 48h when treated as end-of-day)
        assert is_eta_within_48h("2024-01-16", now) is True
        
        # Today (within 48h)
        assert is_eta_within_48h("2024-01-15", now) is True
        
        # 3 days out (beyond 48h)
        assert is_eta_within_48h("2024-01-18", now) is False
    
    def test_is_eta_within_48h_datetime(self):
        """Test 48h check with datetime strings."""
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        # 24 hours from now
        eta_24h = (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        assert is_eta_within_48h(eta_24h, now) is True
        
        # 49 hours from now (beyond 48h)
        eta_49h = (now + timedelta(hours=49)).strftime("%Y-%m-%d %H:%M:%S")
        assert is_eta_within_48h(eta_49h, now) is False
        
        # Past date within 7-day lookback (should return True)
        past_eta = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        assert is_eta_within_48h(past_eta, now) is True
        
        # Past date beyond lookback (should return False)
        old_eta = (now - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        assert is_eta_within_48h(old_eta, now) is False
    
    def test_is_eta_within_48h_bad_dates(self):
        """Test that bad dates return False without crashing."""
        now = datetime.now(timezone.utc)
        
        bad_dates = [
            "invalid-date",
            None,
            "",
            "2024-13-45",
        ]
        
        for bad_date in bad_dates:
            result = is_eta_within_48h(bad_date, now)
            assert result is False, f"Expected False for {bad_date}, got {result}"
    
    def test_timezone_consistency(self):
        """Test that timezone handling is consistent."""
        # Create a date-only string
        eta_str = "2024-01-16"
        
        # Parse it
        parsed = parse_eta_date_safely(eta_str)
        assert parsed is not None
        assert parsed.tzinfo == timezone.utc
        
        # Check with different "now" times in different timezones
        # Should still work correctly
        now_utc = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        now_est = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
        
        # Both should give same result (within 48h)
        result_utc = is_eta_within_48h(eta_str, now_utc)
        result_est = is_eta_within_48h(eta_str, now_est)
        
        # Both should be True (tomorrow is within 48h from today)
        assert result_utc == result_est

