"""Tests for review sheet generation and loading."""

from pathlib import Path

import pandas as pd
import pytest

from radar.review import generate_review_sheet, load_review_sheet


def _sample_rows():
    return [
        {
            "slug": "alpha",
            "title": "Alpha Co",
            "maritime_relevance_hits": 5,
            "source_urls": "https://alpha.example.com",
            "fetched_at": "2026-01-15T12:00:00+00:00",
        },
        {
            "slug": "beta",
            "title": "Beta Co",
            "maritime_relevance_hits": 3,
            "source_urls": "https://beta.example.com",
            "fetched_at": "2026-01-15T12:00:00+00:00",
        },
    ]


class TestGenerateReviewSheet:
    def test_creates_file_with_override_columns(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        df = pd.read_csv(out)
        assert len(df) == 2
        assert "reviewed" in df.columns
        assert "maritime_relevance_override" in df.columns
        assert "theme_override" in df.columns
        # Default reviewed should be False
        assert not df["reviewed"].any()


class TestLoadReviewSheet:
    def test_unreviewed_excluded_by_default(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        df = load_review_sheet(out)
        assert len(df) == 0

    def test_reviewed_rows_included(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        # Simulate human review: mark first row as reviewed
        df = pd.read_csv(out)
        df.loc[0, "reviewed"] = "true"
        df.loc[0, "maritime_relevance_override"] = 4
        df.to_csv(out, index=False)

        loaded = load_review_sheet(out)
        assert len(loaded) == 1
        assert loaded.iloc[0]["slug"] == "alpha"
        assert loaded.iloc[0]["maritime_relevance_override"] == 4

    def test_include_unreviewed(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        df = load_review_sheet(out, include_unreviewed=True)
        assert len(df) == 2

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_review_sheet(Path("/nonexistent/review.csv"))

    def test_override_columns_respected(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        df = pd.read_csv(out)
        df.loc[0, "reviewed"] = "true"
        df.loc[0, "theme_override"] = "safety_security"
        df.to_csv(out, index=False)

        loaded = load_review_sheet(out)
        assert loaded.iloc[0]["theme_override"] == "safety_security"
