"""Tests for the extractor module using synthetic fixture HTML."""

import json
from pathlib import Path

import pytest

from radar.config import load_scoring_config
from radar.extractor import extract_all, extract_page, extract_startup

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def scoring_cfg():
    return load_scoring_config(Path("configs/scoring.yaml"))


def _make_cache(tmp_path: Path, url: str, html_path: Path) -> Path:
    """Create a cache JSON file from a fixture HTML file."""
    cache = tmp_path / f"{html_path.stem}.json"
    cache.write_text(
        json.dumps(
            {
                "url": url,
                "fetched_at": "2026-01-15T12:00:00+00:00",
                "http_status": 200,
                "content_hash": "abc123",
                "error": None,
                "content": html_path.read_text(encoding="utf-8"),
            }
        ),
        encoding="utf-8",
    )
    return cache


class TestExtractPage:
    def test_good_page(self, tmp_path: Path, scoring_cfg):
        cache = _make_cache(tmp_path, "https://example.com", FIXTURES / "good_page.html")
        result = extract_page(cache, scoring_cfg)

        assert result is not None
        assert result["title"] == "OceanClean Tech — Maritime Decarbonisation Platform"
        assert "hydrogen" in result["meta_description"]
        assert result["maritime_relevance_hits"] > 0
        assert result["decarbonisation_energy_hits"] > 0

    def test_malformed_page(self, tmp_path: Path, scoring_cfg):
        cache = _make_cache(tmp_path, "https://example.com/bad", FIXTURES / "malformed_page.html")
        result = extract_page(cache, scoring_cfg)

        assert result is not None
        assert result["maritime_relevance_hits"] > 0
        # lxml may not recover a title from badly broken markup — that's fine

    def test_empty_page_has_no_hits(self, tmp_path: Path, scoring_cfg):
        cache = _make_cache(tmp_path, "https://example.com/empty", FIXTURES / "empty_page.html")
        result = extract_page(cache, scoring_cfg)
        # HTML structure exists but no meaningful text — all hit counts should be 0
        assert result is not None
        assert result["maritime_relevance_hits"] == 0

    def test_truly_empty_content_returns_none(self, tmp_path: Path, scoring_cfg):
        cache = tmp_path / "empty.json"
        cache.write_text(
            json.dumps({"url": "https://x.com", "fetched_at": "", "http_status": 200,
                        "content_hash": "", "error": None, "content": ""}),
            encoding="utf-8",
        )
        assert extract_page(cache, scoring_cfg) is None

    def test_corrupt_json_returns_none(self, tmp_path: Path, scoring_cfg):
        bad = tmp_path / "corrupt.json"
        bad.write_text("not json at all")
        result = extract_page(bad, scoring_cfg)
        assert result is None


class TestExtractStartup:
    def test_aggregation(self, tmp_path: Path, scoring_cfg):
        c1 = _make_cache(tmp_path, "https://example.com/1", FIXTURES / "good_page.html")
        c2 = _make_cache(tmp_path, "https://example.com/2", FIXTURES / "malformed_page.html")
        # Need unique filenames
        c2_path = tmp_path / "malformed.json"
        c2_data = json.loads(c2.read_text())
        c2_data["url"] = "https://example.com/2"
        c2_path.write_text(json.dumps(c2_data))

        result = extract_startup("test-co", [c1, c2_path], scoring_cfg)
        assert result is not None
        assert result["slug"] == "test-co"
        assert result["source_count"] == 2
        assert "|" in result["source_urls"]

    def test_no_valid_pages(self, tmp_path: Path, scoring_cfg):
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        result = extract_startup("bad-co", [bad], scoring_cfg)
        assert result is None


class TestExtractAll:
    def test_extract_all(self, tmp_path: Path, scoring_cfg):
        c1 = _make_cache(tmp_path, "https://example.com", FIXTURES / "good_page.html")
        collected = {"ocean-clean": [c1]}
        rows = extract_all(collected, scoring_cfg)
        assert len(rows) == 1
        assert rows[0]["slug"] == "ocean-clean"
