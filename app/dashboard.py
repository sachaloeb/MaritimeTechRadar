"""Single-page Streamlit dashboard for the Maritime Tech Radar."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from radar.config import load_scoring_config

st.set_page_config(page_title="Maritime Tech Radar", layout="wide")

RADAR_FILE = Path(os.environ.get("RADAR_CSV", "data/processed/radar.csv"))
SCORING_CFG = load_scoring_config()

RING_ORDER = ["Pilot-ready", "Promising", "Early", "Watch"]
RING_RADIUS = {"Pilot-ready": 1, "Promising": 2, "Early": 3, "Watch": 4}


# ── Data loading ─────────────────────────────────────────────────────────────


@st.cache_data
def load_radar(_path: str, _mtime: float) -> pd.DataFrame:
    p = Path(_path)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def _get_radar_df() -> pd.DataFrame:
    if RADAR_FILE.exists():
        mtime = RADAR_FILE.stat().st_mtime
    else:
        mtime = 0.0
    return load_radar(str(RADAR_FILE), mtime)


def rescore(df: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    """Re-rank using sidebar slider weights (live)."""
    from radar.scoring import score_dataframe

    drop_cols = [
        c for c in
        ["total_score", "theme", "ring", "dataset_kind", "overridden_fields"]
        + [f"{k}_score" for k in SCORING_CFG.criteria]
        if c in df.columns
    ]
    clean = df.drop(columns=drop_cols)
    dk = df["dataset_kind"].iloc[0] if "dataset_kind" in df.columns else "real"
    return score_dataframe(
        clean, SCORING_CFG, weights=weights,
        dataset_kind=dk, include_unreviewed=True,
    )


# ── Sidebar ──────────────────────────────────────────────────────────────────


def sidebar(
    df: pd.DataFrame,
) -> tuple[dict[str, float], list[str], bool]:
    st.sidebar.header("Controls")

    st.sidebar.subheader("Criterion weights")
    weights: dict[str, float] = {}
    for crit_name, crit_cfg in SCORING_CFG.criteria.items():
        label = crit_name.replace("_", " ").title()
        weights[crit_name] = st.sidebar.slider(
            label, 0.0, 1.0, crit_cfg.weight, 0.05,
            key=f"w_{crit_name}",
        )

    # Show normalised weights
    total_w = sum(weights.values())
    if total_w > 0:
        norm = {k: round(v / total_w, 3) for k, v in weights.items()}
        st.sidebar.caption(f"Effective weights: {norm}")

    st.sidebar.subheader("Filters")
    scored = df[df.get("ring", pd.Series()) != "Unreviewed"]
    all_themes = sorted(scored["theme"].dropna().unique()) if not scored.empty else []
    theme_labels = {
        tid: SCORING_CFG.quadrants[tid].label
        for tid in all_themes if tid in SCORING_CFG.quadrants
    }
    # Add unassigned if present
    if "unassigned" in all_themes:
        theme_labels["unassigned"] = "Unassigned"

    theme_filter = st.sidebar.multiselect(
        "Themes",
        options=list(theme_labels.keys()),
        default=list(theme_labels.keys()),
        format_func=lambda t: theme_labels.get(t, t),
    )

    show_unreviewed = st.sidebar.toggle("Show unreviewed", value=False)

    return weights, theme_filter, show_unreviewed


# ── Radar chart ──────────────────────────────────────────────────────────────


def _deterministic_jitter(
    slug: str, sector_center: float, sector_width: float
) -> float:
    h = int(hashlib.md5(slug.encode()).hexdigest()[:8], 16)
    frac = (h % 1000) / 1000.0
    offset = (frac - 0.5) * sector_width * 0.7
    return sector_center + offset


def radar_chart(df: pd.DataFrame) -> tuple[go.Figure, list[str]]:
    """Returns (figure, list_of_unassigned_slugs)."""
    quadrant_ids = list(SCORING_CFG.quadrants.keys())
    n_quads = len(quadrant_ids)
    sector_width = 360.0 / n_quads

    quad_centers = {
        qid: i * sector_width + sector_width / 2
        for i, qid in enumerate(quadrant_ids)
    }

    fig = go.Figure()
    for _, r_val in RING_RADIUS.items():
        fig.add_trace(go.Scatterpolar(
            r=[r_val] * 72, theta=[i * 5 for i in range(72)],
            mode="lines", line=dict(color="lightgray", width=1),
            showlegend=False, hoverinfo="skip",
        ))

    unassigned: list[str] = []

    if df.empty:
        fig.update_layout(polar=dict(radialaxis=dict(visible=False)))
        return fig, unassigned

    for _, row in df.iterrows():
        theme = row.get("theme", "")
        ring = row.get("ring", "Watch")
        slug = str(row.get("slug", ""))
        name = str(row.get("name", slug))

        if theme == "unassigned" or theme not in quad_centers:
            unassigned.append(f"{name} ({slug})")
            continue

        r = RING_RADIUS.get(ring, 4)
        h = int(hashlib.md5(slug.encode()).hexdigest()[8:12], 16)
        r_jitter = r + (h % 100) / 100.0 * 0.4 - 0.2

        theta = _deterministic_jitter(
            slug, quad_centers.get(theme, 0), sector_width
        )

        fig.add_trace(go.Scatterpolar(
            r=[max(0.3, r_jitter)], theta=[theta],
            mode="markers+text", marker=dict(size=12),
            text=[slug], textposition="top center",
            textfont=dict(size=9), name=name,
            hovertext=(
                f"{name}<br>Score: {row.get('total_score', 0)}"
                f"<br>Ring: {ring}<br>Theme: {theme}"
            ),
            hoverinfo="text",
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True, range=[0, 4.5],
                tickvals=[1, 2, 3, 4], ticktext=RING_ORDER,
            ),
            angularaxis=dict(
                tickvals=[quad_centers[q] for q in quadrant_ids],
                ticktext=[
                    SCORING_CFG.quadrants[q].label for q in quadrant_ids
                ],
                direction="clockwise",
            ),
        ),
        showlegend=False, height=600, margin=dict(t=40, b=40),
    )
    return fig, unassigned


# ── Sources table ────────────────────────────────────────────────────────────


def _build_sources_table(df: pd.DataFrame) -> pd.DataFrame:
    """Expand pipe-joined source columns into one row per source page."""
    rows = []
    for _, r in df.iterrows():
        name = str(r.get("name", r.get("slug", "")))
        urls = str(r.get("source_urls", "")).split("|")
        dates = str(r.get("source_fetched_at", "")).split("|")
        statuses = str(r.get("source_statuses", "")).split("|")
        for i, url in enumerate(urls):
            if not url.strip():
                continue
            rows.append({
                "Start-up": name,
                "URL": url.strip(),
                "Retrieved": dates[i].strip() if i < len(dates) else "",
                "Status": statuses[i].strip() if i < len(statuses) else "",
            })
    return pd.DataFrame(rows)


# ── Sensitivity table ────────────────────────────────────────────────────────


def _compute_sensitivity(df: pd.DataFrame) -> pd.DataFrame | None:
    """Weight sensitivity from radar.csv alone."""
    scored = df[df["ring"] != "Unreviewed"]
    if scored.empty or len(scored) < 2:
        return None
    from radar.analysis import rq3_weight_sensitivity
    return rq3_weight_sensitivity(scored, SCORING_CFG)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    st.title("Maritime Tech Radar")

    df = _get_radar_df()

    if df.empty:
        st.warning(
            "No radar data found. Run `radar run` then `radar score`."
        )
        return

    # Demo banner
    is_demo = (
        df.get("dataset_kind", pd.Series(["real"])).iloc[0] == "demo"
    )
    if is_demo:
        st.error(
            "\U0001f6a8 SYNTHETIC DEMO DATA \u2014 NOT REAL START-UPS \U0001f6a8"
        )

    weights, theme_filter, show_unreviewed = sidebar(df)

    # Re-score with slider weights
    scored = rescore(df, weights)

    # Split reviewed vs unreviewed
    reviewed_mask = scored["ring"] != "Unreviewed"
    reviewed = scored[reviewed_mask].copy()
    unreviewed = scored[~reviewed_mask].copy()

    # Filter reviewed by theme
    if theme_filter:
        reviewed = reviewed[reviewed["theme"].isin(theme_filter)]
    else:
        st.info("No themes selected — deselect all shows no start-ups.")
        reviewed = reviewed.iloc[0:0]

    # Radar plot
    st.subheader("Radar")
    fig, unassigned_list = radar_chart(reviewed)
    st.plotly_chart(fig, use_container_width=True)
    if unassigned_list:
        st.caption(
            "**Unassigned (not plotted):** " + ", ".join(unassigned_list)
        )

    # Ranked table
    st.subheader("Ranked start-ups")
    display_cols = [
        "name", "slug", "total_score", "ring", "theme",
    ]
    score_cols = [
        f"{c}_score" for c in SCORING_CFG.criteria
        if f"{c}_score" in reviewed.columns
    ]
    display_cols += score_cols
    if "overridden_fields" in reviewed.columns:
        display_cols.append("overridden_fields")
    if "reviewed" in reviewed.columns:
        display_cols.append("reviewed")

    available = [c for c in display_cols if c in reviewed.columns]
    if not reviewed.empty:
        st.dataframe(
            reviewed[available], use_container_width=True, hide_index=True
        )
    else:
        st.info("No scored start-ups to display.")

    # Unreviewed table
    if show_unreviewed and not unreviewed.empty:
        st.subheader("Awaiting review (not scored)")
        ur_cols = ["name", "slug", "source_count"]
        ur_avail = [c for c in ur_cols if c in unreviewed.columns]
        st.dataframe(
            unreviewed[ur_avail],
            use_container_width=True, hide_index=True,
        )

    # Sources & evidence
    st.subheader("Sources & evidence")
    sources = _build_sources_table(scored[reviewed_mask])
    if not sources.empty:
        st.dataframe(
            sources,
            column_config={"URL": st.column_config.LinkColumn("URL")},
            use_container_width=True, hide_index=True,
        )

    # CSV download
    csv = reviewed.to_csv(index=False)
    st.download_button(
        "Download ranking as CSV", csv, "radar_ranking.csv", "text/csv"
    )

    # Method & limitations
    st.divider()
    st.subheader("Method & limitations")

    # Gather stats
    n = len(reviewed)
    all_dates = []
    for col in ["source_fetched_at"]:
        if col in scored.columns:
            for val in scored[col].dropna():
                all_dates.extend(str(val).split("|"))
    data_as_of = max(all_dates) if all_dates else "unknown"

    st.markdown(f"""
- **Scoring:** `total = 100 * sum(w_i * s_i / 5)` where `s_i = min(5, 5 * hits / saturation)`.
- **n = {n}** scored start-ups in this view. Data as of **{data_as_of}**.
- Heuristic keyword scores plus human judgement.
- Rings show maturity visible in public evidence, not company quality.
- **Independent of and not endorsed by PortXL.**
""")

    # Sensitivity table
    sens = _compute_sensitivity(scored)
    if sens is not None and not sens.empty:
        st.subheader("Weight sensitivity")
        st.dataframe(sens, use_container_width=True, hide_index=True)


main()
