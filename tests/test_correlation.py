"""Tests for alert correlation functionality."""

from hardstop.alerts.correlation import build_correlation_key


def test_build_correlation_key_stable():
    """Test that correlation keys are stable and deterministic."""
    event = {
        "event_type": "SAFETY_AND_OPERATIONS",
        "title": "Spill at plant",
        "raw_text": "spill happened",
        "facilities": ["PLANT-01"],
        "lanes": ["LANE-001"],
    }
    k1 = build_correlation_key(event)
    k2 = build_correlation_key(event)
    assert k1 == k2
    assert "PLANT-01" in k1
    assert "LANE-001" in k1


def test_correlation_key_risk_bucket():
    """Test that risk buckets are correctly identified."""
    # Test explicit event_type
    event1 = {"event_type": "SPILL", "facilities": ["PLANT-01"], "lanes": []}
    key1 = build_correlation_key(event1)
    assert key1.startswith("SPILL|")
    
    # Test keyword inference
    event2 = {"title": "Chemical spill", "raw_text": "spill occurred", "facilities": ["PLANT-01"], "lanes": []}
    key2 = build_correlation_key(event2)
    assert key2.startswith("SPILL|")
    
    # Test strike
    event3 = {"event_type": "STRIKE", "facilities": ["PLANT-01"], "lanes": []}
    key3 = build_correlation_key(event3)
    assert key3.startswith("STRIKE|")
    
    # Test closure
    event4 = {"title": "Facility shutdown", "facilities": ["PLANT-01"], "lanes": []}
    key4 = build_correlation_key(event4)
    assert key4.startswith("CLOSURE|")


def test_correlation_key_facility_lane():
    """Test that facilities and lanes are included in correlation key."""
    event = {
        "event_type": "GENERAL",
        "facilities": ["PLANT-01", "DC-02"],
        "lanes": ["LANE-001", "LANE-002"],
    }
    key = build_correlation_key(event)
    
    # Should include first facility (sorted)
    assert "PLANT-01" in key or "DC-02" in key
    
    # Should include first lane (sorted)
    assert "LANE-001" in key or "LANE-002" in key


def test_correlation_key_no_facilities_lanes():
    """Test correlation key when no facilities or lanes are present."""
    event = {
        "event_type": "GENERAL",
        "facilities": [],
        "lanes": [],
    }
    key = build_correlation_key(event)
    
    # Should still produce a valid key with NONE placeholders
    assert "|" in key
    parts = key.split("|")
    assert len(parts) == 3
    assert parts[1] == "NONE"  # No facilities
    assert parts[2] == "NONE"  # No lanes


def test_correlation_key_deduplicates_facilities():
    """Test that duplicate facilities are handled correctly."""
    event = {
        "event_type": "GENERAL",
        "facilities": ["PLANT-01", "PLANT-01", "DC-02"],
        "lanes": [],
    }
    key1 = build_correlation_key(event)
    
    # Same facilities in different order should produce same key
    event2 = {
        "event_type": "GENERAL",
        "facilities": ["DC-02", "PLANT-01"],
        "lanes": [],
    }
    key2 = build_correlation_key(event2)
    
    # Should use first facility after sorting (alphabetically)
    # So both should use the same first facility
    assert key1 == key2

