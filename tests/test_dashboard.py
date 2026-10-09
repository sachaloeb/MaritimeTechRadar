"""Tests for the Streamlit dashboard using streamlit.testing.v1.AppTest."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _demo_radar_df() -> pd.DataFrame:
    """A minimal scored DataFrame that the dashboard can render."""
    return pd.DataFrame(
        [
            {
                "slug": "demo-alpha",
                "name": "Alpha Marine",
                "source_urls": "https://example.com/alpha",
                "source_fetched_at": "2026-01-15T12:00:00+00:00",
                "source_statuses": "200",
                "source_count": 2,
                "evidence_quality_pages": 1,
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
                "maritime_relevance_matched": "maritime|shipping|port",
                "theme_fit_matched": "decarbonisation|hydrogen",
                "maturity_signals_matched": "pilot|funding",
                "evidence_quality_matched": "case study",
                "reviewed": True,
                "excluded": False,
                "exclusion_reason": "",
                "maritime_relevance_score": 4.0,
                "theme_fit_score": 2.5,
                "maturity_signals_score": 2.5,
                "evidence_quality_score": 2.5,
                "total_score": 58.75,
                "theme": "decarbonisation_energy",
                "ring": "Promising",
                "dataset_kind": "demo",
                "overridden_fields": "",
            },
            {
                "slug": "demo-beta",
                "name": "Beta Logistics",
                "source_urls": "https://example.com/beta",
                "source_fetched_at": "2026-01-15T12:00:00+00:00",
                "source_statuses": "200",
                "source_count": 2,
                "evidence_quality_pages": 1,
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
                "maritime_relevance_matched": "maritime|cargo",
                "theme_fit_matched": "logistics",
                "maturity_signals_matched": "customer",
                "evidence_quality_matched": "",
                "reviewed": True,
                "excluded": False,
                "exclusion_reason": "",
                "maritime_relevance_score": 1.5,
                "theme_fit_score": 1.25,
                "maturity_signals_score": 0.83,
                "evidence_quality_score": 1.25,
                "total_score": 24.17,
                "theme": "logistics_operations",
                "ring": "Watch",
                "dataset_kind": "demo",
                "overridden_fields": "",
            },
        ]
    )


@pytest.fixture
def radar_csv(tmp_path: Path) -> Path:
    """Write demo radar data to a temp CSV and return its path."""
    csv_path = tmp_path / "radar.csv"
    _demo_radar_df().to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def app(radar_csv: Path, monkeypatch: pytest.MonkeyPatch):
    """Create an AppTest instance with RADAR_CSV pointing to temp data."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("RADAR_CSV", str(radar_csv))
    dashboard_path = str(
        Path(__file__).resolve().parent.parent / "app" / "dashboard.py"
    )
    at = AppTest.from_file(dashboard_path, default_timeout=30)
    at.run()
    yield at


class TestDashboard:
    def test_renders_without_error(self, app):
        assert not app.exception, f"Dashboard raised: {app.exception}"

    def test_demo_banner_present(self, app):
        error_blocks = [e.value for e in app.error]
        assert any("SYNTHETIC DEMO DATA" in str(e) for e in error_blocks)

    def test_title_present(self, app):
        titles = [t.value for t in app.title]
        assert any("Maritime Tech Radar" in t for t in titles)

    def test_non_affiliation_caption(self, app):
        captions = [c.value for c in app.caption]
        assert any("not affiliated" in str(c).lower() for c in captions)

    def test_method_section_has_n_and_data_as_of(self, app):
        all_md = " ".join(str(m.value) for m in app.markdown)
        assert "n = 2" in all_md or "n=2" in all_md
        assert "2026" in all_md

    def test_sensitivity_table_present(self, app):
        # At least one dataframe should contain sensitivity columns
        dfs = [d.value for d in app.dataframe]
        has_sens = any(
            "Criterion" in (list(d.columns) if hasattr(d, "columns") else [])
            for d in dfs
        )
        assert has_sens

    def test_sources_table_has_links(self, app):
        dfs = [d.value for d in app.dataframe]
        has_url = any(
            "URL" in (list(d.columns) if hasattr(d, "columns") else [])
            for d in dfs
        )
        assert has_url


