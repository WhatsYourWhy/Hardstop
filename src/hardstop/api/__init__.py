"""API layer: canonical query/transform surface for UI and export.

This module provides the stable read model API. Key rules:

1. No SQLAlchemy imports - only call repo functions
2. No sorting/filtering unless it's presentation shaping
3. Return Pydantic models or composition wrappers only
4. This is the canonical surface - all query/transform logic lives here
"""

