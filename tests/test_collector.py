"""Tests for the collector module. All HTTP is mocked with `responses`."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

from radar.collector import (
    _is_denied,
    _url_to_cache_path,
    collect_all,
    collect_url,
)
from radar.config import ScoringConfig, StartupsConfig


@pytest.fixture(autouse=True)
def _isolate_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect RAW_DIR to a temp directory and clear robots cache."""
    monkeypatch.setattr("radar.collector.RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr("radar.collector._robots_cache", {})
    monkeypatch.setattr("radar.collector._last_request_time", {})
    monkeypatch.setattr("radar.collector.RATE_LIMIT_SECONDS", 0.0)


DENYLIST = ["linkedin.com", "crunchbase.com"]


class TestDenylist:
    def test_denied(self):
        assert _is_denied("https://www.linkedin.com/company/foo", DENYLIST)

    def test_allowed(self):
        assert not _is_denied("https://example.com/about", DENYLIST)


class TestCollectUrl:
    @responses.activate
    def test_success(self, tmp_path: Path):
        url = "https://example.com/page"
        responses.add(responses.GET, "https://example.com/robots.txt", body="", status=200)
        responses.add(responses.GET, url, body="<html>hello</html>", status=200)

        path = collect_url(url, [])
        assert path is not None
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["http_status"] == 200
        assert "hello" in data["content"]

    @responses.activate
    def test_404_returns_none(self, tmp_path: Path):
        url = "https://example.com/missing"
        responses.add(responses.GET, "https://example.com/robots.txt", body="", status=200)
        responses.add(responses.GET, url, body="not found", status=404)

        path = collect_url(url, [])
        assert path is None

    @responses.activate
    def test_robots_denial(self, tmp_path: Path):
        url = "https://example.com/secret"
        robots_body = "User-agent: *\nDisallow: /secret\n"
        responses.add(responses.GET, "https://example.com/robots.txt", body=robots_body, status=200)

        path = collect_url(url, [])
        assert path is None

    @responses.activate
    def test_cache_hit(self, tmp_path: Path):
        url = "https://example.com/cached"
        cache_path = _url_to_cache_path(url)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"url": url, "content": "cached"}))

        path = collect_url(url, [])
        assert path == cache_path
        # No HTTP requests should have been made
        assert len(responses.calls) == 0

    @responses.activate
    def test_timeout_retries(self, tmp_path: Path):
        url = "https://example.com/slow"
        responses.add(responses.GET, "https://example.com/robots.txt", body="", status=200)
        responses.add(responses.GET, url, body=responses.ConnectionError("timeout"))
        responses.add(responses.GET, url, body=responses.ConnectionError("timeout"))
        responses.add(responses.GET, url, body=responses.ConnectionError("timeout"))

        with patch("radar.collector.BACKOFF_BASE", 0.01):
            path = collect_url(url, [])
        assert path is None


class TestCollectAllOffline:
    def test_offline_uses_cache(self, tmp_path: Path):
        url = "https://example.com/page"
        cache_path = _url_to_cache_path(url)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"url": url, "content": "cached"}))

        startups_cfg = StartupsConfig(
            startups=[{"name": "Test", "slug": "test", "urls": [url]}]
        )
        scoring_cfg = ScoringConfig(
            criteria={
                "a": {"weight": 0.5, "saturation": 5, "keywords": ["x"]},
                "b": {"weight": 0.5, "saturation": 5, "keywords": ["y"]},
            },
            quadrants={"q1": {"label": "Q1", "keywords": ["k"]}},
        )

        result = collect_all(startups_cfg, scoring_cfg, offline=True)
        assert len(result["test"]) == 1

    def test_offline_missing_cache(self, tmp_path: Path):
        startups_cfg = StartupsConfig(
            startups=[
                {"name": "Test", "slug": "test", "urls": ["https://example.com/nope"]}
            ]
        )
        scoring_cfg = ScoringConfig(
            criteria={
                "a": {"weight": 0.5, "saturation": 5, "keywords": ["x"]},
                "b": {"weight": 0.5, "saturation": 5, "keywords": ["y"]},
            },
            quadrants={"q1": {"label": "Q1", "keywords": ["k"]}},
        )

        result = collect_all(startups_cfg, scoring_cfg, offline=True)
        assert len(result["test"]) == 0
