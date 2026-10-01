"""Fetch URLs from startups.yaml, respecting robots.txt, rate limits, and caching."""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from radar.config import ScoringConfig, StartupsConfig

logger = logging.getLogger(__name__)

USER_AGENT = "maritime-tech-radar/0.1 (research prototype; contact: sacha.loeb@hotmail.com)"
TIMEOUT = 15
MAX_RETRIES = 2
BACKOFF_BASE = 2.0
RATE_LIMIT_SECONDS = 2.0
RAW_DIR = Path("data/raw")


def _url_to_cache_path(url: str) -> Path:
    """Deterministic cache path from URL hash."""
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return RAW_DIR / f"{h}.json"


def _is_denied(url: str, denylist: list[str]) -> bool:
    host = urlparse(url).hostname or ""
    for denied in denylist:
        if denied in host:
            return True
    return False


_robots_cache: dict[str, RobotFileParser | None] = {}


def _check_robots(url: str) -> bool:
    """Return True if robots.txt allows fetching this URL."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    if robots_url not in _robots_cache:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
            _robots_cache[robots_url] = rp
        except Exception:
            logger.warning("Could not fetch robots.txt for %s, allowing by default", parsed.netloc)
            _robots_cache[robots_url] = None

    rp = _robots_cache[robots_url]
    if rp is None:
        return True
    return rp.can_fetch(USER_AGENT, url)


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
                url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, allow_redirects=True
            )
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "Retry %d/%d for %s after error: %s (waiting %.1fs)",
                    attempt + 1,
                    MAX_RETRIES,
                    url,
                    exc,
                    wait,
                )
                time.sleep(wait)
            else:
                raise


def _save_cache(url: str, response: requests.Response | None, error: str | None = None) -> Path:
    """Save fetched page with provenance metadata."""
    cache_path = _url_to_cache_path(url)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    content = response.text if response is not None else ""
    record = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "http_status": response.status_code if response is not None else None,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "error": error,
        "content": content,
    }
    cache_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return cache_path


def collect_url(url: str, denylist: list[str], refresh: bool = False) -> Path | None:
    """Collect a single URL. Returns the cache path or None if skipped."""
    cache_path = _url_to_cache_path(url)

    if _is_denied(url, denylist):
        logger.info("SKIP (denylist): %s", url)
        return None

    if cache_path.exists() and not refresh:
        logger.debug("CACHE HIT: %s", url)
        return cache_path

    if not _check_robots(url):
        logger.info("SKIP (robots.txt): %s", url)
        return None

    try:
        resp = _fetch_with_retry(url)
        if resp.status_code >= 400:
            logger.warning("HTTP %d for %s", resp.status_code, url)
            _save_cache(url, resp)
            return None
        logger.info("FETCHED %d %s (%d bytes)", resp.status_code, url, len(resp.content))
        return _save_cache(url, resp)
    except requests.RequestException as exc:
        logger.error("FAILED after retries: %s — %s", url, exc)
        _save_cache(url, None, error=str(exc))
        return None


def collect_all(
    startups_cfg: StartupsConfig,
    scoring_cfg: ScoringConfig,
    refresh: bool = False,
    offline: bool = False,
) -> dict[str, list[Path]]:
    """Collect all URLs for all start-ups. Returns {slug: [cache_paths]}."""
    if offline:
        logger.info("OFFLINE mode: using cached pages only")
        result: dict[str, list[Path]] = {}
        for s in startups_cfg.startups:
            paths = []
            for url in s.urls:
                cp = _url_to_cache_path(url)
                if cp.exists():
                    paths.append(cp)
                else:
                    logger.warning("OFFLINE: no cache for %s (%s)", url, s.slug)
            result[s.slug] = paths
        return result

    result = {}
    for s in startups_cfg.startups:
        paths = []
        for url in s.urls:
            path = collect_url(url, scoring_cfg.denylist, refresh=refresh)
            if path is not None:
                paths.append(path)
        result[s.slug] = paths
        logger.info("Collected %d/%d pages for %s", len(paths), len(s.urls), s.slug)
    return result
