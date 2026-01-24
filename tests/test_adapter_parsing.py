from pathlib import Path
import json

import requests

from hardstop.retrieval.adapters import FEMAAdapter, NWSAlertsAdapter, RSSAdapter


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "adapters"


class DummyResponse:
    def __init__(self, *, content: bytes, status_code: int = 200, headers: dict | None = None, json_data=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"Status {self.status_code}")

    def json(self):
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.content.decode("utf-8"))


def _source_config(source_type: str, url: str = "https://example.com/feed") -> dict:
    return {
        "id": f"test-{source_type}",
        "type": source_type,
        "url": url,
        "max_items_per_fetch": 10,
    }


def _defaults() -> dict:
    return {"timeout_seconds": 5, "user_agent": "hardstop-test/1.0"}


def test_rss_adapter_parsing(monkeypatch):
    fixture = (FIXTURE_DIR / "rss_feed.xml").read_bytes()

    def fake_get(*_args, **_kwargs):
        return DummyResponse(content=fixture, headers={"Content-Type": "application/rss+xml"})

    monkeypatch.setattr(requests, "get", fake_get)

    adapter = RSSAdapter(_source_config("rss"), _defaults())
    response = adapter.fetch()

    assert response.status_code == 200
    assert len(response.items) == 2
    assert response.items[0].canonical_id == "rss-1"
    assert response.items[0].title == "Alert One"
    assert response.items[0].url == "https://example.com/alerts/1"
    assert response.items[0].published_at_utc == "2024-01-01T12:00:00+00:00"


def test_nws_adapter_parsing(monkeypatch):
    fixture = json.loads((FIXTURE_DIR / "nws_alerts.json").read_text(encoding="utf-8"))

    def fake_get(*_args, **_kwargs):
        return DummyResponse(
            content=json.dumps(fixture).encode("utf-8"),
            headers={"Content-Type": "application/geo+json"},
            json_data=fixture,
        )

    monkeypatch.setattr(requests, "get", fake_get)

    adapter = NWSAlertsAdapter(_source_config("nws_alerts"), _defaults())
    response = adapter.fetch()

    assert response.status_code == 200
    assert len(response.items) == 1
    item = response.items[0]
    assert item.canonical_id == "nws-1"
    assert item.title == "Winter Weather Advisory"
    assert item.url == "https://alerts.weather.gov/nws-1"
    assert item.published_at_utc == "2024-01-15T17:00:00+00:00"


def test_fema_adapter_parses_rss(monkeypatch):
    fixture = (FIXTURE_DIR / "fema_feed.xml").read_bytes()

    def fake_get(*_args, **_kwargs):
        return DummyResponse(content=fixture, headers={"Content-Type": "application/rss+xml"})

    monkeypatch.setattr(requests, "get", fake_get)

    adapter = FEMAAdapter(_source_config("fema"), _defaults())
    response = adapter.fetch()

    assert response.status_code == 200
    assert len(response.items) == 1
    item = response.items[0]
    assert item.canonical_id == "fema-rss-1"
    assert item.title == "FEMA RSS Alert"
    assert item.url == "https://example.com/fema/rss/1"
    assert item.published_at_utc == "2024-01-03T14:00:00+00:00"


def test_fema_adapter_parses_json(monkeypatch):
    fixture_text = (FIXTURE_DIR / "fema_feed.json").read_text(encoding="utf-8")
    fixture = json.loads(fixture_text)

    def fake_get(*_args, **_kwargs):
        return DummyResponse(
            content=fixture_text.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            json_data=fixture,
        )

    monkeypatch.setattr(requests, "get", fake_get)

    adapter = FEMAAdapter(_source_config("fema"), _defaults())
    response = adapter.fetch()

    assert response.status_code == 200
    assert len(response.items) == 2
    assert response.items[0].canonical_id == "fema-1"
    assert response.items[0].title == "FEMA Alert One"
    assert response.items[0].url == "https://example.com/fema/1"
    assert response.items[0].published_at_utc == "2024-02-01T15:00:00+00:00"
    assert response.items[1].canonical_id == "fema-2"
    assert response.items[1].title == "FEMA Alert Two"
    assert response.items[1].url == "https://example.com/fema/2"
    assert response.items[1].published_at_utc == "2024-02-02T10:30:00+00:00"
