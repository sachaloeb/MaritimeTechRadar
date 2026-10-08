"""Tests for scoring: determinism, rings, overrides, validation, D7/D8."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from radar.config import load_scoring_config
from radar.scoring import score_dataframe, score_row


@pytest.fixture
def cfg():
    return load_scoring_config(Path("configs/scoring.yaml"))


def _make_row(**overrides) -> dict:
    base = {
        "slug": "test-co",
        "name": "Test Co",
        "source_urls": "https://example.com",
        "source_fetched_at": "2026-01-15T12:00:00+00:00",
        "source_statuses": "200",
        "source_count": 1,
        "distinct_pages": 1,
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
        "excluded": False,
    }
    base.update(overrides)
    return base


class TestScoreRow:
    def test_determinism(self, cfg):
        row = pd.Series(_make_row())
        assert score_row(row, cfg) == score_row(row, cfg)

    def test_score_range(self, cfg):
        result = score_row(pd.Series(_make_row()), cfg)
        assert 0 <= result["total_score"] <= 100
        for key in result:
            if key.endswith("_score") and key != "total_score":
                assert 0 <= result[key] <= 5

    def test_override_wins(self, cfg):
        row = pd.Series(_make_row(
            maritime_relevance_override=5.0, maritime_relevance_hits=0
        ))
        result = score_row(row, cfg)
        assert result["maritime_relevance_score"] == 5.0
        assert "maritime_relevance" in result["overridden_fields"]

    def test_theme_from_quadrant_hits(self, cfg):
        result = score_row(pd.Series(_make_row()), cfg)
        assert result["theme"] == "decarbonisation_energy"

    def test_theme_tiebreak_alphabetical(self, cfg):
        row = pd.Series(_make_row(
            decarbonisation_energy_hits=5,
            digitalisation_ai_hits=5,
            logistics_operations_hits=5,
            safety_security_hits=5,
        ))
        assert score_row(row, cfg)["theme"] == "decarbonisation_energy"

    def test_theme_override_wins(self, cfg):
        row = pd.Series(_make_row(theme_override="safety_security"))
        result = score_row(row, cfg)
        assert result["theme"] == "safety_security"
        assert "theme" in result["overridden_fields"]

    def test_d7_all_zero_quadrants_gives_unassigned(self, cfg):
        """D7: zero quadrant hits -> theme 'unassigned'."""
        row = pd.Series(_make_row(
            decarbonisation_energy_hits=0,
            digitalisation_ai_hits=0,
            logistics_operations_hits=0,
            safety_security_hits=0,
        ))
        assert score_row(row, cfg)["theme"] == "unassigned"

    def test_d8_invalid_override_raises(self, cfg):
        """D8: bad override value -> ValueError."""
        row = pd.Series(_make_row(maritime_relevance_override="banana"))
        with pytest.raises(ValueError, match="maritime_relevance_override"):
            score_row(row, cfg)

    def test_d8_override_out_of_range(self, cfg):
        row = pd.Series(_make_row(maritime_relevance_override=6.0))
        with pytest.raises(ValueError, match="not in"):
            score_row(row, cfg)

    def test_d8_invalid_theme_override(self, cfg):
        row = pd.Series(_make_row(theme_override="nonexistent"))
        with pytest.raises(ValueError, match="theme_override"):
            score_row(row, cfg)

    # Ring boundary tests
    def test_ring_at_exactly_70(self, cfg):
        # Manually set all overrides to achieve exactly 70
        row = pd.Series(_make_row(
            maritime_relevance_override=3.5,
            theme_fit_override=3.5,
            maturity_signals_override=3.5,
            evidence_quality_override=3.5,
        ))
        result = score_row(row, cfg)
        assert result["total_score"] == 70.0
        assert result["ring"] == "Pilot-ready"

    def test_ring_at_69_99(self, cfg):
        # total = (weighted_sum / 5) * 100
        # For 69.99: weighted_sum = 69.99 * 5 / 100 = 3.4995
        # With equal 0.25 weights and override 3.4995 each:
        # weighted_sum = 4 * 0.25 * 3.4995 = 3.4995 ✓... but rounding
        # Use direct overrides to get just under 70
        row = pd.Series(_make_row(
            maritime_relevance_override=3.499,
            theme_fit_override=3.5,
            maturity_signals_override=3.5,
            evidence_quality_override=3.5,
        ))
        result = score_row(row, cfg)
        assert result["total_score"] < 70
        assert result["ring"] == "Promising"

    def test_ring_at_exactly_50(self, cfg):
        row = pd.Series(_make_row(
            maritime_relevance_override=2.5,
            theme_fit_override=2.5,
            maturity_signals_override=2.5,
            evidence_quality_override=2.5,
        ))
        result = score_row(row, cfg)
        assert result["total_score"] == 50.0
        assert result["ring"] == "Promising"

    def test_ring_at_exactly_30(self, cfg):
        row = pd.Series(_make_row(
            maritime_relevance_override=1.5,
            theme_fit_override=1.5,
            maturity_signals_override=1.5,
            evidence_quality_override=1.5,
        ))
        result = score_row(row, cfg)
        assert result["total_score"] == 30.0
        assert result["ring"] == "Early"

    def test_ring_below_30(self, cfg):
        row = pd.Series(_make_row(
            maritime_relevance_override=1.0,
            theme_fit_override=1.0,
            maturity_signals_override=1.0,
            evidence_quality_override=1.0,
        ))
        result = score_row(row, cfg)
        assert result["total_score"] < 30
        assert result["ring"] == "Watch"

    def test_all_zero_weights_raises(self, cfg):
        row = pd.Series(_make_row())
        weights = {k: 0.0 for k in cfg.criteria}
        with pytest.raises(ValueError, match="zero"):
            score_row(row, cfg, weights=weights)

    def test_missing_hits_column_raises(self, cfg):
        row_data = _make_row()
        del row_data["maritime_relevance_hits"]
        row = pd.Series(row_data)
        with pytest.raises(ValueError, match="maritime_relevance_hits"):
            score_row(row, cfg)


class TestScoreDataframe:
    def test_weight_normalisation(self, cfg):
        df = pd.DataFrame([_make_row()])
        weights = {
            "maritime_relevance": 1, "theme_fit": 1,
            "maturity_signals": 1, "evidence_quality": 1,
        }
        result = score_dataframe(df, cfg, weights=weights)
        assert 0 <= result.iloc[0]["total_score"] <= 100

    def test_stable_ordering(self, cfg):
        rows = [
            _make_row(slug="alpha", maritime_relevance_hits=10),
            _make_row(slug="beta", maritime_relevance_hits=10),
        ]
        r1 = score_dataframe(pd.DataFrame(rows), cfg)
        r2 = score_dataframe(pd.DataFrame(rows), cfg)
        assert list(r1["slug"]) == list(r2["slug"])

    def test_determinism_byte_identical(self, cfg, tmp_path: Path):
        """Two scoring runs produce identical CSV."""
        rows = [
            _make_row(slug="a", maritime_relevance_hits=8),
            _make_row(slug="b", maritime_relevance_hits=3),
        ]
        r1 = score_dataframe(pd.DataFrame(rows), cfg)
        r2 = score_dataframe(pd.DataFrame(rows), cfg)
        p1 = tmp_path / "r1.csv"
        p2 = tmp_path / "r2.csv"
        r1.to_csv(p1, index=False)
        r2.to_csv(p2, index=False)
        assert p1.read_bytes() == p2.read_bytes()

    def test_dataset_kind(self, cfg):
        result = score_dataframe(
            pd.DataFrame([_make_row()]), cfg, dataset_kind="demo"
        )
        assert result.iloc[0]["dataset_kind"] == "demo"

    def test_empty_df(self, cfg):
        assert score_dataframe(pd.DataFrame(), cfg).empty

    def test_unreviewed_rows_included_with_flag(self, cfg):
        """D9: unreviewed rows in output with ring 'Unreviewed'."""
        rows = [
            _make_row(slug="reviewed-co", reviewed=True),
            _make_row(slug="pending-co", reviewed=False),
        ]
        result = score_dataframe(
            pd.DataFrame(rows), cfg, include_unreviewed=True
        )
        assert len(result) == 2
        pending = result[result["slug"] == "pending-co"].iloc[0]
        assert pending["ring"] == "Unreviewed"

    def test_excluded_rows_have_excluded_ring(self, cfg):
        """Excluded rows appear in output with ring='Excluded', no scores."""
        rows = [
            _make_row(slug="good"),
            _make_row(slug="bad", excluded=True, reviewed=True),
        ]
        result = score_dataframe(
            pd.DataFrame(rows), cfg, include_unreviewed=True
        )
        assert "bad" in result["slug"].values
        bad = result[result["slug"] == "bad"].iloc[0]
        assert bad["ring"] == "Excluded"
        assert pd.isna(bad["total_score"])
