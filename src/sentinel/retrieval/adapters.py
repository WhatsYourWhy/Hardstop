"""Source adapters for fetching from external sources."""

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

import feedparser
import requests
from pydantic import BaseModel


class RawItemCandidate(BaseModel):
    """Candidate raw item from a source adapter."""
    
    canonical_id: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    published_at_utc: Optional[str] = None  # ISO 8601 string
    payload: Dict  # Full original record


class AdapterFetchResponse(BaseModel):
    """Combined adapter payload with diagnostics for fetcher consumption."""

    items: List[RawItemCandidate]
    status_code: Optional[int] = None
    bytes_downloaded: int = 0


class SourceAdapter(ABC):
    """Abstract base class for source adapters."""
    
    def __init__(self, source_config: Dict, defaults: Dict):
        self.source_config = source_config
        self.defaults = defaults
        self.source_id = source_config["id"]
        self.url = source_config["url"]
        self.timeout = defaults.get("timeout_seconds", 20)
        self.user_agent = defaults.get("user_agent", "sentinel-agent/0.6")
        self.max_items = source_config.get("max_items_per_fetch") or defaults.get("max_items_per_fetch", 50)
    
    @abstractmethod
    def fetch(self, since_hours: Optional[int] = None) -> AdapterFetchResponse:
        """
        Fetch items from the source.
        
        Args:
            since_hours: Only fetch items published within this many hours (optional)
            
        Returns:
            AdapterFetchResponse containing items plus diagnostics
        """
        pass
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for requests."""
        return {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
        }


class RSSAdapter(SourceAdapter):
    """Adapter for RSS/Atom feeds."""
    
    def fetch(self, since_hours: Optional[int] = None) -> AdapterFetchResponse:
        """Fetch items from RSS/Atom feed."""
        try:
            response = requests.get(
                self.url,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            candidates = []
            
            cutoff_time = None
            if since_hours:
                cutoff_time = datetime.now(timezone.utc).timestamp() - (since_hours * 3600)
            
            for entry in feed.entries[:self.max_items]:
                # Parse published date
                published_at_utc = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        published_at_utc = pub_dt.isoformat()
                        
                        # Filter by time if requested
                        if cutoff_time and pub_dt.timestamp() < cutoff_time:
                            continue
                    except (ValueError, TypeError):
                        pass
                
                # Get canonical ID (guid or link)
                canonical_id = None
                if hasattr(entry, "id") and entry.id:
                    canonical_id = entry.id
                elif hasattr(entry, "link") and entry.link:
                    canonical_id = entry.link
                
                # Get title and link
                title = getattr(entry, "title", None)
                url = getattr(entry, "link", None)
                
                # Build payload (full entry as dict)
                payload = {
                    "title": title,
                    "link": url,
                    "summary": getattr(entry, "summary", None),
                    "content": getattr(entry, "content", [{}])[0].get("value") if hasattr(entry, "content") else None,
                    "published": getattr(entry, "published", None),
                    "published_parsed": entry.published_parsed if hasattr(entry, "published_parsed") else None,
                    "tags": [tag.term for tag in entry.tags] if hasattr(entry, "tags") else [],
                }
                
                candidates.append(RawItemCandidate(
                    canonical_id=canonical_id,
                    title=title,
                    url=url,
                    published_at_utc=published_at_utc,
                    payload=payload,
                ))
            
            bytes_downloaded = len(response.content or b"")
            return AdapterFetchResponse(
                items=candidates,
                status_code=response.status_code,
                bytes_downloaded=bytes_downloaded,
            )
            
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch RSS feed {self.url}: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to parse RSS feed {self.url}: {e}") from e


class NWSAlertsAdapter(SourceAdapter):
    """Adapter for NWS Alerts API (JSON format)."""
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for NWS requests (requires User-Agent and Accept)."""
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/geo+json",  # NWS prefers geo+json
        }
    
    def fetch(self, since_hours: Optional[int] = None) -> AdapterFetchResponse:
        """Fetch items from NWS Alerts API."""
        try:
            response = requests.get(
                self.url,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            data = response.json()
            features = data.get("features", [])
            candidates = []
            
            cutoff_time = None
            if since_hours:
                cutoff_time = datetime.now(timezone.utc).timestamp() - (since_hours * 3600)
            
            for feature in features[:self.max_items]:
                properties = feature.get("properties", {})
                
                # Parse sent time (NWS uses ISO 8601)
                published_at_utc = None
                sent_str = properties.get("sent")
                if sent_str:
                    try:
                        # NWS format: "2024-01-15T12:00:00-05:00" or similar
                        sent_dt = datetime.fromisoformat(sent_str.replace("Z", "+00:00"))
                        if sent_dt.tzinfo is None:
                            sent_dt = sent_dt.replace(tzinfo=timezone.utc)
                        else:
                            sent_dt = sent_dt.astimezone(timezone.utc)
                        published_at_utc = sent_dt.isoformat()
                        
                        # Filter by time if requested
                        if cutoff_time and sent_dt.timestamp() < cutoff_time:
                            continue
                    except (ValueError, TypeError):
                        pass
                
                # Get canonical ID (NWS alert ID)
                canonical_id = properties.get("id")
                
                # Get title and URL
                title = properties.get("headline") or properties.get("event", "NWS Alert")
                url = properties.get("web_url") or properties.get("url")
                
                # Build payload (full feature as dict)
                payload = {
                    "id": canonical_id,
                    "headline": properties.get("headline"),
                    "event": properties.get("event"),
                    "severity": properties.get("severity"),
                    "urgency": properties.get("urgency"),
                    "certainty": properties.get("certainty"),
                    "areaDesc": properties.get("areaDesc"),
                    "description": properties.get("description"),
                    "instruction": properties.get("instruction"),
                    "sent": properties.get("sent"),
                    "effective": properties.get("effective"),
                    "expires": properties.get("expires"),
                    "status": properties.get("status"),
                    "messageType": properties.get("messageType"),
                    "web_url": properties.get("web_url"),
                    "geometry": feature.get("geometry"),
                }
                
                candidates.append(RawItemCandidate(
                    canonical_id=canonical_id,
                    title=title,
                    url=url,
                    published_at_utc=published_at_utc,
                    payload=payload,
                ))
            
            bytes_downloaded = len(response.content or b"")
            return AdapterFetchResponse(
                items=candidates,
                status_code=response.status_code,
                bytes_downloaded=bytes_downloaded,
            )
            
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch NWS alerts from {self.url}: {e}") from e
        except (json.JSONDecodeError, KeyError) as e:
            raise RuntimeError(f"Failed to parse NWS alerts response from {self.url}: {e}") from e


class FEMAAdapter(SourceAdapter):
    """Adapter for FEMA/IPAWS feeds (can be RSS or JSON)."""
    
    def fetch(self, since_hours: Optional[int] = None) -> AdapterFetchResponse:
        """
        Fetch items from FEMA/IPAWS feed.
        Tries to detect format (RSS vs JSON) and uses appropriate parser.
        """
        try:
            response = requests.get(
                self.url,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            content_type = response.headers.get("Content-Type", "").lower()
            
            # Try RSS/Atom first
            if "xml" in content_type or "rss" in content_type or "atom" in content_type:
                items = self._parse_rss_response(response, since_hours)
            else:
                items = self._parse_json_response(response, since_hours)

            bytes_downloaded = len(response.content or b"")
            return AdapterFetchResponse(
                items=items,
                status_code=response.status_code,
                bytes_downloaded=bytes_downloaded,
            )
                
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch FEMA feed from {self.url}: {e}") from e
    
    def _parse_rss_response(self, response: requests.Response, since_hours: Optional[int] = None) -> List[RawItemCandidate]:
        """Parse RSS/Atom response."""
        feed = feedparser.parse(response.content)
        candidates = []
        
        cutoff_time = None
        if since_hours:
            cutoff_time = datetime.now(timezone.utc).timestamp() - (since_hours * 3600)
        
        for entry in feed.entries[:self.max_items]:
            published_at_utc = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    published_at_utc = pub_dt.isoformat()
                    
                    if cutoff_time and pub_dt.timestamp() < cutoff_time:
                        continue
                except (ValueError, TypeError):
                    pass
            
            canonical_id = getattr(entry, "id", None) or getattr(entry, "link", None)
            title = getattr(entry, "title", None)
            url = getattr(entry, "link", None)
            
            payload = {
                "title": title,
                "link": url,
                "summary": getattr(entry, "summary", None),
                "published": getattr(entry, "published", None),
            }
            
            candidates.append(RawItemCandidate(
                canonical_id=canonical_id,
                title=title,
                url=url,
                published_at_utc=published_at_utc,
                payload=payload,
            ))
        
        return candidates
    
    def _parse_json_response(self, response: requests.Response, since_hours: Optional[int] = None) -> List[RawItemCandidate]:
        """Parse JSON response."""
        data = response.json()
        candidates = []
        
        cutoff_time = None
        if since_hours:
            cutoff_time = datetime.now(timezone.utc).timestamp() - (since_hours * 3600)
        
        # Handle different JSON structures
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Try common keys
            items = data.get("items", data.get("data", data.get("results", [])))
        
        for item in items[:self.max_items]:
            # Extract published date (try common fields)
            published_at_utc = None
            for date_field in ["published", "sent", "created", "date", "timestamp"]:
                if date_field in item:
                    try:
                        date_val = item[date_field]
                        if isinstance(date_val, str):
                            pub_dt = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
                            if pub_dt.tzinfo is None:
                                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                            else:
                                pub_dt = pub_dt.astimezone(timezone.utc)
                            published_at_utc = pub_dt.isoformat()
                            
                            if cutoff_time and pub_dt.timestamp() < cutoff_time:
                                break
                        elif isinstance(date_val, (int, float)):
                            pub_dt = datetime.fromtimestamp(date_val, tz=timezone.utc)
                            published_at_utc = pub_dt.isoformat()
                            
                            if cutoff_time and pub_dt.timestamp() < cutoff_time:
                                break
                    except (ValueError, TypeError):
                        continue
                    break
            
            canonical_id = item.get("id") or item.get("guid") or item.get("url")
            title = item.get("title") or item.get("headline") or item.get("name")
            url = item.get("url") or item.get("link") or item.get("web_url")
            
            candidates.append(RawItemCandidate(
                canonical_id=str(canonical_id) if canonical_id else None,
                title=title,
                url=url,
                published_at_utc=published_at_utc,
                payload=item,
            ))
        
        return candidates


def create_adapter(source_config: Dict, defaults: Dict) -> SourceAdapter:
    """
    Factory function to create appropriate adapter based on source type.
    
    Args:
        source_config: Source configuration dict
        defaults: Default configuration values
        
    Returns:
        SourceAdapter instance
    """
    source_type = source_config.get("type", "rss")
    
    if source_type == "rss" or source_type == "atom":
        return RSSAdapter(source_config, defaults)
    elif source_type == "nws_alerts":
        return NWSAlertsAdapter(source_config, defaults)
    elif source_type == "fema" or source_type == "ipaws":
        return FEMAAdapter(source_config, defaults)
    else:
        raise ValueError(f"Unknown source type: {source_type}")

