"""Tests for alert quality validation (confidence thresholds)."""

import pytest
from hardstop.alerts.alert_builder import (
    _compute_max_allowed_classification,
    _detect_high_impact_keywords,
)
from hardstop.config.loader import load_alert_quality_config


def test_ambiguous_match_with_2_compensators_gets_class_1():
    """Ambiguous facility match with 2+ compensating factors → classification 1."""
    quality_config = load_alert_quality_config()
    
    event = {
        "facilities": ["PLANT-01"],
        "lanes": ["LANE-001"],
        "link_confidence": {"facility": 0.55, "lanes": 0.75},  # Above ambiguous threshold
        "link_provenance": {"facility": "CITY_STATE_AMBIGUOUS"},
    }
    
    breakdown = ["+2: Facility criticality_score >= 7 (PLANT-01=8)"]
    max_class, reasoning, high_impact_factors = _compute_max_allowed_classification(
        event=event,
        impact_score=5,
        breakdown=breakdown,
        trust_tier=3,  # High trust
        quality_config=quality_config,
    )
    
    assert max_class == 1, f"Expected class 1, got {max_class}. Reasoning: {reasoning}"
    assert any("capped at classification 1" in r for r in reasoning)
    assert high_impact_factors >= 1


def test_ambiguous_match_with_1_compensator_gets_class_0():
    """Ambiguous facility match with <2 compensating factors → classification 0."""
    quality_config = load_alert_quality_config()
    
    event = {
        "facilities": ["PLANT-01"],
        "link_confidence": {"facility": 0.55},
        "link_provenance": {"facility": "CITY_STATE_AMBIGUOUS"},
    }
    
    breakdown = []
    max_class, reasoning, high_impact_factors = _compute_max_allowed_classification(
        event=event,
        impact_score=2,
        breakdown=breakdown,
        trust_tier=2,  # Medium trust only
        quality_config=quality_config,
    )
    
    assert max_class == 0, f"Expected class 0, got {max_class}. Reasoning: {reasoning}"
    assert any("insufficient compensating factors" in r for r in reasoning)
    assert high_impact_factors == 0


def test_ambiguous_match_below_threshold_gets_class_0():
    """Ambiguous facility match below threshold → classification 0."""
    quality_config = load_alert_quality_config()
    
    event = {
        "facilities": ["PLANT-01"],
        "link_confidence": {"facility": 0.45},  # Below ambiguous threshold
        "link_provenance": {"facility": "CITY_STATE_AMBIGUOUS"},
    }
    
    breakdown = []
    max_class, reasoning, high_impact_factors = _compute_max_allowed_classification(
        event=event,
        impact_score=3,
        breakdown=breakdown,
        trust_tier=3,
        quality_config=quality_config,
    )
    
    assert max_class == 0, f"Expected class 0, got {max_class}. Reasoning: {reasoning}"
    assert any("without sufficient evidence" in r for r in reasoning)


def test_facility_first_policy_low_facility_high_lane():
    """Facility-first policy: low facility confidence caps even with high lane confidence."""
    quality_config = load_alert_quality_config()
    
    event = {
        "facilities": ["PLANT-01"],
        "lanes": ["LANE-001"],
        "link_confidence": {
            "facility": 0.45,  # Low
            "lanes": 0.90,  # High
        },
        "link_provenance": {"facility": "CITY_STATE"},
    }
    
    breakdown = []
    max_class, reasoning, high_impact_factors = _compute_max_allowed_classification(
        event=event,
        impact_score=3,
        breakdown=breakdown,
        trust_tier=2,
        quality_config=quality_config,
    )
    
    # Should be capped at 0 due to low facility confidence (facility-first policy)
    assert max_class == 0, f"Expected class 0 due to facility-first policy. Reasoning: {reasoning}"
    assert any("Low facility confidence" in r for r in reasoning)


def test_keyword_detection_avoids_false_positives():
    """Keyword detection avoids false positives like 'fire sale'."""
    has_impact, keywords = _detect_high_impact_keywords("Fire sale at warehouse")
    assert not has_impact, "Should not detect 'fire sale' as high-impact"
    
    has_impact, keywords = _detect_high_impact_keywords("Fire at warehouse facility")
    assert has_impact, "Should detect 'fire at facility' as high-impact"
    assert "FIRE" in keywords


