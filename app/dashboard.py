"""Single-page Streamlit dashboard for the Maritime Tech Radar."""

import hashlib
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from radar.config import load_scoring_config

st.set_page_config(page_title="Maritime Tech Radar", layout="wide")

RADAR_FILE = Path("data/processed/radar.csv")
SCORING_CFG = load_scoring_config()

RING_ORDER = ["Pilot-ready", "Promising", "Early", "Watch"]
RING_RADIUS = {"Pilot-ready": 1, "Promising": 2, "Early": 3, "Watch": 4}


# ── Data loading ─────────────────────────────────────────────────────────────


@st.cache_data
def load_radar() -> pd.DataFrame:
    if not RADAR_FILE.exists():
        return pd.DataFrame()
    return pd.read_csv(RADAR_FILE)


def rescore(df: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    """Re-rank using sidebar slider weights (live)."""
    from radar.scoring import score_dataframe

    return score_dataframe(
        df.drop(
            columns=[
                c
                for c in ["total_score", "theme", "ring", "dataset_kind"]
                + [f"{k}_score" for k in SCORING_CFG.criteria]
                if c in df.columns
            ]
        ),
        SCORING_CFG,
        weights=weights,
        dataset_kind=df["dataset_kind"].iloc[0] if "dataset_kind" in df.columns else "real",
    )


# ── Sidebar ──────────────────────────────────────────────────────────────────


def sidebar(df: pd.DataFrame) -> tuple[dict[str, float], list[str], bool]:
    st.sidebar.header("Controls")

    st.sidebar.subheader("Criterion weights")
    weights = {}
    for crit_name, crit_cfg in SCORING_CFG.criteria.items():
        label = crit_name.replace("_", " ").title()
        weights[crit_name] = st.sidebar.slider(
            label, 0.0, 1.0, crit_cfg.weight, 0.05, key=f"w_{crit_name}"
        )

    st.sidebar.subheader("Filters")
    all_themes = sorted(df["theme"].dropna().unique()) if "theme" in df.columns else []
    theme_filter = st.sidebar.multiselect("Themes", all_themes, default=all_themes)

    show_unreviewed = st.sidebar.toggle("Show unreviewed", value=False)

    return weights, theme_filter, show_unreviewed


# ── Radar chart ──────────────────────────────────────────────────────────────


def _deterministic_jitter(slug: str, sector_center: float, sector_width: float) -> float:
    """Deterministic angular jitter within a sector, derived from slug hash."""
    h = int(hashlib.md5(slug.encode()).hexdigest()[:8], 16)
    frac = (h % 1000) / 1000.0
    offset = (frac - 0.5) * sector_width * 0.7
    return sector_center + offset


def radar_chart(df: pd.DataFrame) -> go.Figure:
    quadrant_ids = list(SCORING_CFG.quadrants.keys())
    n_quads = len(quadrant_ids)
    sector_width = 360.0 / n_quads

    quad_centers = {}
    for i, qid in enumerate(quadrant_ids):
        quad_centers[qid] = i * sector_width + sector_width / 2

    fig = go.Figure()

    # Ring boundaries
    for ring_name, r in RING_RADIUS.items():
        fig.add_trace(
            go.Scatterpolar(
                r=[r] * 72,
                theta=[i * 5 for i in range(72)],
                mode="lines",
                line=dict(color="lightgray", width=1),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    if df.empty:
        fig.update_layout(polar=dict(radialaxis=dict(visible=False)))
        return fig

    for _, row in df.iterrows():
        theme = row.get("theme", "")
        ring = row.get("ring", "Watch")
        slug = row.get("slug", "")
        name = row.get("title", slug)

        r = RING_RADIUS.get(ring, 4)
        # Add small radial jitter
        h = int(hashlib.md5(slug.encode()).hexdigest()[8:12], 16)
        r_jitter = r + (h % 100) / 100.0 * 0.4 - 0.2

        theta = _deterministic_jitter(
            slug,
            quad_centers.get(theme, 0),
            sector_width,
        )

        fig.add_trace(
            go.Scatterpolar(
                r=[max(0.3, r_jitter)],
                theta=[theta],
                mode="markers+text",
                marker=dict(size=12),
                text=[slug],
                textposition="top center",
                textfont=dict(size=9),
                name=name,
                hovertext=(
                    f"{name}<br>Score: {row.get('total_score', 0)}"
                    f"<br>Ring: {ring}<br>Theme: {theme}"
                ),
                hoverinfo="text",
            )
        )

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 4.5],
                tickvals=[1, 2, 3, 4],
                ticktext=RING_ORDER,
            ),
            angularaxis=dict(
                tickvals=[quad_centers[qid] for qid in quadrant_ids],
                ticktext=[SCORING_CFG.quadrants[qid].label for qid in quadrant_ids],
                direction="clockwise",
            ),
        ),
        showlegend=False,
        height=600,
        margin=dict(t=40, b=40),
    )
    return fig


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    st.title("Maritime Tech Radar")

    df = load_radar()

    if df.empty:
        st.warning("No radar data found. Run `radar run` then `radar score` to generate data.")
        return

    # Demo banner
    is_demo = df.get("dataset_kind", pd.Series(["real"])).iloc[0] == "demo"
    if is_demo:
        st.error("🚨 SYNTHETIC DEMO DATA — NOT REAL START-UPS 🚨")

    weights, theme_filter, show_unreviewed = sidebar(df)

    # Re-score with current weights
    scored = rescore(df, weights)

    # Filter
    if theme_filter:
        scored = scored[scored["theme"].isin(theme_filter)]

    if not show_unreviewed and "reviewed" in scored.columns:
        scored = scored[scored["reviewed"].astype(str).str.lower().isin(["true", "1", "yes"])]

    st.subheader("Radar")
    fig = radar_chart(scored)
    st.plotly_chart(fig, use_container_width=True)

    # Ranked table
    st.subheader("Ranked start-ups")
    display_cols = ["slug", "title", "total_score", "ring", "theme"]
    score_cols = [c for c in scored.columns if c.endswith("_score") and c != "total_score"]
    display_cols += score_cols

    if "source_urls" in scored.columns:
        display_cols.append("source_urls")
    if "fetched_at" in scored.columns:
        display_cols.append("fetched_at")

    available = [c for c in display_cols if c in scored.columns]
    st.dataframe(scored[available], use_container_width=True, hide_index=True)

    # CSV download
    csv = scored.to_csv(index=False)
    st.download_button("Download ranking as CSV", csv, "radar_ranking.csv", "text/csv")

    # Method & limitations
    st.divider()
    st.subheader("Method & limitations")
    n = len(scored)
    data_as_of = scored["fetched_at"].max() if "fetched_at" in scored.columns else "unknown"
    st.markdown(
        f"""
- **Scoring method:** heuristic keyword scoring with human-reviewed fields.
- **Sample size:** n={n} start-ups in this view.
- **Data as of:** {data_as_of}.
- **Sources:** public web pages only; each fact carries a source URL and retrieval date.
- **Dataset:** {"SYNTHETIC DEMO" if is_demo else "Real (human-reviewed)"}.
- **Not affiliated with or endorsed by PortXL.** Independent work sample, public info only.
"""
    )


main()
