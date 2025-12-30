"""Unit tests for suppression engine."""

import pytest

from hardstop.suppression.engine import evaluate_suppression
from hardstop.suppression.models import SuppressionRule


def test_keyword_match_any_field():
    """Test keyword matching in any field."""
    rule = SuppressionRule(
        id="test_keyword",
        kind="keyword",
        field="any",
        pattern="test alert",
        case_sensitive=False,
    )
    
    item = {
        "title": "This is a test alert",
        "summary": "Some summary",
        "raw_text": "Content here",
    }
    
    result = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item,
        global_rules=[rule],
        source_rules=[],
    )
    
    assert result.is_suppressed is True
    assert result.primary_rule_id == "test_keyword"
    assert "test_keyword" in result.matched_rule_ids
    assert result.primary_reason_code == "test_keyword"
    assert result.reason_codes == ["test_keyword"]


def test_keyword_match_specific_field():
    """Test keyword matching in specific field."""
    rule = SuppressionRule(
        id="test_title",
        kind="keyword",
        field="title",
        pattern="recall",
        case_sensitive=False,
    )
    
    item = {
        "title": "Product Recall Notice",
        "summary": "Some summary",
    }
    
    result = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item,
        global_rules=[rule],
        source_rules=[],
    )
    
    assert result.is_suppressed is True
    assert result.primary_rule_id == "test_title"


def test_keyword_no_match():
    """Test keyword matching when pattern doesn't match."""
    rule = SuppressionRule(
        id="test_keyword",
        kind="keyword",
        field="any",
        pattern="test alert",
        case_sensitive=False,
    )
    
    item = {
        "title": "Real alert",
        "summary": "Important notice",
    }
    
    result = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item,
        global_rules=[rule],
        source_rules=[],
    )
    
    assert result.is_suppressed is False
    assert result.primary_rule_id is None
    assert result.primary_reason_code is None


def test_regex_match():
    """Test regex matching."""
    rule = SuppressionRule(
        id="test_regex",
        kind="regex",
        field="title",
        pattern=r"test\s+alert",
        case_sensitive=False,
    )
    
    item = {
        "title": "This is a test alert",
    }
    
    result = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item,
        global_rules=[rule],
        source_rules=[],
    )
    
    assert result.is_suppressed is True
    assert result.primary_rule_id == "test_regex"


def test_exact_match():
    """Test exact matching."""
    rule = SuppressionRule(
        id="test_exact",
        kind="exact",
        field="title",
        pattern="Test Alert",
        case_sensitive=False,
    )
    
    item = {
        "title": "test alert",  # Case insensitive
    }
    
    result = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item,
        global_rules=[rule],
        source_rules=[],
    )
    
    assert result.is_suppressed is True
    assert result.primary_rule_id == "test_exact"
    assert result.primary_reason_code == "test_exact"


def test_case_sensitive_match():
    """Test case-sensitive matching."""
    rule = SuppressionRule(
        id="test_case",
        kind="keyword",
        field="title",
        pattern="Test",
        case_sensitive=True,
    )
    
    # Should match
    item1 = {"title": "Test Alert"}
    result1 = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item1,
        global_rules=[rule],
        source_rules=[],
    )
    assert result1.is_suppressed is True
    
    # Should not match (different case)
    item2 = {"title": "test alert"}
    result2 = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item2,
        global_rules=[rule],
        source_rules=[],
    )
    assert result2.is_suppressed is False


def test_global_precedence_over_source():
    """Test that global rules are evaluated before source rules."""
    global_rule = SuppressionRule(
        id="global_rule",
        kind="keyword",
        field="any",
        pattern="test",
        case_sensitive=False,
    )
    
    source_rule = SuppressionRule(
        id="source_rule",
        kind="keyword",
        field="any",
        pattern="test",
        case_sensitive=False,
    )
    
    item = {"title": "test alert"}
    
    result = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item,
        global_rules=[global_rule],
        source_rules=[source_rule],
    )
    
    # Primary rule should be global (first match)
    assert result.is_suppressed is True
    assert result.primary_rule_id == "global_rule"
    # Both rules should be in matched list
    assert "global_rule" in result.matched_rule_ids
    assert "source_rule" in result.matched_rule_ids


def test_reason_code_override():
    """Reason codes fall back to explicit overrides."""
    rule = SuppressionRule(
        id="rule_with_reason",
        kind="keyword",
        field="title",
        pattern="snooze",
        reason_code="noise",
        case_sensitive=False,
    )
    item = {"title": "Snooze button"}
    result = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item,
        global_rules=[rule],
        source_rules=[],
    )
    assert result.is_suppressed is True
    assert result.primary_rule_id == "rule_with_reason"
    assert result.primary_reason_code == "noise"
    assert result.reason_codes == ["noise"]


def test_multiple_matches_collected():
    """Test that multiple matching rules are collected."""
    rule1 = SuppressionRule(
        id="rule1",
        kind="keyword",
        field="title",
        pattern="test",
        case_sensitive=False,
    )
    
    rule2 = SuppressionRule(
        id="rule2",
        kind="keyword",
        field="summary",
        pattern="alert",
        case_sensitive=False,
    )
    
    item = {
        "title": "test",
        "summary": "alert",
    }
    
    result = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item,
        global_rules=[rule1, rule2],
        source_rules=[],
    )
    
    assert result.is_suppressed is True
    assert result.primary_rule_id == "rule1"  # First match
    assert len(result.matched_rule_ids) == 2
    assert "rule1" in result.matched_rule_ids
    assert "rule2" in result.matched_rule_ids


def test_disabled_rule_not_matched():
    """Test that disabled rules don't match."""
    rule = SuppressionRule(
        id="disabled_rule",
        enabled=False,
        kind="keyword",
        field="any",
        pattern="test",
        case_sensitive=False,
    )
    
    item = {"title": "test alert"}
    
    result = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item,
        global_rules=[rule],
        source_rules=[],
    )
    
    assert result.is_suppressed is False


def test_field_any_checks_all_text_fields():
    """Test that field=any checks all text fields."""
    rule = SuppressionRule(
        id="any_field",
        kind="keyword",
        field="any",
        pattern="match",
        case_sensitive=False,
    )
    
    # Test title
    item1 = {"title": "match here"}
    result1 = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item1,
        global_rules=[rule],
        source_rules=[],
    )
    assert result1.is_suppressed is True
    
    # Test summary
    item2 = {"summary": "match here"}
    result2 = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item2,
        global_rules=[rule],
        source_rules=[],
    )
    assert result2.is_suppressed is True
    
    # Test raw_text
    item3 = {"raw_text": "match here"}
    result3 = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item3,
        global_rules=[rule],
        source_rules=[],
    )
    assert result3.is_suppressed is True
    
    # Test url
    item4 = {"url": "http://example.com/match"}
    result4 = evaluate_suppression(
        source_id="test_source",
        tier="global",
        item=item4,
        global_rules=[rule],
        source_rules=[],
    )
    assert result4.is_suppressed is True

