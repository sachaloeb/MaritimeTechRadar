"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from radar.config import load_scoring_config, load_startups_config


@pytest.fixture
def tmp_yaml(tmp_path: Path):
    def _write(data: dict, name: str = "test.yaml") -> Path:
        p = tmp_path / name
        p.write_text(yaml.dump(data), encoding="utf-8")
        return p
    return _write


class TestStartupsConfig:
    def test_valid_config(self, tmp_yaml):
        data = {"startups": [
            {"name": "AcmeMarine", "slug": "acme-marine",
             "urls": ["https://example.com"]},
        ]}
        cfg = load_startups_config(tmp_yaml(data))
        assert len(cfg.startups) == 1
        assert cfg.startups[0].slug == "acme-marine"

    def test_empty_seed_list(self, tmp_yaml):
        cfg = load_startups_config(tmp_yaml({"startups": []}))
        assert cfg.startups == []

    def test_missing_urls_raises(self, tmp_yaml):
        with pytest.raises(Exception):
            load_startups_config(tmp_yaml(
                {"startups": [{"name": "Bad", "slug": "bad", "urls": []}]}
            ))

    def test_bad_slug_raises(self, tmp_yaml):
        with pytest.raises(Exception):
            load_startups_config(tmp_yaml(
                {"startups": [{"name": "Bad", "slug": "Bad Slug!",
                               "urls": ["https://example.com"]}]}
            ))

    def test_pipe_in_url_raises(self, tmp_yaml):
        """D4 regression: pipe char is the list delimiter."""
        with pytest.raises(Exception, match="pipe"):
            load_startups_config(tmp_yaml(
                {"startups": [{"name": "X", "slug": "x",
                               "urls": ["https://a.com|b.com"]}]}
            ))


class TestScoringConfig:
    def test_valid_scoring(self):
        cfg = load_scoring_config(Path("configs/scoring.yaml"))
        assert abs(sum(c.weight for c in cfg.criteria.values()) - 1.0) < 0.001
        assert len(cfg.quadrants) == 4

    def test_derived_from_field(self):
        cfg = load_scoring_config(Path("configs/scoring.yaml"))
        assert cfg.criteria["theme_fit"].derived_from == "best_quadrant"

    def test_bad_weights_raise(self, tmp_yaml):
        data = {
            "criteria": {
                "a": {"weight": 0.5, "saturation": 5, "keywords": ["x"]},
                "b": {"weight": 0.3, "saturation": 5, "keywords": ["y"]},
            },
            "quadrants": {"q1": {"label": "Q1", "keywords": ["k"]}},
        }
        with pytest.raises(Exception, match="weights must sum to 1.0"):
            load_scoring_config(tmp_yaml(data))

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_scoring_config(Path("/nonexistent/scoring.yaml"))

    def test_d10_no_multiline_fstring(self):
        """D10 regression: config.py must parse on Python 3.11."""
        import py_compile
        py_compile.compile("src/radar/config.py", doraise=True)
