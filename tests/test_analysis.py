"""Tests for analysis module: markdown tables, RQ1-RQ4, README markers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from radar.analysis import (
    RESULTS_END,
    RESULTS_START,
    SNAPSHOT_END,
    SNAPSHOT_START,
    _average_ranks,
    _df_to_md_table,
    _spearman_rho,
    _update_readme,
    rq1_coverage,
    rq2_review_effect,
    rq3_weight_sensitivity,
)
from radar.config import load_scoring_config


@pytest.fixture
def cfg() -> object:
    return load_scoring_config(Path("configs/scoring.yaml"))


def _scored_df() -> pd.DataFrame:
    """Minimal scored DataFrame with 2 rows for analysis tests."""
    return pd.DataFrame([
        {
            "slug": "alpha",
            "name": "Alpha",
            "maritime_relevance_hits": 8,
            "theme_fit_hits": 4,
            "maturity_signals_hits": 3,
            "evidence_quality_hits": 2,
            "decarbonisation_energy_hits": 6,
            "digitalisation_ai_hits": 2,
            "logistics_operations_hits": 1,
            "safety_security_hits": 0,
            "maritime_relevance_override": "",
            "theme_fit_override": "",
            "maturity_signals_override": "",
            "evidence_quality_override": "",
            "theme_override": "",
            "maritime_relevance_score": 4.0,
            "theme_fit_score": 2.5,
            "maturity_signals_score": 2.5,
            "evidence_quality_score": 1.67,
            "total_score": 55.42,
            "theme": "decarbonisation_energy",
            "ring": "Promising",
            "reviewed": True,
            "excluded": False,
            "overridden_fields": "",
            "source_urls": "https://example.com/a",
            "source_fetched_at": "2026-01-15T12:00:00+00:00",
            "source_statuses": "200",
            "source_count": 1,
        },
        {
            "slug": "beta",
            "name": "Beta",
            "maritime_relevance_hits": 3,
            "theme_fit_hits": 2,
            "maturity_signals_hits": 1,
            "evidence_quality_hits": 1,
            "decarbonisation_energy_hits": 1,
            "digitalisation_ai_hits": 1,
            "logistics_operations_hits": 5,
            "safety_security_hits": 0,
            "maritime_relevance_override": "",
            "theme_fit_override": "",
            "maturity_signals_override": "",
            "evidence_quality_override": "",
            "theme_override": "",
            "maritime_relevance_score": 1.5,
            "theme_fit_score": 1.25,
            "maturity_signals_score": 0.83,
            "evidence_quality_score": 0.83,
            "total_score": 22.29,
            "theme": "logistics_operations",
            "ring": "Watch",
            "reviewed": True,
            "excluded": False,
            "overridden_fields": "",
            "source_urls": "https://example.com/b",
            "source_fetched_at": "2026-01-15T12:00:00+00:00",
            "source_statuses": "200",
            "source_count": 1,
        },
    ])


# ── _df_to_md_table ─────────────────────────────────────────────────────────


class TestDfToMdTable:
    def test_empty_df(self):
        assert _df_to_md_table(pd.DataFrame()) == "(no data)\n"

    def test_single_row(self):
        df = pd.DataFrame([{"a": 1, "b": "x"}])
        result = _df_to_md_table(df)
        assert "| a | b |" in result
        assert "| --- | --- |" in result
        assert "| 1 | x |" in result

    def test_na_rendered_as_empty(self):
        df = pd.DataFrame([{"a": pd.NA, "b": None}])
        result = _df_to_md_table(df)
        assert "|  |  |" in result

    def test_multiple_rows(self):
        df = pd.DataFrame([{"x": 1}, {"x": 2}, {"x": 3}])
        lines = _df_to_md_table(df).strip().split("\n")
        assert len(lines) == 5  # header + sep + 3 data rows


# ── Utility functions ────────────────────────────────────────────────────────


class TestSpearmanRho:
    def test_perfect_correlation(self):
        result = _spearman_rho([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        assert result == "1.0000"

    def test_too_few_values(self):
        assert _spearman_rho([1.0, 2.0], [2.0, 1.0]) == "n/a"

    def test_zero_std_gives_na(self):
        assert _spearman_rho([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) == "n/a"


class TestAverageRanks:
    def test_distinct_scores(self):
        ranks = _average_ranks([100.0, 50.0, 75.0])
        # 100 -> rank 1, 75 -> rank 2, 50 -> rank 3
        assert ranks == [1.0, 3.0, 2.0]

    def test_tied_scores(self):
        ranks = _average_ranks([50.0, 50.0, 100.0])
        # 100 -> rank 1, 50 tied -> avg of 2,3 = 2.5
        assert ranks == [2.5, 2.5, 1.0]


# ── RQ1: Coverage ────────────────────────────────────────────────────────────


class TestRQ1:
    def test_returns_rows_for_all_criteria_plus_theme(self, cfg):
        df = _scored_df()
        result = rq1_coverage(df, cfg)
        assert len(result) == len(cfg.criteria) + 1  # +1 for theme
        assert "theme" in result["criterion"].values

    def test_no_overrides_means_zero_share(self, cfg):
        df = _scored_df()
        result = rq1_coverage(df, cfg)
        for _, row in result.iterrows():
            assert row["share_overridden"] == 0

    def test_with_override_increases_share(self, cfg):
        df = _scored_df()
        df.loc[0, "maritime_relevance_override"] = 5.0
        result = rq1_coverage(df, cfg)
        mr_row = result[result["criterion"] == "maritime_relevance"].iloc[0]
        assert mr_row["share_overridden"] == 0.5  # 1 of 2

    def test_auto_score_close_to_final_when_no_overrides(self, cfg):
        """Without overrides, auto and final scores should be very close.

        Small rounding diffs are expected because _scored_df() uses
        hand-entered values while rq1 re-computes from hits/saturation.
        """
        df = _scored_df()
        result = rq1_coverage(df, cfg)
        for _, row in result.iterrows():
            if row["criterion"] != "theme":
                assert abs(row["mean_auto_score"] - row["mean_reviewed_score"]) < 0.05

    def test_empty_scored_returns_empty(self, cfg):
        df = _scored_df()
        df["ring"] = "Unreviewed"
        assert rq1_coverage(df, cfg).empty


# ── RQ2: Review effect ──────────────────────────────────────────────────────


class TestRQ2:
    def test_no_overrides_close_scores(self, cfg):
        """Without overrides, auto and reviewed scores should be very close.

        Small rounding diffs are expected because _scored_df() uses
        hand-entered values while rq2 re-computes from hits/saturation.
        """
        df = _scored_df()
        result = rq2_review_effect(df, cfg)
        assert len(result) == 2
        for _, row in result.iterrows():
            assert abs(row["auto_score"] - row["reviewed_score"]) < 1.0
            assert not row["ring_changed"]

    def test_has_rank_columns(self, cfg):
        df = _scored_df()
        result = rq2_review_effect(df, cfg)
        assert "auto_rank" in result.columns
        assert "reviewed_rank" in result.columns
        assert "rank_change" in result.columns
        assert "spearman_rho" in result.columns

    def test_empty_scored_returns_empty(self, cfg):
        df = _scored_df()
        df["ring"] = "Excluded"
        assert rq2_review_effect(df, cfg).empty


# ── RQ3: Weight sensitivity ─────────────────────────────────────────────────


class TestRQ3:
    def test_has_summary_row(self, cfg):
        df = _scored_df()
        result = rq3_weight_sensitivity(df, cfg)
        assert not result.empty
        assert "SUMMARY" in result["criterion"].values

    def test_produces_rows_for_each_criterion_and_delta(self, cfg):
        df = _scored_df()
        result = rq3_weight_sensitivity(df, cfg)
        # Each criterion gets 2 deltas (-0.10, +0.10) + 1 summary
        n_criteria = len(cfg.criteria)
        assert len(result) == n_criteria * 2 + 1

    def test_columns_present(self, cfg):
        df = _scored_df()
        result = rq3_weight_sensitivity(df, cfg)
        expected_cols = {
            "criterion", "delta", "new_weight", "clipped",
            "rank_changes", "max_rank_shift", "ring_changes",
            "spearman_vs_baseline",
        }
        assert expected_cols.issubset(set(result.columns))

    def test_empty_scored_returns_empty(self, cfg):
        df = _scored_df()
        df["ring"] = "Unreviewed"
        assert rq3_weight_sensitivity(df, cfg).empty


# ── README markers ───────────────────────────────────────────────────────────


class TestUpdateReadme:
    def test_missing_markers_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        readme = tmp_path / "README.md"
        readme.write_text("# Hello\nNo markers here.\n")
        with pytest.raises(ValueError, match="missing result markers"):
            _update_readme("results text", 2, "2026-01-15", False)

    def test_updates_between_markers(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        readme = tmp_path / "README.md"
        readme.write_text(
            f"# Radar\n\n{RESULTS_START}\nold results\n{RESULTS_END}\n"
            f"\n{SNAPSHOT_START} old snap {SNAPSHOT_END}\n"
        )
        _update_readme("new results", 5, "2026-06-01", False)
        content = readme.read_text()
        assert "new results" in content
        assert "old results" not in content
        assert "n=5" in content
        assert "2026-06-01" in content

    def test_missing_readme_skips(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Should not raise — just logs a warning
        _update_readme("results", 2, "2026-01-15", False)


# ── Marker constants ────────────────────────────────────────────────────────


class TestMarkerConstants:
    def test_markers_are_html_comments(self):
        assert RESULTS_START.startswith("<!--")
        assert RESULTS_END.startswith("<!--")
        assert SNAPSHOT_START.startswith("<!--")
        assert SNAPSHOT_END.startswith("<!--")

    def test_start_end_differ(self):
        assert RESULTS_START != RESULTS_END
        assert SNAPSHOT_START != SNAPSHOT_END