def test_keyword_detection_requires_operational_context():
    """Keyword detection requires operational context or location signals."""
    # Without context - should not trigger
    has_impact, keywords = _detect_high_impact_keywords("Strike price increased")
    assert not has_impact, "Should not detect 'strike price' without operational context"
    
    # With facility context - should trigger
    has_impact, keywords = _detect_high_impact_keywords("Strike at PLANT-01 facility")
    assert has_impact, "Should detect 'strike at facility' with operational context"
    assert "STRIKE" in keywords
    
    # With location signal - should trigger
    has_impact, keywords = _detect_high_impact_keywords("Spill in Chicago, IL")
    assert has_impact, "Should detect 'spill' with location signal"


def test_no_facilities_caps_at_class_0():
    """Events with no network links are capped at classification 0."""
    quality_config = load_alert_quality_config()
    
    event = {
        "facilities": [],
        "link_confidence": {},
        "link_provenance": {},
    }
    
    breakdown = []
    max_class, reasoning, high_impact_factors = _compute_max_allowed_classification(
        event=event,
        impact_score=5,  # High score, but no network links
        breakdown=breakdown,
        trust_tier=3,
        quality_config=quality_config,
    )
    
    assert max_class == 0, f"Expected class 0, got {max_class}. Reasoning: {reasoning}"
    assert any("No network links" in r for r in reasoning)


def test_high_confidence_with_insufficient_factors():
    """High facility confidence but insufficient high-impact factors → classification 1."""
    quality_config = load_alert_quality_config()
    
    event = {
        "facilities": ["PLANT-01"],
        "link_confidence": {"facility": 0.75},  # Above class 2 threshold
        "link_provenance": {"facility": "FACILITY_ID_EXACT"},
    }
    
    breakdown = []  # No high-impact factors
    max_class, reasoning, high_impact_factors = _compute_max_allowed_classification(
        event=event,
        impact_score=4,  # Would map to class 2
        breakdown=breakdown,
        trust_tier=2,
        quality_config=quality_config,
    )
    
    assert max_class == 1, f"Expected class 1, got {max_class}. Reasoning: {reasoning}"
    assert any("insufficient high-impact factors" in r for r in reasoning)
    assert high_impact_factors == 0


def test_high_confidence_with_2_factors_gets_class_2():
    """High facility confidence with 2+ high-impact factors → classification 2."""
    quality_config = load_alert_quality_config()
    
    event = {
        "facilities": ["PLANT-01"],
        "link_confidence": {"facility": 0.75},
        "link_provenance": {"facility": "FACILITY_ID_EXACT"},
    }
    
    breakdown = [
        "+2: Facility criticality_score >= 7 (PLANT-01=8)",
        "+1: Lane volume_score >= 7 (LANE-001=8)",
    ]
    max_class, reasoning, high_impact_factors = _compute_max_allowed_classification(
        event=event,
        impact_score=5,
        breakdown=breakdown,
        trust_tier=2,
        quality_config=quality_config,
    )
    
    assert max_class == 2, f"Expected class 2, got {max_class}. Reasoning: {reasoning}"
    assert high_impact_factors >= 2


def test_missing_confidence_defaults_to_zero():
    """Missing link_confidence defaults to 0.0 (not 1.0) to prevent false positives."""
    quality_config = load_alert_quality_config()
    
    event = {
        "facilities": ["PLANT-01"],
        # Missing link_confidence entirely
        "link_provenance": {"facility": "CITY_STATE"},
    }
    
    breakdown = []
    max_class, reasoning, high_impact_factors = _compute_max_allowed_classification(
        event=event,
        impact_score=4,
        breakdown=breakdown,
        trust_tier=2,
        quality_config=quality_config,
    )
    
    # Should be capped at 0 due to missing confidence (treated as 0.0)
    assert max_class == 0, f"Expected class 0 for missing confidence, got {max_class}. Reasoning: {reasoning}"
    assert any("Low facility confidence" in r for r in reasoning)

