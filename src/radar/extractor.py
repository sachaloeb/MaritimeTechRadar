"""Parse cached HTML into structured fields with keyword hit counts."""

import json
import logging
from pathlib import Path

from bs4 import BeautifulSoup

from radar.config import ScoringConfig

logger = logging.getLogger(__name__)


def _extract_text(html: str) -> tuple[str, str, str]:
    """Extract title, meta description, and visible text from HTML."""
    soup = BeautifulSoup(html, "lxml")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = str(meta_tag["content"]).strip()

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    visible_text = soup.get_text(separator=" ", strip=True)

    return title, meta_desc, visible_text


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    """Count how many distinct keywords appear in the text (case-insensitive)."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def extract_page(cache_path: Path, scoring_cfg: ScoringConfig) -> dict | None:
    """Extract structured fields from a single cached page.

    Returns a dict of extracted fields, or None if the page can't be parsed.
    """
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Cannot read cache file %s: %s", cache_path, exc)
        return None

    content = raw.get("content", "")
    if not content.strip():
        logger.warning("Empty content in %s", cache_path)
        return None

    title, meta_desc, visible_text = _extract_text(content)
    snippet = visible_text[:500]

    # Count keyword hits per criterion
    criterion_hits: dict[str, int] = {}
    for crit_name, crit_cfg in scoring_cfg.criteria.items():
        criterion_hits[f"{crit_name}_hits"] = _count_keyword_hits(visible_text, crit_cfg.keywords)

    # Count keyword hits per quadrant
    quadrant_hits: dict[str, int] = {}
    for quad_name, quad_cfg in scoring_cfg.quadrants.items():
        quadrant_hits[f"{quad_name}_hits"] = _count_keyword_hits(visible_text, quad_cfg.keywords)

    return {
        "url": raw.get("url", ""),
        "fetched_at": raw.get("fetched_at", ""),
        "http_status": raw.get("http_status"),
        "title": title,
        "meta_description": meta_desc,
        "text_snippet": snippet,
        **criterion_hits,
        **quadrant_hits,
    }


def extract_startup(
    slug: str, cache_paths: list[Path], scoring_cfg: ScoringConfig
) -> dict | None:
    """Extract and aggregate fields across all cached pages for a start-up.

    Returns aggregated row or None if no pages could be parsed.
    """
    pages = []
    for cp in cache_paths:
        result = extract_page(cp, scoring_cfg)
        if result is not None:
            pages.append(result)

    if not pages:
        logger.warning("No parseable pages for %s", slug)
        return None

    # Aggregate: keep first title/description, sum keyword hits, join URLs
    first = pages[0]
    aggregated: dict = {
        "slug": slug,
        "title": first["title"],
        "meta_description": first["meta_description"],
        "text_snippet": first["text_snippet"],
        "source_urls": "|".join(p["url"] for p in pages),
        "fetched_at": first["fetched_at"],
        "source_count": len(pages),
    }

    # Sum all _hits columns across pages
    hit_keys = [k for k in first if k.endswith("_hits")]
    for key in hit_keys:
        aggregated[key] = sum(p.get(key, 0) for p in pages)

    return aggregated


def extract_all(
    collected: dict[str, list[Path]], scoring_cfg: ScoringConfig
) -> list[dict]:
    """Extract structured data for all start-ups."""
    rows = []
    for slug, paths in collected.items():
        row = extract_startup(slug, paths, scoring_cfg)
        if row is not None:
            rows.append(row)
    return rows
