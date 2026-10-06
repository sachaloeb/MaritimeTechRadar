"""Tests for the extractor module: whole-word matching, union aggregation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from radar.config import load_scoring_config
from radar.extractor import extract_all, extract_page, extract_startup, match_keywords

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def scoring_cfg():
    return load_scoring_config(Path("configs/scoring.yaml"))


def _make_cache(
    tmp_path: Path, url: str, html_path: Path, content_hash: str = "abc123"
) -> Path:
    cache = tmp_path / f"{html_path.stem}.json"
    cache.write_text(
        json.dumps({
            "url": url,
            "fetched_at": "2026-01-15T12:00:00+00:00",
            "http_status": 200,
            "content_hash": content_hash,
            "error": None,
            "content": html_path.read_text(encoding="utf-8"),
        }),
        encoding="utf-8",
    )
    return cache


# ── D2 regression: whole-word matching ───────────────────────────────────────


class TestWholeWordMatching:
    def test_port_not_in_support(self):
        assert match_keywords("We provide support services", ["port"]) == set()

    def test_port_not_in_report(self):
        assert match_keywords("Read our annual report", ["port"]) == set()

    def test_port_matches_port(self):
        assert match_keywords("Ships dock at the port", ["port"]) == {"port"}

    def test_port_matches_ports_plural(self):
        assert match_keywords("Major ports in Europe", ["port"]) == {"port"}

    def test_ai_not_in_email(self):
        assert match_keywords("Send us an email", ["ai"]) == set()

    def test_ai_not_in_maintain(self):
        assert match_keywords("We maintain systems", ["ai"]) == set()

    def test_ai_matches_ai(self):
        assert match_keywords("We use AI for analytics", ["ai"]) == {"ai"}

    def test_wind_not_in_window(self):
        assert match_keywords("Look through the window", ["wind"]) == set()

    def test_wind_matches_wind(self):
        assert match_keywords("Wind energy solutions", ["wind"]) == {"wind"}

    def test_data_not_in_update(self):
        assert match_keywords("We update daily", ["data"]) == set()

    def test_data_matches_data(self):
        assert match_keywords("Data analytics platform", ["data"]) == {"data"}

    def test_phrase_matching(self):
        result = match_keywords(
            "Our supply chain solution", ["supply chain"]
        )
        assert result == {"supply chain"}

    def test_carbon_not_in_hydrocarbon(self):
        assert match_keywords("hydrocarbon fuels", ["carbon"]) == set()


# ── Extraction tests ─────────────────────────────────────────────────────────


class TestExtractPage:
    def test_good_page(self, tmp_path: Path, scoring_cfg):
        cache = _make_cache(
            tmp_path, "https://example.com", FIXTURES / "good_page.html"
        )
        result = extract_page(cache, scoring_cfg)
        assert result is not None
        assert result["page_title"] == (
            "OceanClean Tech — Maritime Decarbonisation Platform"
        )
        assert "hydrogen" in result["meta_description"]
        assert "_criterion_matched" in result
        assert "_quadrant_matched" in result

    def test_malformed_page(self, tmp_path: Path, scoring_cfg):
        cache = _make_cache(
            tmp_path, "https://example.com/bad",
            FIXTURES / "malformed_page.html",
        )
        result = extract_page(cache, scoring_cfg)
        assert result is not None
        m = result["_criterion_matched"]["maritime_relevance"]
        assert len(m) > 0

    def test_truly_empty_returns_none(self, tmp_path: Path, scoring_cfg):
        cache = tmp_path / "empty.json"
        cache.write_text(json.dumps({
            "url": "https://x.com", "fetched_at": "",
            "http_status": 200, "content_hash": "",
            "error": None, "content": "",
        }))
        assert extract_page(cache, scoring_cfg) is None

    def test_corrupt_json_returns_none(self, tmp_path: Path, scoring_cfg):
        bad = tmp_path / "corrupt.json"
        bad.write_text("not json")
        assert extract_page(bad, scoring_cfg) is None


class TestExtractStartup:
    def test_aggregation_union_based(self, tmp_path: Path, scoring_cfg):
        """D3: hits are union-based, not summed per page."""
        c1 = _make_cache(
            tmp_path, "https://example.com/1",
            FIXTURES / "good_page.html", content_hash="h1",
        )
        c2 = tmp_path / "good_page_2.json"
        c2.write_text(json.dumps({
            "url": "https://example.com/2",
            "fetched_at": "2026-01-15T12:00:00+00:00",
            "http_status": 200, "content_hash": "h2", "error": None,
            "content": (FIXTURES / "good_page.html").read_text(),
        }))

        result = extract_startup(
            "test-co", "Test Co", [c1, c2], scoring_cfg
        )
        assert result is not None
        # Same keywords on both pages -> union should be same as one page
        single = extract_startup(
            "test-co", "Test Co", [c1], scoring_cfg
        )
        assert result["maritime_relevance_hits"] == single["maritime_relevance_hits"]

    def test_name_carried_through(self, tmp_path: Path, scoring_cfg):
        c1 = _make_cache(
            tmp_path, "https://example.com", FIXTURES / "good_page.html"
        )
        result = extract_startup("oc", "OceanClean", [c1], scoring_cfg)
        assert result is not None
        assert result["name"] == "OceanClean"

    def test_matched_columns_present(self, tmp_path: Path, scoring_cfg):
        c1 = _make_cache(
            tmp_path, "https://example.com", FIXTURES / "good_page.html"
        )
        result = extract_startup("oc", "OceanClean", [c1], scoring_cfg)
        assert "maritime_relevance_matched" in result
        assert isinstance(result["maritime_relevance_matched"], str)

    def test_theme_fit_derived_from_best_quadrant(
        self, tmp_path: Path, scoring_cfg
    ):
        """D1 regression: theme_fit_hits > 0 when quadrants have hits."""
        c1 = _make_cache(
            tmp_path, "https://example.com", FIXTURES / "good_page.html"
        )
        result = extract_startup("oc", "OceanClean", [c1], scoring_cfg)
        assert result["theme_fit_hits"] > 0

    def test_evidence_quality_includes_distinct_pages(
        self, tmp_path: Path, scoring_cfg
    ):
        """D3: evidence_quality = distinct pages + evidence keywords."""
        c1 = _make_cache(
            tmp_path, "https://example.com/1",
            FIXTURES / "good_page.html", content_hash="h1",
        )
        result = extract_startup("oc", "OceanClean", [c1], scoring_cfg)
        # 1 distinct page + evidence keywords matched
        assert result["evidence_quality_hits"] >= 1

    def test_source_columns_aligned(self, tmp_path: Path, scoring_cfg):
        c1 = _make_cache(
            tmp_path, "https://example.com/1",
            FIXTURES / "good_page.html", content_hash="h1",
        )
        c2 = tmp_path / "mal.json"
        c2.write_text(json.dumps({
            "url": "https://example.com/2",
            "fetched_at": "2026-01-16T12:00:00+00:00",
            "http_status": 200, "content_hash": "h2", "error": None,
            "content": (FIXTURES / "malformed_page.html").read_text(),
        }))
        result = extract_startup("oc", "OC", [c1, c2], scoring_cfg)
        assert result is not None
        urls = result["source_urls"].split("|")
        dates = result["source_fetched_at"].split("|")
        statuses = result["source_statuses"].split("|")
        assert len(urls) == len(dates) == len(statuses) == 2


class TestExtractAll:
    def test_extract_all(self, tmp_path: Path, scoring_cfg):
        c1 = _make_cache(
            tmp_path, "https://example.com", FIXTURES / "good_page.html"
        )
        rows = extract_all(
            {"ocean-clean": [c1]}, scoring_cfg,
            slug_to_name={"ocean-clean": "OceanClean"},
        )
        assert len(rows) == 1
        assert rows[0]["slug"] == "ocean-clean"
        assert rows[0]["name"] == "OceanClean"
