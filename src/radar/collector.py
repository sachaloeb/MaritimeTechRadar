"""Fetch URLs from startups.yaml, respecting robots.txt, rate limits, and caching."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import pandas as pd
import requests

from radar.config import ScoringConfig, StartupsConfig
from radar.paths import raw_dir

logger = logging.getLogger(__name__)

USER_AGENT = (
    "maritime-tech-radar/0.1 (research prototype; contact: sacha.loeb@hotmail.com)"
)
TIMEOUT = 15
MAX_RETRIES = 2
BACKOFF_BASE = 2.0
RATE_LIMIT_SECONDS = 2.0

# Outcome constants
FETCHED = "fetched"
CACHE_HIT = "cache_hit"
CACHED_FAILURE = "cached_failure"
ROBOTS_DENIED = "robots_denied"
ROBOTS_UNREACHABLE = "robots_unreachable"
DENYLIST = "denylist"
HTTP_ERROR = "http_error"
NETWORK_ERROR = "network_error"
NO_CACHE = "no_cache"

# Outcomes that count as "failed or blocked" (no usable page produced)
FAILED_OR_BLOCKED = frozenset({
    ROBOTS_DENIED, ROBOTS_UNREACHABLE, DENYLIST,
    HTTP_ERROR, NETWORK_ERROR, CACHED_FAILURE, NO_CACHE,
})


@dataclass(frozen=True)
class CollectResult:
    slug: str
    url: str
    outcome: str
    http_status: int | None
    fetched_at: str
    cache_path: Path | None


def url_to_cache_path(url: str, demo: bool = False) -> Path:
    """Deterministic cache path from URL hash."""
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return raw_dir(demo) / f"{h}.json"


def _is_denied(url: str, denylist: list[str]) -> bool:
    host = urlparse(url).hostname or ""
    for denied in denylist:
        if denied in host:
            return True
    return False


_robots_cache: dict[str, tuple[str, RobotFileParser | None]] = {}


_ROBOTS_ALLOW = "allow"
_ROBOTS_DENY_POLICY = "deny_policy"
_ROBOTS_UNREACHABLE = "unreachable"


def _check_robots(url: str) -> str:
    """Check robots.txt for *url*.

    Returns one of: _ROBOTS_ALLOW, _ROBOTS_DENY_POLICY, _ROBOTS_UNREACHABLE.
    Network/timeout errors are distinct from policy denials (G4 fix).
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    if robots_url not in _robots_cache:
        _rate_limit(robots_url)
        try:
            resp = requests.get(
                robots_url,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            if resp.status_code in (404, 410):
                logger.debug(
                    "robots.txt not found (%d) for %s, allowing",
                    resp.status_code, parsed.netloc,
                )
                _robots_cache[robots_url] = (_ROBOTS_ALLOW, None)
            elif resp.status_code in (401, 403):
                logger.warning(
                    "robots.txt returned %d for %s, disallowing all",
                    resp.status_code, parsed.netloc,
                )
                rp = RobotFileParser()
                rp.parse(["User-agent: *", "Disallow: /"])
                _robots_cache[robots_url] = (_ROBOTS_DENY_POLICY, rp)
            elif resp.status_code >= 500:
                logger.warning(
                    "robots.txt returned %d for %s, disallowing (conservative)",
                    resp.status_code, parsed.netloc,
                )
                rp = RobotFileParser()
                rp.parse(["User-agent: *", "Disallow: /"])
                _robots_cache[robots_url] = (_ROBOTS_DENY_POLICY, rp)
            else:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                _robots_cache[robots_url] = (_ROBOTS_ALLOW, rp)
        except requests.RequestException as exc:
            logger.warning(
                "Could not fetch robots.txt for %s (%s), "
                "disallowing (conservative, robots_unreachable)",
                parsed.netloc, exc,
            )
            # Network failure — never cached, returns ROBOTS_UNREACHABLE
            return _ROBOTS_UNREACHABLE

    status, rp = _robots_cache[robots_url]
    if status == _ROBOTS_DENY_POLICY:
        if rp is None:
            return _ROBOTS_DENY_POLICY
        return _ROBOTS_DENY_POLICY if not rp.can_fetch(USER_AGENT, url) else _ROBOTS_ALLOW
    if rp is None:
        return _ROBOTS_ALLOW
    return _ROBOTS_ALLOW if rp.can_fetch(USER_AGENT, url) else _ROBOTS_DENY_POLICY


_last_request_time: dict[str, float] = {}


def _rate_limit(url: str) -> None:
    host = urlparse(url).hostname or ""
    last = _last_request_time.get(host, 0.0)
    elapsed = time.monotonic() - last
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time[host] = time.monotonic()


def _fetch_with_retry(url: str) -> requests.Response:
    """Fetch URL with retries and exponential backoff."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            _rate_limit(url)
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "Retry %d/%d for %s after error: %s (waiting %.1fs)",
                    attempt + 1, MAX_RETRIES, url, exc, wait,
                )
                time.sleep(wait)
            else:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


def _save_cache(
    url: str,
    response: requests.Response | None,
    error: str | None = None,
    demo: bool = False,
) -> Path:
    """Save fetched page with provenance metadata."""
    cache_path = url_to_cache_path(url, demo)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    content = response.text if response is not None else ""
    record = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "http_status": response.status_code if response is not None else None,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "error": error,
        "content": content,
    }
    cache_path.write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    return cache_path


def _read_cache(cache_path: Path) -> dict | None:
    """Read a cache file and return parsed JSON, or None."""
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _is_usable(cache_data: dict | None) -> bool:
    """A cached page is usable only if status=200 and non-empty content."""
    if cache_data is None:
        return False
    return (
        cache_data.get("http_status") == 200
        and bool(cache_data.get("content", "").strip())
    )


def collect_url(
    slug: str,
    url: str,
    denylist: list[str],
    refresh: bool = False,
    demo: bool = False,
) -> CollectResult:
    """Collect a single URL. Returns a CollectResult."""
    now = datetime.now(timezone.utc).isoformat()
    cache_path = url_to_cache_path(url, demo)

    if _is_denied(url, denylist):
        logger.info("SKIP (denylist): %s [%s]", url, slug)
        return CollectResult(slug, url, DENYLIST, None, now, None)

    if cache_path.exists() and not refresh:
        cached = _read_cache(cache_path)
        if _is_usable(cached):
            logger.debug("CACHE HIT: %s [%s]", url, slug)
            return CollectResult(
                slug, url, CACHE_HIT,
                cached.get("http_status") if cached else None,
                cached.get("fetched_at", now) if cached else now,
                cache_path,
            )
        else:
            logger.debug("CACHED FAILURE: %s [%s]", url, slug)
            return CollectResult(
                slug, url, CACHED_FAILURE,
                cached.get("http_status") if cached else None,
                cached.get("fetched_at", now) if cached else now,
                None,
            )

    robots_result = _check_robots(url)
    if robots_result == _ROBOTS_UNREACHABLE:
        logger.info("SKIP (robots.txt unreachable): %s [%s]", url, slug)
        return CollectResult(slug, url, ROBOTS_UNREACHABLE, None, now, None)
    if robots_result == _ROBOTS_DENY_POLICY:
        logger.info("SKIP (robots.txt denied): %s [%s]", url, slug)
        return CollectResult(slug, url, ROBOTS_DENIED, None, now, None)

    try:
        resp = _fetch_with_retry(url)

        # After redirects, re-check final URL against denylist
        final_url = resp.url
        if final_url != url and _is_denied(final_url, denylist):
            logger.info(
                "SKIP (redirect to denylist): %s -> %s [%s]", url, final_url, slug
            )
            return CollectResult(slug, url, DENYLIST, resp.status_code, now, None)

        if resp.status_code >= 400:
            logger.warning("HTTP %d for %s [%s]", resp.status_code, url, slug)
            _save_cache(url, resp, demo=demo)
            return CollectResult(
                slug, url, HTTP_ERROR, resp.status_code, now, None
            )

        saved = _save_cache(url, resp, demo=demo)
        logger.info(
            "FETCHED %d %s (%d bytes) [%s]",
            resp.status_code, url, len(resp.content), slug,
        )
        return CollectResult(
            slug, url, FETCHED, resp.status_code, now, saved
        )
    except requests.RequestException as exc:
        logger.error("FAILED after retries: %s — %s [%s]", url, exc, slug)
        _save_cache(url, None, error=str(exc), demo=demo)
        return CollectResult(slug, url, NETWORK_ERROR, None, now, None)


def collect_all(
    startups_cfg: StartupsConfig,
    scoring_cfg: ScoringConfig,
    refresh: bool = False,
    offline: bool = False,
    demo: bool = False,
) -> tuple[dict[str, list[Path]], list[CollectResult]]:
    """Collect all URLs. Returns ({slug: [usable_cache_paths]}, [all_results])."""
    all_results: list[CollectResult] = []

    if offline:
        logger.info("OFFLINE mode: using cached pages only, zero network calls")
        result: dict[str, list[Path]] = {}
        for s in startups_cfg.startups:
            paths: list[Path] = []
            for url in s.urls:
                cp = url_to_cache_path(url, demo)
                if cp.exists():
                    cached = _read_cache(cp)
                    if _is_usable(cached):
                        paths.append(cp)
                        all_results.append(CollectResult(
                            s.slug, url, CACHE_HIT,
                            cached.get("http_status") if cached else None,
                            cached.get("fetched_at", "") if cached else "",
                            cp,
                        ))
                    else:
                        all_results.append(CollectResult(
                            s.slug, url, CACHED_FAILURE,
                            cached.get("http_status") if cached else None,
                            cached.get("fetched_at", "") if cached else "",
                            None,
                        ))
                else:
                    logger.warning(
                        "OFFLINE: no cache for %s (%s)", url, s.slug
                    )
                    all_results.append(CollectResult(
                        s.slug, url, NO_CACHE, None, "", None
                    ))
            result[s.slug] = paths
        return result, all_results

    result = {}
    for s in startups_cfg.startups:
        paths = []
        for url in s.urls:
            cr = collect_url(s.slug, url, scoring_cfg.denylist,
                             refresh=refresh, demo=demo)
            all_results.append(cr)
            if cr.cache_path is not None:
                paths.append(cr.cache_path)
        result[s.slug] = paths
        logger.info(
            "Collected %d/%d usable pages for %s",
            len(paths), len(s.urls), s.slug,
        )
    return result, all_results


def write_collection_report(
    results: list[CollectResult], output_path: Path
) -> None:
    """Write collection results to a CSV report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "slug": r.slug,
            "url": r.url,
            "outcome": r.outcome,
            "http_status": r.http_status,
            "fetched_at": r.fetched_at,
            "cache_path": str(r.cache_path) if r.cache_path else "",
        }
        for r in sorted(results, key=lambda r: (r.slug, r.url))
    ]
    pd.DataFrame(rows).to_csv(output_path, index=False)
    logger.info("Collection report written to %s", output_path)


def write_manifest(results: list[CollectResult], output_path: Path) -> None:
    """Write raw data manifest (provenance) CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in sorted(results, key=lambda r: (r.slug, r.url)):
        content_hash = ""
        if r.cache_path and r.cache_path.exists():
            cached = _read_cache(r.cache_path)
            if cached:
                content_hash = cached.get("content_hash", "")
        rows.append({
            "url": r.url,
            "fetched_at": r.fetched_at,
            "http_status": r.http_status,
            "content_hash": content_hash,
            "outcome": r.outcome,
        })
    pd.DataFrame(rows).to_csv(output_path, index=False)
    logger.info("Manifest written to %s", output_path)
