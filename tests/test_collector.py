"""Tests for the collector module. All HTTP is mocked with `responses`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

from radar.collector import (
    CACHE_HIT,
    CACHED_FAILURE,
    DENYLIST,
    FETCHED,
    HTTP_ERROR,
    NETWORK_ERROR,
    NO_CACHE,
    ROBOTS_DENIED,
    _is_denied,
    collect_all,
    collect_url,
    url_to_cache_path,
)
from radar.config import ScoringConfig, StartupsConfig


@pytest.fixture(autouse=True)
def _isolate_collector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect raw_dir to temp and clear caches."""
    monkeypatch.setattr("radar.collector._robots_cache", {})
    monkeypatch.setattr("radar.collector._last_request_time", {})
    monkeypatch.setattr("radar.collector.RATE_LIMIT_SECONDS", 0.0)
    monkeypatch.setattr("radar.paths._PROJECT_ROOT", tmp_path)


DENY = ["linkedin.com", "crunchbase.com"]


class TestDenylist:
    def test_denied(self):
        assert _is_denied("https://www.linkedin.com/company/foo", DENY)

    def test_allowed(self):
        assert not _is_denied("https://example.com/about", DENY)


class TestCollectUrl:
    @responses.activate
    def test_success(self):
        url = "https://example.com/page"
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="", status=200)
        responses.add(responses.GET, url,
                      body="<html>hello</html>", status=200)

        cr = collect_url("test", url, [])
        assert cr.outcome == FETCHED
        assert cr.cache_path is not None
        assert cr.cache_path.exists()
        data = json.loads(cr.cache_path.read_text())
        assert data["http_status"] == 200

    @responses.activate
    def test_404_returns_http_error(self):
        url = "https://example.com/missing"
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="", status=200)
        responses.add(responses.GET, url, body="not found", status=404)

        cr = collect_url("test", url, [])
        assert cr.outcome == HTTP_ERROR
        assert cr.cache_path is None

    @responses.activate
    def test_500_returns_http_error(self):
        url = "https://example.com/err"
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="", status=200)
        responses.add(responses.GET, url, body="error", status=500)

        cr = collect_url("test", url, [])
        assert cr.outcome == HTTP_ERROR

    @responses.activate
    def test_robots_denial(self):
        url = "https://example.com/secret"
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="User-agent: *\nDisallow: /secret\n", status=200)

        cr = collect_url("test", url, [])
        assert cr.outcome == ROBOTS_DENIED

    @responses.activate
    def test_robots_403_disallows(self):
        """D6: robots 403 -> disallow (conservative)."""
        url = "https://example.com/page"
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="Forbidden", status=403)

        cr = collect_url("test", url, [])
        assert cr.outcome == ROBOTS_DENIED

    @responses.activate
    def test_robots_5xx_disallows(self):
        """D6: robots 5xx -> disallow (conservative)."""
        url = "https://example.com/page"
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="error", status=503)

        cr = collect_url("test", url, [])
        assert cr.outcome == ROBOTS_DENIED

    def test_denylist_outcome(self):
        cr = collect_url("test", "https://linkedin.com/x", DENY)
        assert cr.outcome == DENYLIST

    @responses.activate
    def test_cache_hit_no_requests(self):
        """D5: cache hit of usable page makes zero requests."""
        url = "https://example.com/cached"
        cp = url_to_cache_path(url)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({
            "url": url, "content": "<html>ok</html>",
            "http_status": 200, "fetched_at": "2026-01-01T00:00:00Z",
            "content_hash": "abc",
        }))

        cr = collect_url("test", url, [])
        assert cr.outcome == CACHE_HIT
        assert len(responses.calls) == 0

    @responses.activate
    def test_cached_failure_not_usable(self):
        """D5: cached 404 is reported as cached_failure, not usable."""
        url = "https://example.com/bad"
        cp = url_to_cache_path(url)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({
            "url": url, "content": "not found",
            "http_status": 404, "fetched_at": "2026-01-01T00:00:00Z",
        }))

        cr = collect_url("test", url, [])
        assert cr.outcome == CACHED_FAILURE
        assert cr.cache_path is None

    @responses.activate
    def test_refresh_refetches(self):
        url = "https://example.com/r"
        cp = url_to_cache_path(url)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({
            "url": url, "content": "old", "http_status": 200,
            "fetched_at": "2026-01-01T00:00:00Z", "content_hash": "old",
        }))
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="", status=200)
        responses.add(responses.GET, url, body="<html>new</html>", status=200)

        cr = collect_url("test", url, [], refresh=True)
        assert cr.outcome == FETCHED

    @responses.activate
    def test_timeout_retries_exact_count(self):
        """Exact attempt count = 1 + MAX_RETRIES = 3."""
        url = "https://example.com/slow"
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="", status=200)
        for _ in range(3):
            responses.add(responses.GET, url,
                          body=responses.ConnectionError("timeout"))

        with patch("radar.collector.BACKOFF_BASE", 0.001):
            cr = collect_url("test", url, [])

        assert cr.outcome == NETWORK_ERROR
        # 1 robots + 3 page attempts = 4
        assert len(responses.calls) == 4

    @responses.activate
    def test_user_agent_header(self):
        url = "https://example.com/ua"
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="", status=200)
        responses.add(responses.GET, url, body="<html>ok</html>", status=200)

        collect_url("test", url, [])
        page_call = responses.calls[-1]
        assert "maritime-tech-radar" in page_call.request.headers["User-Agent"]
        assert "@" in page_call.request.headers["User-Agent"]

    @responses.activate
    def test_redirect_to_denylisted_host(self):
        """D6: redirect to denylisted host -> denylist outcome."""
        url = "https://example.com/redir"
        responses.add(responses.GET, "https://example.com/robots.txt",
                      body="", status=200)
        responses.add(
            responses.GET, url, status=301,
            headers={"Location": "https://linkedin.com/profile"},
        )
        responses.add(
            responses.GET, "https://linkedin.com/profile",
            body="<html>linked</html>", status=200,
        )

        cr = collect_url("test", url, DENY)
        assert cr.outcome == DENYLIST


class TestCollectAllOffline:
    def test_offline_uses_cache(self):
        url = "https://example.com/page"
        cp = url_to_cache_path(url)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({
            "url": url, "content": "<html>ok</html>",
            "http_status": 200, "fetched_at": "2026-01-01",
            "content_hash": "x",
        }))

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

        collected, results = collect_all(
            startups_cfg, scoring_cfg, offline=True
        )
        assert len(collected["test"]) == 1
        assert all(r.outcome in (CACHE_HIT, NO_CACHE) for r in results)

    def test_offline_no_cache(self):
        startups_cfg = StartupsConfig(
            startups=[{"name": "T", "slug": "t",
                       "urls": ["https://example.com/nope"]}]
        )
        scoring_cfg = ScoringConfig(
            criteria={
                "a": {"weight": 0.5, "saturation": 5, "keywords": ["x"]},
                "b": {"weight": 0.5, "saturation": 5, "keywords": ["y"]},
            },
            quadrants={"q1": {"label": "Q1", "keywords": ["k"]}},
        )

        collected, results = collect_all(
            startups_cfg, scoring_cfg, offline=True
        )
        assert len(collected["t"]) == 0
        assert results[0].outcome == NO_CACHE