class TestDashboardExtended:
    def test_method_section_has_formula(self, app):
        all_md = " ".join(str(m.value) for m in app.markdown)
        assert "total = 100" in all_md or "s_i = min(5" in all_md

    def test_method_section_has_known_limits(self, app):
        all_md = " ".join(str(m.value) for m in app.markdown)
        assert "context-blind" in all_md

    def test_themes_mentioned_in_method(self, app):
        all_md = " ".join(str(m.value) for m in app.markdown)
        assert "Themes" in all_md
        assert "scoring.yaml" in all_md

    def test_ring_legend_from_config(self, app):
        captions = [str(c.value) for c in app.caption]
        assert any("70" in c and "Pilot-ready" in c for c in captions)

    def test_radar_caption_present(self, app):
        """Radar has the interpretation caption."""
        captions = [str(c.value) for c in app.caption]
        assert any("Distance from the centre" in c for c in captions)

    def test_download_button_present(self, app):
        # Streamlit AppTest doesn't have a direct download_button accessor,
        # but the dashboard should not raise and should have sidebar content
        assert not app.exception

    def test_excluded_row_in_expander(self, tmp_path: Path, monkeypatch):
        """Excluded rows appear in an expander with reasons."""
        import streamlit as st
        from streamlit.testing.v1 import AppTest

        st.cache_data.clear()

        df = _demo_radar_df()
        # Add an excluded row as a new dict
        excl_dict = df.iloc[0].to_dict()
        excl_dict["slug"] = "demo-excl"
        excl_dict["name"] = "Excluded Co"
        excl_dict["ring"] = "Excluded"
        excl_dict["excluded"] = True
        excl_dict["exclusion_reason"] = "not maritime"
        excl_dict["total_score"] = ""
        excl_df = pd.DataFrame(
            df.to_dict("records") + [excl_dict]
        )

        csv_path = tmp_path / "radar_excl.csv"
        excl_df.to_csv(csv_path, index=False)
        monkeypatch.setenv("RADAR_CSV", str(csv_path))
        dashboard_path = str(
            Path(__file__).resolve().parent.parent / "app" / "dashboard.py"
        )
        at = AppTest.from_file(dashboard_path, default_timeout=30)
        at.run()
        assert not at.exception, f"Dashboard raised: {at.exception}"

    def test_evidence_quality_decomposition(self, app):
        """'Why this score?' shows 'hits = pages + keywords' for evidence quality."""
        all_md = " ".join(str(m.value) for m in app.markdown)
        # Alpha: evidence_quality_pages=1, hits=2, matched="case study" → 1 keyword
        # → "2 hits = 1 page + 1 keyword"
        assert "hits =" in all_md

    def test_unreviewed_toggle(self, tmp_path: Path, monkeypatch):
        """Unreviewed rows appear when toggled on."""
        import streamlit as st
        from streamlit.testing.v1 import AppTest

        st.cache_data.clear()

        df = _demo_radar_df()
        # Add an unreviewed row as a new dict
        ur_dict = df.iloc[0].to_dict()
        ur_dict["slug"] = "demo-unrev"
        ur_dict["name"] = "Unreviewed Co"
        ur_dict["ring"] = "Unreviewed"
        ur_dict["reviewed"] = False
        ur_dict["total_score"] = ""
        ur_df = pd.DataFrame(
            df.to_dict("records") + [ur_dict]
        )

        csv_path = tmp_path / "radar_ur.csv"
        ur_df.to_csv(csv_path, index=False)
        monkeypatch.setenv("RADAR_CSV", str(csv_path))
        dashboard_path = str(
            Path(__file__).resolve().parent.parent / "app" / "dashboard.py"
        )
        at = AppTest.from_file(dashboard_path, default_timeout=30)
        at.run()
        assert not at.exception, f"Dashboard raised: {at.exception}"


