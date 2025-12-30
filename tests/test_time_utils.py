"""Tests for time utilities."""

import pytest
from datetime import datetime, timezone, timedelta

from hardstop.utils.time import to_utc_z, utc_now_z


def test_utc_now_z_always_ends_with_z():
    """Test that utc_now_z() always ends with Z."""
    result = utc_now_z()
    assert result.endswith('Z'), f"Expected result to end with 'Z', got: {result}"


def test_utc_now_z_never_contains_plus_00_00_z():
    """Test that utc_now_z() never returns invalid +00:00Z format."""
    result = utc_now_z()
    assert '+00:00Z' not in result, f"Result should not contain '+00:00Z', got: {result}"


def test_to_utc_z_always_ends_with_z():
    """Test that to_utc_z() always ends with Z for timezone-aware datetime."""
    dt = datetime.now(timezone.utc)
    result = to_utc_z(dt)
    assert result.endswith('Z'), f"Expected result to end with 'Z', got: {result}"


def test_to_utc_z_never_contains_plus_00_00_z():
    """Test that to_utc_z() never returns invalid +00:00Z format."""
    dt = datetime.now(timezone.utc)
    result = to_utc_z(dt)
    assert '+00:00Z' not in result, f"Result should not contain '+00:00Z', got: {result}"


def test_to_utc_z_raises_on_naive_datetime():
    """Test that to_utc_z() raises ValueError for naive datetime."""
    naive_dt = datetime.now()
    with pytest.raises(ValueError, match="Naive datetime not allowed"):
        to_utc_z(naive_dt)


def test_to_utc_z_converts_non_utc_timezone():
    """Test that to_utc_z() converts non-UTC timezone to UTC."""
    # Create a datetime in a different timezone (e.g., EST = UTC-5)
    est = timezone(timedelta(hours=-5))
    dt_est = datetime(2025, 12, 23, 12, 0, 0, tzinfo=est)
    
    result = to_utc_z(dt_est)
    
    # Should end with Z
    assert result.endswith('Z')
    # Should represent UTC time (17:00:00 in this case)
    assert '2025-12-23T17:00:00' in result or '2025-12-23T17:00:00.000000Z' in result


def test_to_utc_z_preserves_microseconds():
    """Test that to_utc_z() preserves microseconds."""
    dt = datetime(2025, 12, 23, 12, 34, 56, 123456, tzinfo=timezone.utc)
    result = to_utc_z(dt)
    
    assert '123456' in result or '.123456' in result
    assert result.endswith('Z')

