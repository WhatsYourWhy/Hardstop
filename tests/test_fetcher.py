import pytest

import sentinel.retrieval.fetcher as fetcher_mod
from sentinel.retrieval.adapters import AdapterFetchResponse
from sentinel.retrieval.fetcher import SourceFetcher


def test_rate_limit_strict_disables_jitter(monkeypatch):
    sources_config = {"defaults": {"rate_limit": {"per_host_min_seconds": 2, "jitter_seconds": 5}}}
    fetcher = SourceFetcher(sources_config, strict=True, rng_seed=123)
    host = "https://example.com"

    monkeypatch.setattr(fetcher_mod.time, "time", lambda: 10.0)
    sleep_calls = []
    monkeypatch.setattr(fetcher_mod.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    fetcher._last_fetch_time[fetcher._get_host_from_url(host)] = 9.0

    fetcher._wait_for_rate_limit(host)

    assert sleep_calls == [pytest.approx(1.0)]


def test_best_effort_metadata_records_seed_and_inputs(monkeypatch):
    sources_config = {
        "defaults": {
            "rate_limit": {"per_host_min_seconds": 0, "jitter_seconds": 1},
            "max_items_per_fetch": 1,
        },
        "sources": [{"id": "source-1", "url": "https://example.com", "type": "rss"}],
    }
    fetcher = SourceFetcher(sources_config, strict=False, rng_seed=99)

    monkeypatch.setattr(fetcher_mod, "get_all_sources", lambda _cfg: _cfg.get("sources", []))

    class _Adapter:
        adapter_version = "demo@1"

        def __init__(self, *_, **__):
            self.source_id = "source-1"

        def fetch(self, since_hours=None):
            return AdapterFetchResponse(items=[], status_code=200, bytes_downloaded=0)

    monkeypatch.setattr(fetcher_mod, "create_adapter", lambda source, defaults, random_seed=None: _Adapter())
    monkeypatch.setattr(fetcher_mod.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(fetcher_mod.time, "time", lambda: 0.0)
    monkeypatch.setattr(fetcher_mod.time, "monotonic", lambda: 0.0)

    fetcher.fetch_all()
    metadata = fetcher.best_effort_metadata()

    assert metadata["seed"] == 99
    assert metadata["inputs_version"] == "source-1:demo@1"
    assert "jitter_seconds" in metadata["notes"]
