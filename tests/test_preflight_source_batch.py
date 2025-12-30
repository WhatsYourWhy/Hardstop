"""Unit tests for preflight_source_batch function."""

import pytest

from hardstop.runners.ingest_external import preflight_source_batch


def test_preflight_accepts_empty_batch():
    """Test that preflight accepts empty batches (quiet sources are normal)."""
    # Empty list should be accepted
    preflight_source_batch("test_source", [])
    
    # Empty tuple should be accepted
    preflight_source_batch("test_source", ())
    
    # Non-empty list should be accepted
    preflight_source_batch("test_source", [1, 2, 3])


def test_preflight_rejects_none_source_items():
    """Test that preflight rejects None source_items."""
    with pytest.raises(ValueError, match="cannot be None"):
        preflight_source_batch("test_source", None)


def test_preflight_rejects_empty_source_id():
    """Test that preflight rejects empty or whitespace-only source_id."""
    with pytest.raises(ValueError, match="Invalid source_id"):
        preflight_source_batch("", [])
    
    with pytest.raises(ValueError, match="Invalid source_id"):
        preflight_source_batch("   ", [])


def test_preflight_accepts_any_iterable():
    """Test that preflight accepts any iterable type (doesn't enforce list/tuple)."""
    # Accept list
    preflight_source_batch("test_source", [1, 2])
    
    # Accept tuple
    preflight_source_batch("test_source", (1, 2))
    
    # Note: We don't validate type to avoid breaking weird adapters
    # Only validate that it's not None

