"""Adapter-level parsing tests."""

import json
from pathlib import Path

import pytest
import requests

from hardstop.retrieval.adapters import FEMAAdapter, NWSAlertsAdapter, RSSAdapter

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "adapters"


def _build_response(*, content: bytes, status_code: int = 200, headers: dict | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = content
    response.headers = headers or {}
    response.url = "https://example.com/feed"
    return response


def _default_source_config(source_type: str) -> dict:
    return {
        "id": f"{source_type}-source",
        "type": source_type,
        "url": "https://example.com/feed",
        "adapter_version": "test",
    }


def _default_defaults() -> dict:
    return {
        "timeout_seconds": 5,
        "user_agent": "hardstop-tests",
        "max_items_per_fetch": 10,
    }


def test_rss_adapter_parses_feed(mocker):
    content = (FIXTURES_DIR / "rss_feed.xml").read_bytes()
    response = _build_response(content=content, headers={"Content-Type": "application/rss+xml"})
    mocker.patch("requests.get", return_value=response)

    adapter = RSSAdapter(_default_source_config("rss"), _default_defaults())
    result = adapter.fetch()

    assert len(result.items) == 2
    first = result.items[0]
    assert first.canonical_id == "rss-1"
    assert first.title == "Alert One"
    assert first.url == "https://example.com/alerts/1"
    assert first.published_at_utc == "2024-01-01T12:00:00+00:00"
    assert first.payload["summary"] == "First alert summary."


def test_nws_adapter_parses_geojson(mocker):
    content = (FIXTURES_DIR / "nws_alerts.json").read_bytes()
    response = _build_response(content=content, headers={"Content-Type": "application/geo+json"})
    mocker.patch("requests.get", return_value=response)

    adapter = NWSAlertsAdapter(_default_source_config("nws_alerts"), _default_defaults())
    result = adapter.fetch()

    assert len(result.items) == 1
    item = result.items[0]
    assert item.canonical_id == "nws-1"
    assert item.title == "Winter Weather Advisory"
    assert item.url == "https://alerts.weather.gov/nws-1"
    assert item.published_at_utc == "2024-01-15T17:00:00+00:00"
    assert item.payload["severity"] == "Moderate"
    assert item.payload["geometry"]["type"] == "Point"


def test_fema_adapter_parses_json(mocker):
    content = (FIXTURES_DIR / "fema_feed.json").read_bytes()
    response = _build_response(content=content, headers={"Content-Type": "application/json"})
    mocker.patch("requests.get", return_value=response)

    adapter = FEMAAdapter(_default_source_config("fema"), _default_defaults())
    result = adapter.fetch()

    assert len(result.items) == 2
    first, second = result.items
    assert first.canonical_id == "fema-1"
    assert first.title == "FEMA Alert One"
    assert first.url == "https://example.com/fema/1"
    assert first.published_at_utc == "2024-02-01T15:00:00+00:00"
    assert second.canonical_id == "fema-2"
    assert second.title == "FEMA Alert Two"
    assert second.url == "https://example.com/fema/2"


def test_fema_adapter_parses_rss(mocker):
    content = (FIXTURES_DIR / "fema_feed.xml").read_bytes()
    response = _build_response(content=content, headers={"Content-Type": "application/rss+xml"})
    mocker.patch("requests.get", return_value=response)

    adapter = FEMAAdapter(_default_source_config("fema"), _default_defaults())
    result = adapter.fetch()

    assert len(result.items) == 1
    item = result.items[0]
    assert item.canonical_id == "fema-rss-1"
    assert item.title == "FEMA RSS Alert"
    assert item.url == "https://example.com/fema/rss/1"
    assert item.published_at_utc == "2024-01-03T14:00:00+00:00"


def test_nws_adapter_invalid_json_raises_runtime_error(mocker):
    response = _build_response(content=b"{invalid", headers={"Content-Type": "application/geo+json"})
    mocker.patch("requests.get", return_value=response)

    adapter = NWSAlertsAdapter(_default_source_config("nws_alerts"), _default_defaults())

    with pytest.raises(RuntimeError, match="Failed to parse NWS alerts response"):
        adapter.fetch()


def test_fema_adapter_invalid_json_raises_decode_error(mocker):
    response = _build_response(content=b"{invalid", headers={"Content-Type": "application/json"})
    mocker.patch("requests.get", return_value=response)

    adapter = FEMAAdapter(_default_source_config("fema"), _default_defaults())

    with pytest.raises(json.JSONDecodeError):
        adapter.fetch()


def test_rss_adapter_parse_failure_raises_runtime_error(mocker):
    content = (FIXTURES_DIR / "rss_feed.xml").read_bytes()
    response = _build_response(content=content, headers={"Content-Type": "application/rss+xml"})
    mocker.patch("requests.get", return_value=response)
    mocker.patch("feedparser.parse", side_effect=ValueError("bad feed"))

    adapter = RSSAdapter(_default_source_config("rss"), _default_defaults())

    with pytest.raises(RuntimeError, match="Failed to parse RSS feed"):
        adapter.fetch()
