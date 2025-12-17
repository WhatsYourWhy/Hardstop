"""Pytest configuration and fixtures."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from sentinel.database.migrate import (
    ensure_alert_correlation_columns,
    ensure_event_external_fields,
    ensure_raw_items_table,
    ensure_suppression_columns,
    ensure_trust_tier_columns,
)
from sentinel.database.schema import Base


@pytest.fixture
def session():
    """Create a temporary in-memory database session for testing."""
    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    
    # Run migrations
    # Note: We can't use the migration functions directly with in-memory DB,
    # but since we're creating all tables from schema, columns should exist.
    # For tests that need migrations, we can add columns manually if needed.
    
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        yield session
    finally:
        session.close()

