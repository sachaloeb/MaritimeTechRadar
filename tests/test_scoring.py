"""Tests for the scorer: determinism, weights, rings, overrides, theme tie-break."""

from pathlib import Path

import pandas as pd
import pytest

from radar.config import load_scoring_config
from radar.scoring import score_dataframe, score_row


@pytest.fixture
def cfg():
    return load_scoring_config(Path("configs/scoring.yaml"))


def _make_row(**overrides):
    """Build a minimal row dict suitable for scoring."""
    base = {
        "slug": "test-co",
        "title": "Test Co",
        "source_urls": "https://example.com",
        "fetched_at": "2026-01-15T12:00:00+00:00",
        "source_count": 1,
        "maritime_relevance_hits": 5,
        "theme_fit_hits": 4,
        "maturity_signals_hits": 3,
        "evidence_quality_hits": 2,
        "decarbonisation_energy_hits": 6,
        "digitalisation_ai_hits": 3,
        "logistics_operations_hits": 2,
        "safety_security_hits": 1,
        "maritime_relevance_override": "",
        "theme_fit_override": "",
        "maturity_signals_override": "",
        "evidence_quality_override": "",
        "theme_override": "",
        "reviewed": True,
    }
    base.update(overrides)
    return base


class TestScoreRow:
    def test_determinism(self, cfg):
        row = pd.Series(_make_row())
        r1 = score_row(row, cfg)
        r2 = score_row(row, cfg)
        assert r1 == r2

    def test_score_range(self, cfg):
        row = pd.Series(_make_row())
        result = score_row(row, cfg)
        assert 0 <= result["total_score"] <= 100
        for key in result:
            if key.endswith("_score") and key != "total_score":
                assert 0 <= result[key] <= 5

    def test_override_wins(self, cfg):
        row = pd.Series(_make_row(maritime_relevance_override=5.0, maritime_relevance_hits=0))
        result = score_row(row, cfg)
        assert result["maritime_relevance_score"] == 5.0

    def test_theme_from_quadrant_hits(self, cfg):
        row = pd.Series(_make_row())
        result = score_row(row, cfg)
        assert result["theme"] == "decarbonisation_energy"  # highest hits

    def test_theme_tiebreak_alphabetical(self, cfg):
        row = pd.Series(
            _make_row(
                decarbonisation_energy_hits=5,
                digitalisation_ai_hits=5,
                logistics_operations_hits=5,
                safety_security_hits=5,
            )
        )
        result = score_row(row, cfg)
        assert result["theme"] == "decarbonisation_energy"  # alphabetically first

    def test_theme_override_wins(self, cfg):
        row = pd.Series(_make_row(theme_override="safety_security"))
        result = score_row(row, cfg)
        assert result["theme"] == "safety_security"

    def test_ring_pilot_ready(self, cfg):
        row = pd.Series(
            _make_row(
                maritime_relevance_hits=20,
                theme_fit_hits=20,
                maturity_signals_hits=20,
                evidence_quality_hits=20,
            )
        )
        result = score_row(row, cfg)
        assert result["ring"] == "Pilot-ready"

    def test_ring_watch(self, cfg):
        row = pd.Series(
            _make_row(
                maritime_relevance_hits=0,
                theme_fit_hits=0,
                maturity_signals_hits=0,
                evidence_quality_hits=0,
            )
        )
        result = score_row(row, cfg)
        assert result["ring"] == "Watch"


class TestScoreDataframe:
    def test_weight_normalisation(self, cfg):
        """Custom weights that don't sum to 1 should still work (normalised internally)."""
        df = pd.DataFrame([_make_row()])
        weights = {
            "maritime_relevance": 1, "theme_fit": 1,
            "maturity_signals": 1, "evidence_quality": 1,
        }
        result = score_dataframe(df, cfg, weights=weights)
        assert len(result) == 1
        assert 0 <= result.iloc[0]["total_score"] <= 100

    def test_stable_ordering(self, cfg):
        rows = [
            _make_row(slug="alpha", maritime_relevance_hits=10),
            _make_row(slug="beta", maritime_relevance_hits=10),
            _make_row(slug="gamma", maritime_relevance_hits=1),
        ]
        df = pd.DataFrame(rows)
        r1 = score_dataframe(df, cfg)
        r2 = score_dataframe(df, cfg)
        assert list(r1["slug"]) == list(r2["slug"])

    def test_dataset_kind(self, cfg):
        df = pd.DataFrame([_make_row()])
        result = score_dataframe(df, cfg, dataset_kind="demo")
        assert result.iloc[0]["dataset_kind"] == "demo"

    def test_empty_df(self, cfg):
        df = pd.DataFrame()
        result = score_dataframe(df, cfg)
        assert result.empty
