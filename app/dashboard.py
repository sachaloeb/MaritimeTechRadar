"""Single-page Streamlit dashboard for the Maritime Tech Radar."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from radar.config import load_scoring_config
from radar.scoring import NON_SCORED_RINGS

st.set_page_config(
    page_title="Maritime Tech Radar",
    page_icon=None,
    layout="wide",
)

SCORING_CFG = load_scoring_config()


def _radar_file() -> Path:
    return Path(os.environ.get("RADAR_CSV", "data/processed/radar.csv"))

RING_ORDER = ["Pilot-ready", "Promising", "Early", "Watch"]
RING_RADIUS = {"Pilot-ready": 1, "Promising": 2, "Early": 3, "Watch": 4}

# Colour-blind-safe palette (Okabe-Ito inspired)
RING_COLOURS = {
    "Pilot-ready": "#009E73",  # bluish green
    "Promising": "#0072B2",    # blue
    "Early": "#E69F00",        # orange
    "Watch": "#CC79A7",        # reddish purple
}


# ── Data loading ─────────────────────────────────────────────────────────────


@st.cache_data
def load_radar(_path: str, _mtime: float) -> pd.DataFrame:
    p = Path(_path)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def _get_radar_df() -> pd.DataFrame:
    if _radar_file().exists():
        mtime = _radar_file().stat().st_mtime
    else:
        mtime = 0.0
    return load_radar(str(_radar_file()), mtime)


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


def _data_as_of(df: pd.DataFrame) -> str:
    """Extract the latest fetched_at date from the DataFrame."""
    all_dates: list[str] = []
    if "source_fetched_at" in df.columns:
        for val in df["source_fetched_at"].dropna():
            all_dates.extend(str(val).split("|"))
    clean = [d.strip() for d in all_dates if d.strip()]
    return max(clean) if clean else "unknown"


# ── Sidebar ──────────────────────────────────────────────────────────────────


def _reset_weights() -> None:
    """on_click callback: write config defaults into session_state."""
    for crit_name, crit_cfg in SCORING_CFG.criteria.items():
        st.session_state[f"w_{crit_name}"] = crit_cfg.weight


def sidebar(
    df: pd.DataFrame,
) -> tuple[dict[str, float], list[str], bool]:
    st.sidebar.header("Controls")

    st.sidebar.subheader("Criterion weights")

    # Initialise missing keys before creating sliders
    for crit_name, crit_cfg in SCORING_CFG.criteria.items():
        key = f"w_{crit_name}"
        if key not in st.session_state:
            st.session_state[key] = crit_cfg.weight

    weights: dict[str, float] = {}
    for crit_name in SCORING_CFG.criteria:
        label = crit_name.replace("_", " ").title()
        weights[crit_name] = st.sidebar.slider(
            label, 0.0, 1.0, step=0.05,
            key=f"w_{crit_name}",
        )

    # Reset button — on_click fires before the next run, so sliders
    # pick up the restored defaults without a manual rerun.
    st.sidebar.button("Reset weights", on_click=_reset_weights)

    # Show normalised weights
    total_w = sum(weights.values())
    if total_w > 0:
        norm = {k: round(v / total_w, 3) for k, v in weights.items()}
        norm_text = ", ".join(
            f"{k.replace('_', ' ').title()}: {v}" for k, v in norm.items()
        )
        st.sidebar.caption(f"Effective weights: {norm_text}")

    st.sidebar.subheader("Filters")
    scored = df[~df["ring"].isin(NON_SCORED_RINGS)] if "ring" in df.columns else df
    all_themes = (
        sorted(scored["theme"].dropna().unique()) if not scored.empty else []
    )
    theme_labels: dict[str, str] = {}
    for tid in all_themes:
        if tid in SCORING_CFG.quadrants:
            theme_labels[tid] = SCORING_CFG.quadrants[tid].label
        elif tid == "unassigned":
            theme_labels["unassigned"] = "Unassigned"

    theme_filter = st.sidebar.multiselect(
        "Themes",
        options=list(theme_labels.keys()),
        default=list(theme_labels.keys()),
        format_func=lambda t: theme_labels.get(t, t),
    )

    show_unreviewed = st.sidebar.toggle("Show unreviewed", value=False)

    # CSV download
    st.sidebar.divider()
    csv = df.to_csv(index=False)
    st.sidebar.download_button(
        "Download full data as CSV", csv, "radar_ranking.csv", "text/csv"
    )

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
    """Returns (figure, list_of_unassigned_display_strings)."""
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
        sc = row.get("source_count", 0)
        theme_label = (
            SCORING_CFG.quadrants[theme].label
            if theme in SCORING_CFG.quadrants else theme
        )

        if theme == "unassigned" or theme not in quad_centers:
            unassigned.append(f"{name} ({slug})")
            continue

        r = RING_RADIUS.get(ring, 4)
        h = int(hashlib.md5(slug.encode()).hexdigest()[8:12], 16)
        r_jitter = r + (h % 100) / 100.0 * 0.4 - 0.2

        theta = _deterministic_jitter(
            slug, quad_centers.get(theme, 0), sector_width
        )

        colour = RING_COLOURS.get(ring, "#999999")

        fig.add_trace(go.Scatterpolar(
            r=[max(0.3, r_jitter)], theta=[theta],
            mode="markers+text",
            marker=dict(size=12, color=colour),
            text=[name], textposition="top center",
            textfont=dict(size=9), name=name,
            hovertext=(
                f"{name}<br>Score: {row.get('total_score', 0)}"
                f"<br>Ring: {ring}<br>Theme: {theme_label}"
                f"<br>Sources: {sc}"
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
    rows: list[dict] = []
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
    scored = df[~df["ring"].isin(NON_SCORED_RINGS)]
    if scored.empty or len(scored) < 2:
        return None
    from radar.analysis import rq3_weight_sensitivity
    return rq3_weight_sensitivity(scored, SCORING_CFG)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    st.title("Maritime Tech Radar")
    st.caption(
        "Heuristic and indicative: rings show maturity visible in "
        "public evidence, not company quality. "
        "Independent work sample, not affiliated with or endorsed by PortXL."
    )

    df = _get_radar_df()

    if df.empty:
        st.warning(
            "No radar data found. Run `radar run` then `radar score`, "
            f"or set RADAR_CSV to the path of your radar.csv. "
            f"Expected: {_radar_file()}"
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

    # Split by ring type
    scored_mask = ~scored["ring"].isin(NON_SCORED_RINGS)
    reviewed = scored[scored_mask].copy()
    unreviewed = scored[scored["ring"] == "Unreviewed"].copy()
    excluded = scored[scored["ring"] == "Excluded"].copy()

    # Metric row
    data_as_of = _data_as_of(scored)
    n_scored = len(reviewed)
    n_awaiting = len(unreviewed)
    n_excluded = len(excluded)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Scored", n_scored)
    m2.metric("Awaiting review", n_awaiting)
    m3.metric("Excluded", n_excluded)
    m4.metric("Data as of", data_as_of[:10] if len(data_as_of) > 10 else data_as_of)

    # Ring legend (from config, never hard-coded)
    rings_cfg = SCORING_CFG.rings
    ring_text = (
        f"**Rings:** "
        f"\u2265{rings_cfg.pilot_ready} Pilot-ready, "
        f"{rings_cfg.promising}\u2013{rings_cfg.pilot_ready - 1} Promising, "
        f"{rings_cfg.early}\u2013{rings_cfg.promising - 1} Early, "
        f"<{rings_cfg.early} Watch"
    )
    st.caption(ring_text)

    # Filter reviewed by theme
    if theme_filter:
        reviewed = reviewed[reviewed["theme"].isin(theme_filter)]
    else:
        st.info(
            "No themes selected. Select at least one theme in the "
            "sidebar to see start-ups."
        )
        reviewed = reviewed.iloc[0:0]

    # Radar plot
    st.subheader("Radar")
    fig, unassigned_list = radar_chart(reviewed)
    st.plotly_chart(fig, use_container_width=True)
    if unassigned_list:
        st.caption(
            "**Unassigned (not plotted):** " + ", ".join(unassigned_list)
        )

    # Ranked table with column config
    st.subheader("Ranked start-ups")
    if not reviewed.empty:
        col_config: dict[str, st.column_config.Column] = {
            "total_score": st.column_config.ProgressColumn(
                "Total (0-100)", min_value=0, max_value=100, format="%.1f"
            ),
        }
        for crit_name in SCORING_CFG.criteria:
            sc = f"{crit_name}_score"
            if sc in reviewed.columns:
                col_config[sc] = st.column_config.ProgressColumn(
                    crit_name.replace("_", " ").title() + " (0-5)",
                    min_value=0, max_value=5, format="%.2f",
                )
        # Theme label
        if "theme" in reviewed.columns:
            reviewed = reviewed.copy()
            reviewed["theme_label"] = reviewed["theme"].map(
                lambda t: (
                    SCORING_CFG.quadrants[t].label
                    if t in SCORING_CFG.quadrants else t
                )
            )

        display_cols = ["name", "slug", "total_score", "ring", "theme_label"]
        score_cols = [
            f"{c}_score" for c in SCORING_CFG.criteria
            if f"{c}_score" in reviewed.columns
        ]
        display_cols += score_cols
        for extra in ["overridden_fields", "reviewed", "source_count"]:
            if extra in reviewed.columns:
                display_cols.append(extra)
        if "source_fetched_at" in reviewed.columns:
            display_cols.append("source_fetched_at")

        available = [c for c in display_cols if c in reviewed.columns]
        st.dataframe(
            reviewed[available], column_config=col_config,
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No scored start-ups to display.")

    # "Why this score?" expanders
    if not reviewed.empty:
        st.subheader("Why this score?")
        for _, row in reviewed.iterrows():
            name = str(row.get("name", row.get("slug", "?")))
            slug = str(row.get("slug", "?"))
            total = row.get("total_score", 0)
            ring = row.get("ring", "?")
            with st.expander(f"{name} ({slug}) \u2014 {total:.1f} / {ring}"):
                for crit_name, crit_cfg in SCORING_CFG.criteria.items():
                    sc = row.get(f"{crit_name}_score", 0)
                    hits = row.get(f"{crit_name}_hits", 0)
                    matched = str(row.get(f"{crit_name}_matched", ""))
                    ov = row.get(f"{crit_name}_override", "")
                    is_overridden = pd.notna(ov) and str(ov).strip() != ""
                    label = crit_name.replace("_", " ").title()

                    ov_tag = " **(overridden)**" if is_overridden else ""
                    kw_list = matched if matched else "(none)"
                    st.markdown(
                        f"- **{label}**: {sc:.2f}/5 "
                        f"({hits} hits / {crit_cfg.saturation} sat.)"
                        f"{ov_tag} \u2014 keywords: {kw_list}"
                    )

    # Unreviewed table
    if show_unreviewed and not unreviewed.empty:
        st.subheader("Awaiting review (not scored)")
        ur_cols = ["name", "slug", "source_count"]
        ur_avail = [c for c in ur_cols if c in unreviewed.columns]
        st.dataframe(
            unreviewed[ur_avail],
            use_container_width=True, hide_index=True,
        )

    # Excluded expander
    if not excluded.empty:
        with st.expander(f"Excluded ({n_excluded} start-ups, with reason)"):
            ex_cols = ["name", "slug", "exclusion_reason"]
            ex_avail = [c for c in ex_cols if c in excluded.columns]
            st.dataframe(
                excluded[ex_avail],
                use_container_width=True, hide_index=True,
            )

    # Sources & evidence
    st.subheader("Sources & evidence")
    sources = _build_sources_table(reviewed)
    if not sources.empty:
        st.dataframe(
            sources,
            column_config={
                "URL": st.column_config.LinkColumn("URL"),
            },
            use_container_width=True, hide_index=True,
        )

    # Method & limitations
    st.divider()
    st.subheader("Method & limitations")

    st.markdown(
        f"**Scoring:** `total = 100 * sum(w_i * s_i / 5)` "
        f"where `s_i = min(5, 5 * hits / saturation)`.\n\n"
        f"**n = {n_scored}** scored start-ups. "
        f"Data as of **{data_as_of}**."
    )

    # Criteria table from config
    crit_rows: list[dict] = []
    for crit_name, crit_cfg in SCORING_CFG.criteria.items():
        label = crit_name.replace("_", " ").title()
        method = "Whole-word keyword hits"
        if crit_cfg.derived_from:
            method = f"Derived from {crit_cfg.derived_from}"
        crit_rows.append({
            "Criterion": label,
            "Weight": crit_cfg.weight,
            "Saturation": crit_cfg.saturation,
            "Method": method,
        })
    st.dataframe(
        pd.DataFrame(crit_rows),
        use_container_width=True, hide_index=True,
    )

    # Ring thresholds from config
    st.caption(ring_text)

    # Themes
    theme_names = [
        SCORING_CFG.quadrants[q].label for q in SCORING_CFG.quadrants
    ]
    st.markdown(
        f"**Themes:** {', '.join(theme_names)}. "
        "Themes are illustrative defaults and are editable in "
        "`configs/scoring.yaml`."
    )

    # Known limits
    st.markdown(
        "**Known limits of heuristic scoring:**\n"
        "- Matching is context-blind: navigation labels, footers "
        "and bios can match.\n"
        "- theme_fit saturates quickly from a single quadrant.\n"
        "- Maturity vocabulary is narrow.\n"
        "- Human overrides exist for exactly this reason.\n"
    )
    if not is_demo:
        st.caption(
            "Independent work sample, not affiliated with or endorsed "
            "by PortXL."
        )

    # Sensitivity table
    sens = _compute_sensitivity(scored)
    if sens is not None and not sens.empty:
        st.subheader("Weight sensitivity")
        if n_scored < 5:
            st.caption(
                f"n={n_scored} is too small for meaningful sensitivity "
                f"conclusions."
            )
        st.dataframe(sens, use_container_width=True, hide_index=True)


main()
