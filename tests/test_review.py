"""Tests for review sheet generation, merge, and loading."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from radar.review import generate_review_sheet, load_review_sheet


def _sample_rows() -> list[dict]:
    return [
        {"slug": "alpha", "name": "Alpha Co",
         "maritime_relevance_hits": 5,
         "source_urls": "https://alpha.example.com",
         "source_fetched_at": "2026-01-15T12:00:00+00:00",
         "source_statuses": "200"},
        {"slug": "beta", "name": "Beta Co",
         "maritime_relevance_hits": 3,
         "source_urls": "https://beta.example.com",
         "source_fetched_at": "2026-01-15T12:00:00+00:00",
         "source_statuses": "200"},
    ]


class TestGenerateReviewSheet:
    def test_creates_file_with_override_columns(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        df = pd.read_csv(out)
        assert len(df) == 2
        assert "reviewed" in df.columns
        assert "excluded" in df.columns
        assert "exclusion_reason" in df.columns
        assert "review_minutes" in df.columns
        assert "maritime_relevance_override" in df.columns

    def test_merge_preserves_human_edits(self, tmp_path: Path):
        """D4 regression: re-running must not destroy human edits."""
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        # Simulate human review — use explicit str/float dtypes to avoid
        # FutureWarning about incompatible dtype assignment
        df = pd.read_csv(out)
        df["notes"] = df["notes"].astype(str)
        df["reviewed"] = df["reviewed"].astype(str)
        df.loc[df["slug"] == "alpha", "reviewed"] = "true"
        df.loc[df["slug"] == "alpha", "maritime_relevance_override"] = 4.0
        df.loc[df["slug"] == "alpha", "notes"] = "Looks good"
        df.to_csv(out, index=False)

        # Re-generate (merge, not overwrite)
        generate_review_sheet(_sample_rows(), output_path=out)

        reloaded = pd.read_csv(out)
        alpha = reloaded[reloaded["slug"] == "alpha"].iloc[0]
        assert str(alpha["reviewed"]).lower() == "true"
        assert float(alpha["maritime_relevance_override"]) == 4.0
        assert alpha["notes"] == "Looks good"

    def test_merge_adds_new_slugs(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        new_rows = _sample_rows() + [
            {"slug": "gamma", "name": "Gamma Co",
             "maritime_relevance_hits": 1,
             "source_urls": "https://gamma.example.com",
             "source_fetched_at": "2026-01-15",
             "source_statuses": "200"},
        ]
        generate_review_sheet(new_rows, output_path=out)

        df = pd.read_csv(out)
        assert len(df) == 3

    def test_force_new_starts_fresh_with_backup(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        # Mark reviewed
        df = pd.read_csv(out)
        df.loc[0, "reviewed"] = True
        df.to_csv(out, index=False)

        # Force new
        generate_review_sheet(
            _sample_rows(), output_path=out, force_new=True
        )

        df = pd.read_csv(out)
        # All reviewed should be reset
        assert not any(
            str(v).lower() == "true" for v in df["reviewed"]
        )

        # Backup should exist
        backup_dir = out.parent / "backups"
        assert backup_dir.exists()
        assert len(list(backup_dir.glob("*.csv"))) >= 1


class TestLoadReviewSheet:
    def test_unreviewed_excluded_by_default(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)
        df = load_review_sheet(out)
        assert len(df) == 0

    def test_reviewed_rows_included(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        df = pd.read_csv(out)
        df["reviewed"] = df["reviewed"].astype(str)
        df.loc[0, "reviewed"] = "true"
        df.to_csv(out, index=False)

        loaded = load_review_sheet(out)
        assert len(loaded) == 1

    def test_excluded_rows_filtered(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)

        df = pd.read_csv(out)
        df["reviewed"] = df["reviewed"].astype(str)
        df["excluded"] = df["excluded"].astype(str)
        df["exclusion_reason"] = df["exclusion_reason"].astype(str)
        df.loc[0, "reviewed"] = "true"
        df.loc[0, "excluded"] = "true"
        df.loc[0, "exclusion_reason"] = "test reason"
        df.to_csv(out, index=False)

        loaded = load_review_sheet(out)
        assert len(loaded) == 0

    def test_include_unreviewed(self, tmp_path: Path):
        out = tmp_path / "review.csv"
        generate_review_sheet(_sample_rows(), output_path=out)
        df = load_review_sheet(out, include_unreviewed=True)
        assert len(df) == 2

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_review_sheet(Path("/nonexistent/review.csv"))
