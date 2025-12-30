"""Suppression engine for evaluating rules against items."""

import re
from typing import Dict, List, Optional

from .models import SuppressionResult, SuppressionRule


def _extract_field_value(item: Dict, field: str) -> Optional[str]:
    """
    Extract field value from item dict.
    
    Args:
        item: Item dictionary with normalized fields
        field: Field name to extract
        
    Returns:
        Field value as string, or None if not found
    """
    if field == "any":
        # Check all text fields
        for text_field in ["title", "summary", "raw_text", "url"]:
            value = item.get(text_field)
            if value:
                return str(value)
        return None
    
    value = item.get(field)
    if value is None:
        return None
    return str(value)


def _match_keyword(text: Optional[str], pattern: str, case_sensitive: bool) -> bool:
    """Check if pattern is contained in text (keyword matching)."""
    if not text:
        return False
    if not case_sensitive:
        text = text.lower()
        pattern = pattern.lower()
    return pattern in text


def _match_exact(text: Optional[str], pattern: str, case_sensitive: bool) -> bool:
    """Check if text exactly matches pattern."""
    if not text:
        return False
    if not case_sensitive:
        text = text.lower()
        pattern = pattern.lower()
    return text == pattern


def _match_regex(text: Optional[str], pattern: str, case_sensitive: bool) -> bool:
    """Check if text matches regex pattern."""
    if not text:
        return False
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        return bool(re.search(pattern, text, flags))
    except re.error:
        # Invalid regex - don't match
        return False


def _evaluate_rule(rule: SuppressionRule, item: Dict, source_id: str, tier: Optional[str]) -> bool:
    """
    Evaluate a single suppression rule against an item.
    
    Args:
        rule: Suppression rule to evaluate
        item: Item dictionary with normalized fields
        source_id: Source ID (for field=source_id matching)
        tier: Tier (for field=tier matching)
        
    Returns:
        True if rule matches, False otherwise
    """
    if not rule.enabled:
        return False
    
    # Add source_id and tier to item for matching
    item_with_meta = item.copy()
    item_with_meta["source_id"] = source_id
    if tier:
        item_with_meta["tier"] = tier
    
    # Extract field value
    field_value = _extract_field_value(item_with_meta, rule.field)
    
    # Match based on kind
    if rule.kind == "keyword":
        return _match_keyword(field_value, rule.pattern, rule.case_sensitive)
    elif rule.kind == "exact":
        return _match_exact(field_value, rule.pattern, rule.case_sensitive)
    elif rule.kind == "regex":
        return _match_regex(field_value, rule.pattern, rule.case_sensitive)
    else:
        # Unknown kind - don't match
        return False


def evaluate_suppression(
    *,
    source_id: str,
    tier: Optional[str],
    item: Dict,
    global_rules: List[SuppressionRule],
    source_rules: List[SuppressionRule],
) -> SuppressionResult:
    """
    Evaluate suppression rules against an item.
    
    Rules are evaluated in order: global rules first, then source rules.
    First matching rule becomes the primary_rule_id.
    All matching rules are collected for auditability.
    
    Args:
        source_id: Source ID of the item
        tier: Tier of the item (global, regional, local, or None)
        item: Normalized item dictionary with fields: title, summary, raw_text, url, event_type
        global_rules: List of global suppression rules
        source_rules: List of source-specific suppression rules
        
    Returns:
        SuppressionResult with is_suppressed, primary_rule_id, matched_rule_ids, notes
    """
    matched_rules: List[SuppressionRule] = []
    
    # Evaluate global rules first (in order)
    for rule in global_rules:
        if _evaluate_rule(rule, item, source_id, tier):
            matched_rules.append(rule)
    
    # Then evaluate source rules (in order)
    for rule in source_rules:
        if _evaluate_rule(rule, item, source_id, tier):
            matched_rules.append(rule)
    
    # Build result
    if not matched_rules:
        return SuppressionResult(
            is_suppressed=False,
            primary_rule_id=None,
            matched_rule_ids=[],
            notes=[],
            primary_reason_code=None,
            reason_codes=[],
        )
    
    # Primary rule is first match (deterministic ordering)
    primary_rule = matched_rules[0]
    matched_rule_ids = [rule.id for rule in matched_rules]
    notes = [rule.note for rule in matched_rules if rule.note]
    reason_codes = [rule.get_reason_code() for rule in matched_rules]
    primary_reason_code = reason_codes[0] if reason_codes else None
    
    return SuppressionResult(
        is_suppressed=True,
        primary_rule_id=primary_rule.id,
        matched_rule_ids=matched_rule_ids,
        notes=notes,
        primary_reason_code=primary_reason_code,
        reason_codes=reason_codes,
    )

