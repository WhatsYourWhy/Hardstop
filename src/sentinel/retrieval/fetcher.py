"""Source fetcher with rate limiting and error handling."""

import random
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from sentinel.config.loader import get_all_sources, load_sources_config
from sentinel.retrieval.adapters import RawItemCandidate, create_adapter
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


class SourceFetcher:
    """Fetches items from configured sources with rate limiting."""
    
    def __init__(self, sources_config: Optional[Dict] = None):
        """
        Initialize fetcher.
        
        Args:
            sources_config: Optional sources config dict. If None, loads from default path.
        """
        if sources_config is None:
            sources_config = load_sources_config()
        
        self.config = sources_config
        self.defaults = sources_config.get("defaults", {})
        self.rate_limit_config = self.defaults.get("rate_limit", {})
        self.per_host_min_seconds = self.rate_limit_config.get("per_host_min_seconds", 2)
        self.jitter_seconds = self.rate_limit_config.get("jitter_seconds", 1)
        
        # Track last fetch time per host
        self._last_fetch_time: Dict[str, float] = {}
    
    def _get_host_from_url(self, url: str) -> str:
        """Extract host from URL for rate limiting."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]
    
    def _wait_for_rate_limit(self, url: str) -> None:
        """Wait if necessary to respect rate limit for this host."""
        host = self._get_host_from_url(url)
        last_time = self._last_fetch_time.get(host, 0)
        now = time.time()
        elapsed = now - last_time
        min_interval = self.per_host_min_seconds
        
        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            # Add jitter
            jitter = random.uniform(0, self.jitter_seconds)
            total_wait = wait_time + jitter
            logger.debug(f"Rate limiting: waiting {total_wait:.2f}s for host {host}")
            time.sleep(total_wait)
        
        self._last_fetch_time[host] = time.time()
    
    def _parse_since(self, since_str: str) -> Optional[int]:
        """
        Parse --since argument (24h, 72h, 7d) to hours.
        
        Args:
            since_str: Time string like "24h", "72h", "7d"
            
        Returns:
            Number of hours, or None if invalid
        """
        since_str = since_str.lower().strip()
        if since_str.endswith("h"):
            try:
                return int(since_str[:-1])
            except ValueError:
                return None
        elif since_str.endswith("d"):
            try:
                days = int(since_str[:-1])
                return days * 24
            except ValueError:
                return None
        return None
    
    def fetch_all(
        self,
        tier: Optional[str] = None,
        enabled_only: bool = True,
        max_items_per_source: Optional[int] = None,
        since: Optional[str] = None,
        fail_fast: bool = False,
    ) -> Dict[str, List[RawItemCandidate]]:
        """
        Fetch items from all configured sources.
        
        Args:
            tier: Filter by tier (global, regional, local). None = all tiers.
            enabled_only: Only fetch from enabled sources
            max_items_per_source: Override max items per source
            since: Time window (24h, 72h, 7d). None = no filtering.
            fail_fast: If True, stop on first error. If False, continue on errors.
            
        Returns:
            Dict mapping source_id to list of RawItemCandidate objects
        """
        all_sources = get_all_sources(self.config)
        
        # Filter sources
        filtered_sources = []
        for source in all_sources:
            if tier and source.get("tier") != tier:
                continue
            if enabled_only and not source.get("enabled", True):
                continue
            filtered_sources.append(source)
        
        logger.info(f"Fetching from {len(filtered_sources)} sources")
        
        # Parse since argument
        since_hours = None
        if since:
            since_hours = self._parse_since(since)
            if since_hours is None:
                logger.warning(f"Invalid --since value: {since}, ignoring")
            else:
                logger.info(f"Filtering items from last {since_hours} hours")
        
        results: Dict[str, List[RawItemCandidate]] = {}
        errors: Dict[str, str] = {}
        
        for source in filtered_sources:
            source_id = source["id"]
            source_url = source["url"]
            
            try:
                # Rate limiting
                self._wait_for_rate_limit(source_url)
                
                # Create adapter
                adapter = create_adapter(source, self.defaults)
                
                # Override max_items if specified
                if max_items_per_source:
                    adapter.max_items = max_items_per_source
                
                # Fetch items
                logger.info(f"Fetching from {source_id} ({source.get('tier', 'unknown')} tier)")
                candidates = adapter.fetch(since_hours=since_hours)
                
                results[source_id] = candidates
                logger.info(f"Fetched {len(candidates)} items from {source_id}")
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Failed to fetch from {source_id}: {error_msg}", exc_info=not fail_fast)
                errors[source_id] = error_msg
                
                if fail_fast:
                    raise RuntimeError(f"Failed to fetch from {source_id}: {error_msg}") from e
        
        if errors:
            logger.warning(f"Failed to fetch from {len(errors)} sources: {list(errors.keys())}")
        
        return results