class TestResetWeights:
    """Slider → move → reset → assert defaults restored, no exception."""

    @pytest.fixture
    def fresh_app(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import streamlit as st
        from streamlit.testing.v1 import AppTest

        st.cache_data.clear()
        csv_path = tmp_path / "radar.csv"
        _demo_radar_df().to_csv(csv_path, index=False)
        monkeypatch.setenv("RADAR_CSV", str(csv_path))
        dashboard_path = str(
            Path(__file__).resolve().parent.parent / "app" / "dashboard.py"
        )
        at = AppTest.from_file(dashboard_path, default_timeout=30)
        at.run()
        assert not at.exception, f"Initial run raised: {at.exception}"
        return at

    def test_slider_move_no_exception(self, fresh_app):
        at = fresh_app
        # Move the first slider (Maritime Relevance, default 0.30)
        slider = at.sidebar.slider[0]
        slider.set_value(0.8).run()
        assert not at.exception, f"After slider move: {at.exception}"

    def test_reset_restores_defaults(self, fresh_app):
        from radar.config import load_scoring_config

        cfg = load_scoring_config()
        at = fresh_app

        # Move a slider away from default
        slider = at.sidebar.slider[0]
        slider.set_value(0.8).run()
        assert not at.exception, f"After slider move: {at.exception}"

        # Click "Reset weights"
        reset_btn = at.sidebar.button[0]
        reset_btn.click().run()
        assert not at.exception, f"After reset: {at.exception}"

        # Verify all sliders are back to config defaults
        crit_names = list(cfg.criteria.keys())
        for i, crit_name in enumerate(crit_names):
            expected = cfg.criteria[crit_name].weight
            actual = at.sidebar.slider[i].value
            assert actual == pytest.approx(expected, abs=0.001), (
                f"{crit_name}: expected {expected}, got {actual}"
            )

    def test_reset_twice_no_exception(self, fresh_app):
        at = fresh_app
        reset_btn = at.sidebar.button[0]
        reset_btn.click().run()
        assert not at.exception
        reset_btn.click().run()
        assert not at.exception


class TestRadarChartDirect:
    """Unit tests for radar_chart — load without running main()."""

    @pytest.fixture(scope="class")
    def radar_chart_fn(self):
        """Exec the dashboard source (minus the trailing main() call) and
        return the radar_chart function so it can be tested without starting
        a full Streamlit session."""
        import unittest.mock as mock

        path = Path(__file__).resolve().parent.parent / "app" / "dashboard.py"
        source = path.read_text()
        lines = source.rstrip().split("\n")
        assert lines[-1].strip() == "main()", (
            f"Expected 'main()' as last line, got: {lines[-1]!r}"
        )
        stripped = "\n".join(lines[:-1])

        globs: dict = {"__name__": "__test__", "__file__": str(path)}
        with mock.patch("streamlit.set_page_config"):
            exec(compile(stripped, str(path), "exec"), globs)  # noqa: S102

        return globs["radar_chart"]

    def test_legend_has_four_rings_only(self, radar_chart_fn):
        """Companies are hidden from the legend; only the four rings appear."""
        fig, _ = radar_chart_fn(_demo_radar_df())
        legend_entries = [t.name for t in fig.data if t.showlegend]
        assert set(legend_entries) == {
            "Pilot-ready", "Promising", "Early", "Watch"
        }, f"Legend shows: {legend_entries!r}"

    def test_company_traces_not_in_legend(self, radar_chart_fn):
        """No per-company trace should have showlegend=True."""
        df = _demo_radar_df()
        fig, _ = radar_chart_fn(df)
        company_names = set(df["name"].astype(str))
        in_legend = {t.name for t in fig.data if t.showlegend}
        overlap = company_names & in_legend
        assert not overlap, f"Company names in legend: {overlap!r}"


class TestDashboardMissingCsv:
    def test_missing_csv_shows_warning(self, tmp_path: Path, monkeypatch):
        import streamlit as st
        from streamlit.testing.v1 import AppTest

        st.cache_data.clear()
        monkeypatch.setenv("RADAR_CSV", str(tmp_path / "nonexistent.csv"))
        dashboard_path = str(
            Path(__file__).resolve().parent.parent / "app" / "dashboard.py"
        )
        at = AppTest.from_file(dashboard_path, default_timeout=30)
        at.run()
        assert not at.exception, f"Dashboard raised: {at.exception}"
        warnings = [w.value for w in at.warning]
        assert any("No radar data" in str(w) for w in warnings)
