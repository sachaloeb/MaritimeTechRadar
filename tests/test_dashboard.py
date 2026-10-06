"""Tests for the Streamlit dashboard using streamlit.testing.v1.AppTest."""

from pathlib import Path

import pandas as pd
import pytest


def _demo_radar_df():
    """A minimal scored DataFrame that the dashboard can render."""
    return pd.DataFrame(
        [
            {
                "slug": "demo-alpha",
                "name": "Alpha Marine",
                "source_urls": "https://example.com/alpha",
                "source_fetched_at": "2026-01-15T12:00:00+00:00",
                "source_statuses": "200",
                "source_count": 1,
                "distinct_pages": 1,
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
                "reviewed": True,
                "excluded": False,
                "maritime_relevance_score": 4.0,
                "theme_fit_score": 2.5,
                "maturity_signals_score": 2.5,
                "evidence_quality_score": 2.5,
                "total_score": 58.75,
                "theme": "decarbonisation_energy",
                "ring": "Promising",
                "dataset_kind": "demo",
            },
            {
                "slug": "demo-beta",
                "name": "Beta Logistics",
                "source_urls": "https://example.com/beta",
                "source_fetched_at": "2026-01-15T12:00:00+00:00",
                "source_statuses": "200",
                "source_count": 1,
                "distinct_pages": 1,
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
                "reviewed": True,
                "excluded": False,
                "maritime_relevance_score": 1.5,
                "theme_fit_score": 1.25,
                "maturity_signals_score": 0.83,
                "evidence_quality_score": 1.25,
                "total_score": 24.17,
                "theme": "logistics_operations",
                "ring": "Watch",
                "dataset_kind": "demo",
            },
        ]
    )


@pytest.fixture
def app(tmp_path: Path):
    """Create an AppTest instance with demo radar data written to the real path."""
    from streamlit.testing.v1 import AppTest

    radar_path = Path("data/processed/radar.csv")
    radar_path.parent.mkdir(parents=True, exist_ok=True)
    backup = radar_path.read_text() if radar_path.exists() else None

    try:
        _demo_radar_df().to_csv(radar_path, index=False)
        at = AppTest.from_file("app/dashboard.py", default_timeout=30)
        at.run()
        yield at
    finally:
        if backup is not None:
            radar_path.write_text(backup)
        elif radar_path.exists():
            radar_path.unlink()


class TestDashboard:
    def test_renders_without_error(self, app):
        assert not app.exception, f"Dashboard raised: {app.exception}"

    def test_demo_banner_present(self, app):
        error_blocks = [e.value for e in app.error]
        assert any("SYNTHETIC DEMO DATA" in str(e) for e in error_blocks)

    def test_title_present(self, app):
        titles = [t.value for t in app.title]
        assert any("Maritime Tech Radar" in t for t in titles)
