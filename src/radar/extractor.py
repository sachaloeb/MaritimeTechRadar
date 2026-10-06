"""Parse cached HTML into structured fields with whole-word keyword matching."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup

from radar.config import ScoringConfig

logger = logging.getLogger(__name__)

# ── Keyword matching ────────────────────────────────────────────────────────
# Whole-word/phrase matching with boundaries: (?<![a-z0-9])kw(?:s)?(?![a-z0-9])
# This prevents "port" from matching "support"/"report", "ai" from "email", etc.

_compiled_patterns: dict[str, re.Pattern[str]] = {}


def _compile_pattern(keyword: str) -> re.Pattern[str]:
    """Compile a regex for whole-word matching with optional plural 's'."""
    if keyword not in _compiled_patterns:
        escaped = re.escape(keyword.lower())
        pattern = rf"(?<![a-z0-9]){escaped}(?:s)?(?![a-z0-9])"
        _compiled_patterns[keyword] = re.compile(pattern, re.IGNORECASE)
    return _compiled_patterns[keyword]


def match_keywords(text: str, keywords: list[str]) -> set[str]:
    """Return the set of keywords that match in the text (whole-word)."""
    matched: set[str] = set()
    for kw in keywords:
        if _compile_pattern(kw).search(text):
            matched.add(kw)
    return matched


# ── HTML extraction ─────────────────────────────────────────────────────────


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


# ── Per-page extraction ─────────────────────────────────────────────────────


def extract_page(
    cache_path: Path, scoring_cfg: ScoringConfig
) -> dict | None:
    """Extract structured fields from a single cached page.

    Returns a dict with matched keyword sets per criterion/quadrant, or None.
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

    page_title, meta_desc, visible_text = _extract_text(content)
    snippet = visible_text[:500]

    # Match keywords per criterion (returns sets)
    criterion_matched: dict[str, set[str]] = {}
    for crit_name, crit_cfg in scoring_cfg.criteria.items():
        if crit_cfg.derived_from:
            # Derived criteria computed at aggregation time
            criterion_matched[crit_name] = set()
        else:
            criterion_matched[crit_name] = match_keywords(
                visible_text, crit_cfg.keywords
            )

    # Match keywords per quadrant
    quadrant_matched: dict[str, set[str]] = {}
    for quad_name, quad_cfg in scoring_cfg.quadrants.items():
        quadrant_matched[quad_name] = match_keywords(
            visible_text, quad_cfg.keywords
        )

    return {
        "url": raw.get("url", ""),
        "fetched_at": raw.get("fetched_at", ""),
        "http_status": raw.get("http_status"),
        "content_hash": raw.get("content_hash", ""),
        "page_title": page_title,
        "meta_description": meta_desc,
        "text_snippet": snippet,
        "_criterion_matched": criterion_matched,
        "_quadrant_matched": quadrant_matched,
    }


# ── Per-startup aggregation ─────────────────────────────────────────────────


def extract_startup(
    slug: str,
    name: str,
    cache_paths: list[Path],
    scoring_cfg: ScoringConfig,
) -> dict | None:
    """Extract and aggregate across all cached pages for a start-up.

    Uses UNION of matched keywords (distinct) so page count doesn't inflate scores.
    """
    pages = []
    for cp in cache_paths:
        result = extract_page(cp, scoring_cfg)
        if result is not None:
            pages.append(result)

    if not pages:
        logger.warning("No parseable pages for %s", slug)
        return None

    # Union matched keywords across pages
    crit_union: dict[str, set[str]] = {}
    for crit_name in scoring_cfg.criteria:
        crit_union[crit_name] = set()
        for p in pages:
            crit_union[crit_name] |= p["_criterion_matched"].get(crit_name, set())

    quad_union: dict[str, set[str]] = {}
    for quad_name in scoring_cfg.quadrants:
        quad_union[quad_name] = set()
        for p in pages:
            quad_union[quad_name] |= p["_quadrant_matched"].get(quad_name, set())

    # Derive theme_fit from best quadrant (D1 fix)
    for crit_name, crit_cfg in scoring_cfg.criteria.items():
        if crit_cfg.derived_from == "best_quadrant":
            best_quad_keywords: set[str] = set()
            for qset in quad_union.values():
                if len(qset) > len(best_quad_keywords):
                    best_quad_keywords = qset
            crit_union[crit_name] = best_quad_keywords

    # Deduplicate pages by content_hash for evidence_quality
    seen_hashes: set[str] = set()
    distinct_pages = 0
    for p in pages:
        ch = p.get("content_hash", "")
        if ch and ch not in seen_hashes:
            seen_hashes.add(ch)
            distinct_pages += 1

    first = pages[0]

    # Build source info columns (pipe-joined, aligned)
    source_urls = "|".join(p["url"] for p in pages)
    source_fetched_at = "|".join(p["fetched_at"] for p in pages)
    source_statuses = "|".join(
        str(p.get("http_status", "")) for p in pages
    )

    aggregated: dict = {
        "slug": slug,
        "name": name,
        "page_title": first["page_title"],
        "meta_description": first["meta_description"],
        "text_snippet": first["text_snippet"],
        "source_urls": source_urls,
        "source_fetched_at": source_fetched_at,
        "source_statuses": source_statuses,
        "source_count": len(pages),
        "distinct_pages": distinct_pages,
    }

    # Write hits and matched columns for each criterion
    for crit_name in scoring_cfg.criteria:
        matched = crit_union[crit_name]
        aggregated[f"{crit_name}_hits"] = len(matched)
        aggregated[f"{crit_name}_matched"] = "|".join(sorted(matched))

    # Write hits and matched columns for each quadrant
    for quad_name in scoring_cfg.quadrants:
        matched = quad_union[quad_name]
        aggregated[f"{quad_name}_hits"] = len(matched)
        aggregated[f"{quad_name}_matched"] = "|".join(sorted(matched))

    # evidence_quality: distinct pages + distinct evidence keywords
    ev_crit = scoring_cfg.criteria.get("evidence_quality")
    if ev_crit and not ev_crit.derived_from:
        ev_kw_hits = len(crit_union.get("evidence_quality", set()))
        aggregated["evidence_quality_hits"] = distinct_pages + ev_kw_hits

    return aggregated


def extract_all(
    collected: dict[str, list[Path]],
    scoring_cfg: ScoringConfig,
    slug_to_name: dict[str, str] | None = None,
) -> list[dict]:
    """Extract structured data for all start-ups."""
    slug_to_name = slug_to_name or {}
    rows = []
    for slug, paths in collected.items():
        name = slug_to_name.get(slug, slug)
        row = extract_startup(slug, name, paths, scoring_cfg)
        if row is not None:
            rows.append(row)
    return rows
