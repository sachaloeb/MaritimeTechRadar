"""End-to-end tests for the CLI, exercising main(argv) in tmp directories."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from radar.cli import __version__, main, validate_state


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a tmp environment with configs/ and tests/fixtures/ for demo mode."""
    monkeypatch.chdir(tmp_path)
    # Copy configs
    src_configs = Path(__file__).resolve().parent.parent / "configs"
    shutil.copytree(src_configs, tmp_path / "configs")
    # Copy fixtures
    src_fixtures = Path(__file__).resolve().parent / "fixtures"
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    for f in src_fixtures.iterdir():
        shutil.copy2(f, tmp_path / "tests" / "fixtures" / f.name)
    # Create logs dir so logging_setup doesn't touch the real one
    (tmp_path / "logs").mkdir()
    return tmp_path


class TestVersion:
    def test_version_string(self):
        assert __version__ == "0.1.0"

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit, match="0"):
            main(["--version"])
        assert __version__ in capsys.readouterr().out


class TestDemoRun:
    def test_demo_run_creates_review_sheet(self, cli_env: Path):
        main(["run", "--demo"])
        review = cli_env / "data" / "demo" / "review" / "review_sheet.csv"
        assert review.exists()
        df = pd.read_csv(review)
        assert len(df) >= 2  # at least good_page + malformed_page

    def test_demo_run_then_score(self, cli_env: Path):
        main(["run", "--demo"])
        main(["score", "--demo"])
        radar = cli_env / "data" / "demo" / "processed" / "radar.csv"
        assert radar.exists()
        df = pd.read_csv(radar)
        assert "ring" in df.columns
        assert "total_score" in df.columns

    def test_zero_page_row_in_demo(self, cli_env: Path):
        """Zero-page start-ups get a placeholder row in the review sheet."""
        main(["run", "--demo"])
        review = cli_env / "data" / "demo" / "review" / "review_sheet.csv"
        df = pd.read_csv(review)
        # All slugs should be present even if source_count=0
        for _, row in df.iterrows():
            assert "slug" in row.index
            assert pd.notna(row["slug"])


class TestValidate:
    def test_validate_no_review_sheet_warns(self, cli_env: Path):
        errors, warnings = validate_state(demo=True)
        assert any("not found" in w for w in warnings)

    def test_validate_excluded_without_reason(self, cli_env: Path):
        main(["run", "--demo"])
        review = cli_env / "data" / "demo" / "review" / "review_sheet.csv"
        df = pd.read_csv(review)
        df["reviewed"] = df["reviewed"].astype(str)
        df["excluded"] = df["excluded"].astype(str)
        df["exclusion_reason"] = df["exclusion_reason"].astype(str)
        df.loc[0, "reviewed"] = "true"
        df.loc[0, "excluded"] = "true"
        df.loc[0, "exclusion_reason"] = ""
        df.to_csv(review, index=False)
        errors, _ = validate_state(demo=True)
        assert any("exclusion_reason" in e for e in errors)

    def test_validate_invalid_override(self, cli_env: Path):
        main(["run", "--demo"])
        review = cli_env / "data" / "demo" / "review" / "review_sheet.csv"
        df = pd.read_csv(review)
        df["reviewed"] = "true"
        df.loc[0, "maritime_relevance_override"] = 99.0
        df.to_csv(review, index=False)
        errors, _ = validate_state(demo=True)
        assert any("not in [0, 5]" in e for e in errors)

    def test_validate_bad_theme_override(self, cli_env: Path):
        main(["run", "--demo"])
        review = cli_env / "data" / "demo" / "review" / "review_sheet.csv"
        df = pd.read_csv(review)
        df["reviewed"] = "true"
        df["theme_override"] = df["theme_override"].astype(str)
        df.loc[0, "theme_override"] = "nonexistent_theme"
        df.to_csv(review, index=False)
        errors, _ = validate_state(demo=True)
        assert any("theme_override" in e for e in errors)

    def test_score_refuses_on_validation_error(self, cli_env: Path):
        main(["run", "--demo"])
        review = cli_env / "data" / "demo" / "review" / "review_sheet.csv"
        df = pd.read_csv(review)
        df["reviewed"] = "true"
        df["excluded"] = df["excluded"].astype(str)
        df["exclusion_reason"] = df["exclusion_reason"].astype(str)
        df.loc[0, "excluded"] = "true"
        df.loc[0, "exclusion_reason"] = ""
        df.to_csv(review, index=False)
        with pytest.raises(SystemExit):
            main(["score", "--demo"])


class TestStatus:
    def test_status_runs(self, cli_env: Path, capsys: pytest.CaptureFixture[str]):
        main(["run", "--demo"])
        main(["status", "--demo"])
        out = capsys.readouterr().out
        assert "Slug" in out
        assert "Total:" in out


class TestAnalyse:
    def test_analyse_demo(self, cli_env: Path):
        main(["run", "--demo"])
        main(["score", "--demo"])
        main(["analyse", "--demo"])
        reports = cli_env / "reports" / "demo"
        assert reports.exists()
        assert (reports / "results.md").exists()
        assert (reports / "rq1_coverage.csv").exists()
