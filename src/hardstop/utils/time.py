"""Time utilities for UTC timestamp formatting."""

from datetime import datetime, timezone


def utc_now_z() -> str:
    """
    Get current UTC time as ISO 8601 string with Z suffix.
    
    Returns:
        ISO 8601 UTC timestamp ending with 'Z' (e.g., '2025-12-23T00:27:07.804867Z')
        
    Example:
        >>> utc_now_z()
        '2025-12-23T00:27:07.804867Z'
    """
    return to_utc_z(datetime.now(timezone.utc))


def to_utc_z(dt: datetime) -> str:
    """
    Convert datetime to ISO 8601 UTC string with Z suffix.
    
    Args:
        dt: Datetime object (must be timezone-aware)
        
    Returns:
        ISO 8601 UTC timestamp ending with 'Z' (e.g., '2025-12-23T00:27:07.804867Z')
        
    Raises:
        ValueError: If datetime is naive (not timezone-aware)
        
    Example:
        >>> from datetime import datetime, timezone
        >>> dt = datetime.now(timezone.utc)
        >>> to_utc_z(dt)
        '2025-12-23T00:27:07.804867Z'
    """
    if dt.tzinfo is None:
        raise ValueError(
            f"Naive datetime not allowed. Got {dt}. "
            "Use datetime.now(timezone.utc) or dt.replace(tzinfo=timezone.utc)"
        )
    
    # Convert to UTC if not already
    dt_utc = dt.astimezone(timezone.utc)
    
    # Format as ISO 8601 and replace +00:00 with Z
    return dt_utc.isoformat().replace('+00:00', 'Z')

