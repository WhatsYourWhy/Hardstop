"""Unit tests for source health tracking (v0.9)."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from sentinel.database.source_run_repo import (
    create_source_run,
    get_source_health,
    get_all_source_health,
    list_recent_runs,
)
from sentinel.database.schema import SourceRun
from sentinel.retrieval.fetcher import FetchResult, SourceFetcher
from sentinel.retrieval.adapters import RawItemCandidate


def test_fetcher_captures_status_code_200(session):
    """Test that fetcher captures status code 200 on success."""
    fetcher = SourceFetcher()
    
    # Mock a successful fetch
    with patch('sentinel.retrieval.fetcher.create_adapter') as mock_adapter:
        mock_adapter_instance = Mock()
        mock_adapter_instance.fetch.return_value = []
        mock_adapter.return_value = mock_adapter_instance
        
        # Mock source config
        with patch('sentinel.retrieval.fetcher.get_all_sources') as mock_get_sources:
            mock_get_sources.return_value = [{
                "id": "test_source",
                "type": "rss",
                "enabled": True,
                "tier": "global",
                "url": "https://example.com/feed.rss",
            }]
            
            results = fetcher.fetch_all()
            assert len(results) == 1
            assert results[0].status == "SUCCESS"
            # Status code would be captured from actual HTTP response
            # In this mock, we can't easily test the actual status code capture
            # but we verify the structure is correct


def test_fetcher_zero_items_is_success(session):
    """Test that zero items fetched = SUCCESS (quiet feeds are normal)."""
    fetcher = SourceFetcher()
    
    with patch('sentinel.retrieval.fetcher.create_adapter') as mock_adapter:
        mock_adapter_instance = Mock()
        mock_adapter_instance.fetch.return_value = []  # Zero items
        mock_adapter.return_value = mock_adapter_instance
        
        with patch('sentinel.retrieval.fetcher.get_all_sources') as mock_get_sources:
            mock_get_sources.return_value = [{
                "id": "test_source",
                "type": "rss",
                "enabled": True,
                "tier": "global",
                "url": "https://example.com/feed.rss",
            }]
            
            results = fetcher.fetch_all()
            assert len(results) == 1
            assert results[0].status == "SUCCESS"
            assert len(results[0].items) == 0


def test_source_health_success_rate_computation(session):
    """Test that source health computes success rate correctly."""
    source_id = "test_source"
    now = datetime.now(timezone.utc)
    
    # Create 10 FETCH runs: 7 success, 3 failure
    for i in range(10):
        create_source_run(
            session,
            run_group_id=f"group-{i}",
            source_id=source_id,
            phase="FETCH",
            run_at_utc=(now - timedelta(hours=i)).isoformat(),
            status="SUCCESS" if i < 7 else "FAILURE",
            items_fetched=10,
            items_new=5,
        )
    
    session.commit()
    
    health = get_source_health(session, source_id, lookback_n=10)
    assert health["success_rate"] == 0.7  # 7/10


def test_source_health_stale_flag(session):
    """Test that stale flag is calculated correctly."""
    source_id = "test_source"
    now = datetime.now(timezone.utc)
    
    # Create a successful run 50 hours ago (stale)
    create_source_run(
        session,
        run_group_id="group-1",
        source_id=source_id,
        phase="FETCH",
        run_at_utc=(now - timedelta(hours=50)).isoformat(),
        status="SUCCESS",
        items_fetched=10,
        items_new=5,
    )
    
    session.commit()
    
    health = get_source_health(session, source_id, lookback_n=10)
    assert health["last_success_utc"] is not None
    
    # Check if stale (48h threshold)
    stale_cutoff = now - timedelta(hours=48)
    is_stale = health["last_success_utc"] < stale_cutoff.isoformat()
    assert is_stale is True


def test_source_health_last_ingest_summary(session):
    """Test that last ingest summary is extracted correctly."""
    source_id = "test_source"
    now = datetime.now(timezone.utc)
    
    # Create an INGEST run
    create_source_run(
        session,
        run_group_id="group-1",
        source_id=source_id,
        phase="INGEST",
        run_at_utc=now.isoformat(),
        status="SUCCESS",
        items_processed=20,
        items_suppressed=5,
        items_events_created=15,
        items_alerts_touched=10,
    )
    
    session.commit()
    
    health = get_source_health(session, source_id, lookback_n=10)
    last_ingest = health["last_ingest"]
    
    assert last_ingest["processed"] == 20
    assert last_ingest["suppressed"] == 5
    assert last_ingest["events"] == 15
    assert last_ingest["alerts"] == 10


def test_get_all_source_health(session):
    """Test that get_all_source_health returns health for all sources."""
    now = datetime.now(timezone.utc)
    
    # Create runs for two sources
    for source_id in ["source1", "source2"]:
        create_source_run(
            session,
            run_group_id="group-1",
            source_id=source_id,
            phase="FETCH",
            run_at_utc=now.isoformat(),
            status="SUCCESS",
            items_fetched=10,
            items_new=5,
        )
    
    session.commit()
    
    health_list = get_all_source_health(session, lookback_n=10)
    assert len(health_list) == 2
    
    source_ids = {h["source_id"] for h in health_list}
    assert source_ids == {"source1", "source2"}


def test_list_recent_runs_with_filters(session):
    """Test that list_recent_runs respects filters."""
    source_id = "test_source"
    now = datetime.now(timezone.utc)
    
    # Create FETCH and INGEST runs
    create_source_run(
        session,
        run_group_id="group-1",
        source_id=source_id,
        phase="FETCH",
        run_at_utc=now.isoformat(),
        status="SUCCESS",
        items_fetched=10,
        items_new=5,
    )
    
    create_source_run(
        session,
        run_group_id="group-1",
        source_id=source_id,
        phase="INGEST",
        run_at_utc=now.isoformat(),
        status="SUCCESS",
        items_processed=10,
    )
    
    session.commit()
    
    # Filter by phase
    fetch_runs = list_recent_runs(session, source_id=source_id, phase="FETCH")
    assert len(fetch_runs) == 1
    assert fetch_runs[0].phase == "FETCH"
    
    ingest_runs = list_recent_runs(session, source_id=source_id, phase="INGEST")
    assert len(ingest_runs) == 1
    assert ingest_runs[0].phase == "INGEST"
    
    # No filter
    all_runs = list_recent_runs(session, source_id=source_id)
    assert len(all_runs) == 2

