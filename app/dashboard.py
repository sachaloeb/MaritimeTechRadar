"""Single-page Streamlit dashboard for the Maritime Tech Radar."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from radar.columns import COLUMN_LABELS  # noqa: F401  # exported for consumers
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


def _pretty(name: str) -> str:
    """'maritime_relevance' -> 'Maritime Relevance'."""
    return name.replace("_", " ").title()


def _short_date(iso: str) -> str:
    """'2026-01-15T12:00:00+00:00' -> '2026-01-15'."""
    return iso[:10] if len(iso) >= 10 else iso


def _short_label(label: str) -> str:
    """Shorten theme label to fit sidebar multiselect chips."""
    return (
        label
        .replace("Decarbonisation", "Decarb")
        .replace("Digitalisation", "Digital")
        .replace("Operations", "Ops")
    )


def _text_position(theta: float) -> str:
    """Best Plotly textposition for a polar marker at angle theta (clockwise from N)."""
    theta = theta % 360
    if theta < 45 or theta >= 315:
        return "top center"
    elif theta < 135:
        return "middle right"
    elif theta < 225:
        return "bottom center"
    else:
        return "middle left"


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
        label = _pretty(crit_name)
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
            f"{_pretty(k)}: {v}" for k, v in norm.items()
        )
        st.sidebar.caption(f"Effective weights: {norm_text}")

    st.sidebar.subheader("Filters")
    scored = (
        df[~df["ring"].isin(NON_SCORED_RINGS)]
        if "ring" in df.columns else df
    )
    all_themes = (
        sorted(scored["theme"].dropna().unique())
        if not scored.empty else []
    )
    theme_labels: dict[str, str] = {}
    for tid in all_themes:
        if tid in SCORING_CFG.quadrants:
            theme_labels[tid] = SCORING_CFG.quadrants[tid].label
        elif tid == "unassigned":
            theme_labels["unassigned"] = "Unassigned"

    # Use an expander so chips don't get truncated by sidebar width
    with st.sidebar.expander("Themes", expanded=True):
        theme_filter = st.multiselect(
            "",
            options=list(theme_labels.keys()),
            default=list(theme_labels.keys()),
            format_func=lambda t: _short_label(theme_labels.get(t, t)),
            label_visibility="collapsed",
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
    for ring_name, r_val in RING_RADIUS.items():
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
        tpos = _text_position(theta)
        colour = RING_COLOURS.get(ring, "#999999")

        fig.add_trace(go.Scatterpolar(
            r=[max(0.6, r_jitter)], theta=[theta],
            mode="markers+text",
            marker=dict(size=14, color=colour),
            text=[name], textposition=tpos,
            textfont=dict(size=13), name=name,
            showlegend=False,  # companies hidden; only ring traces in legend
            hovertext=(
                f"{name}<br>Score: {row.get('total_score', 0)}"
                f"<br>Ring: {ring}<br>Theme: {theme_label}"
                f"<br>Sources: {sc}"
            ),
            hoverinfo="text",
        ))

    # Ring colour legend — one invisible trace per ring only
    for ring_name, colour in RING_COLOURS.items():
        fig.add_trace(go.Scatterpolar(
            r=[None], theta=[None],
            mode="markers", marker=dict(size=10, color=colour),
            name=ring_name, showlegend=True,
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True, range=[0, 4.8],
                tickvals=[1, 2, 3, 4],
                showticklabels=False,  # ring names shown in legend, not axis
            ),
            angularaxis=dict(
                tickvals=[quad_centers[q] for q in quadrant_ids],
                ticktext=[
                    SCORING_CFG.quadrants[q].label for q in quadrant_ids
                ],
                direction="clockwise",
            ),
        ),
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="top", y=-0.05,
            xanchor="center", x=0.5,
        ),
        height=520, margin=dict(t=40, b=80),
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
            raw_date = dates[i].strip() if i < len(dates) else ""
            rows.append({
                "Start-up": name,
                "URL": url.strip(),
                "Retrieved": _short_date(raw_date),
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


def _format_sensitivity(sens: pd.DataFrame, n: int) -> pd.DataFrame:
    """Clean up sensitivity table for display."""
    _EM = "\u2014"
    display = sens.copy()
    # Drop clipped column (internal detail)
    if "clipped" in display.columns:
        display = display.drop(columns=["clipped"])
    # Rename columns for readability
    renames = {
        "criterion": "Criterion",
        "delta": "\u0394 Weight",
        "new_weight": "New Weight",
        "rank_changes": "Rank Changes",
        "max_rank_shift": "Max Shift",
        "ring_changes": "Ring Changes",
        "spearman_vs_baseline": "Spearman \u03c1",
    }
    display = display.rename(columns=renames)
    # Prettify criterion names
    if "Criterion" in display.columns:
        display["Criterion"] = display["Criterion"].apply(
            lambda v: _pretty(v) if isinstance(v, str) else v
        )
    # Convert numeric-with-NA columns entirely to strings so PyArrow
    # doesn't choke on mixed float/str types in the SUMMARY row.
    if "\u0394 Weight" in display.columns:
        display["\u0394 Weight"] = display["\u0394 Weight"].apply(
            lambda v: _EM if pd.isna(v) else f"{float(v):+.2f}"
        )
    if "New Weight" in display.columns:
        display["New Weight"] = display["New Weight"].apply(
            lambda v: _EM if pd.isna(v) else f"{float(v):.4f}"
        )
    if "Max Shift" in display.columns:
        display["Max Shift"] = display["Max Shift"].apply(
            lambda v: _EM if pd.isna(v) else str(int(float(v)))
        )
    return display


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    st.title("Maritime Tech Radar")
    st.caption(
        "Heuristic and indicative: rings show maturity visible in "
        "public evidence, not company quality. "
        "Independent work sample, not affiliated with or endorsed by "
        "any company, accelerator, or programme."
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
    m4.metric("Data as of", _short_date(data_as_of))

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

    # ── Radar + Ranked table side by side ────────────────────────────────────
    col_radar, col_table = st.columns([1.1, 1])

    with col_radar:
        st.subheader("Radar")
        st.caption(
            "Distance from the centre \u2248 total score "
            "(closer to centre = higher score). "
            "Colour = ring. Direction = theme."
        )
        fig, unassigned_list = radar_chart(reviewed)
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": "hover", "displaylogo": False},
        )
        if unassigned_list:
            st.caption(
                "**Unassigned (not plotted):** " + ", ".join(unassigned_list)
            )

    with col_table:
        st.subheader("Ranked start-ups")
        if not reviewed.empty:
            col_config: dict[str, st.column_config.Column] = {
                "name": st.column_config.TextColumn("Start-up"),
                "total_score": st.column_config.ProgressColumn(
                    "Total (0\u2013100)", min_value=0, max_value=100,
                    format="%.1f",
                ),
                "ring": st.column_config.TextColumn("Ring"),
                "theme_label": st.column_config.TextColumn("Theme"),
                "source_count": st.column_config.NumberColumn("Sources"),
            }
            for crit_name in SCORING_CFG.criteria:
                sc = f"{crit_name}_score"
                if sc in reviewed.columns:
                    col_config[sc] = st.column_config.ProgressColumn(
                        _pretty(crit_name) + " (0\u20135)",
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

            # Human-readable dates
            if "source_fetched_at" in reviewed.columns:
                reviewed["source_fetched_at"] = (
                    reviewed["source_fetched_at"]
                    .fillna("")
                    .apply(
                        lambda v: ", ".join(
                            _short_date(d.strip())
                            for d in str(v).split("|") if d.strip()
                        )
                    )
                )
                col_config["source_fetched_at"] = (
                    st.column_config.TextColumn("Fetched")
                )

            display_cols = [
                "name", "total_score", "ring", "theme_label",
            ]
            score_cols = [
                f"{c}_score" for c in SCORING_CFG.criteria
                if f"{c}_score" in reviewed.columns
            ]
            display_cols += score_cols
            if "source_count" in reviewed.columns:
                display_cols.append("source_count")
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
            total = row.get("total_score", 0)
            ring = row.get("ring", "?")
            with st.expander(f"{name} \u2014 {total:.1f} / {ring}"):
                for crit_name, crit_cfg in SCORING_CFG.criteria.items():
                    sc = row.get(f"{crit_name}_score", 0)
                    hits = int(row.get(f"{crit_name}_hits", 0))
                    raw_matched = str(
                        row.get(f"{crit_name}_matched", "")
                    )
                    ov = row.get(f"{crit_name}_override", "")
                    is_ov = pd.notna(ov) and str(ov).strip() != ""
                    label = _pretty(crit_name)

                    ov_tag = " **(overridden)**" if is_ov else ""
                    kw_list = (
                        ", ".join(raw_matched.split("|"))
                        if raw_matched else "(none)"
                    )

                    # Evidence quality: show hits = pages + keywords breakdown
                    if crit_name == "evidence_quality":
                        pages = int(row.get("evidence_quality_pages", 0))
                        kw_count = hits - pages if hits > pages else 0
                        kw_detail = f" ({kw_list})" if kw_list != "(none)" else ""
                        decomp = (
                            f"{hits} hit{'s' if hits != 1 else ''} = "
                            f"{pages} page{'s' if pages != 1 else ''} + "
                            f"{kw_count} keyword{'s' if kw_count != 1 else ''}"
                            f"{kw_detail}"
                        )
                        st.markdown(
                            f"- **Evidence signals**: {sc:.2f}/5 "
                            f"\u2014 {decomp} / sat.\u00a0{crit_cfg.saturation}"
                            f"{ov_tag}"
                        )
                    else:
                        st.markdown(
                            f"- **{label}**: {sc:.2f}/5 "
                            f"({hits} hits / "
                            f"{crit_cfg.saturation} sat.)"
                            f"{ov_tag} \u2014 keywords: {kw_list}"
                        )

    # Unreviewed table
    if show_unreviewed and not unreviewed.empty:
        st.subheader("Awaiting review (not scored)")
        ur_cols = ["name", "source_count"]
        ur_avail = [c for c in ur_cols if c in unreviewed.columns]
        st.dataframe(
            unreviewed[ur_avail],
            column_config={
                "name": st.column_config.TextColumn("Start-up"),
                "source_count": st.column_config.NumberColumn("Sources"),
            },
            use_container_width=True, hide_index=True,
        )

    # Excluded expander
    if not excluded.empty:
        with st.expander(
            f"Excluded ({n_excluded} start-up"
            f"{'s' if n_excluded != 1 else ''}, with reason)"
        ):
            ex_cols = ["name", "exclusion_reason"]
            ex_avail = [c for c in ex_cols if c in excluded.columns]
            st.dataframe(
                excluded[ex_avail],
                column_config={
                    "name": st.column_config.TextColumn("Start-up"),
                    "exclusion_reason": st.column_config.TextColumn(
                        "Reason"
                    ),
                },
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
        f"where `s_i = min(5, 5 * hits / saturation)`. "
        f"Evidence quality hits = distinct pages (deduplicated by content hash) "
        f"+ distinct evidence keywords. "
        f"This rewards breadth (independent public pages) and proof-type language, "
        f"not repetition.\n\n"
        f"**n = {n_scored}** scored start-ups. "
        f"Data as of **{_short_date(data_as_of)}**."
    )

    # Criteria table from config
    crit_rows: list[dict] = []
    for crit_name, crit_cfg in SCORING_CFG.criteria.items():
        label = _pretty(crit_name)
        method = "Whole-word keyword hits"
        if crit_cfg.derived_from:
            method = f"Derived from {crit_cfg.derived_from}"
        if crit_name == "evidence_quality":
            method = "Distinct pages + evidence keyword hits"
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
            "by any company, accelerator, or programme."
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
        # Separate SUMMARY row (shown as caption) from data rows (shown as table)
        summary_mask = sens.get("criterion", sens.iloc[:, 0]) == "SUMMARY"
        sens_data = sens[~summary_mask].copy()
        sens_summary = sens[summary_mask]

        display_sens = _format_sensitivity(sens_data, n_scored)
        st.dataframe(
            display_sens,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Criterion": st.column_config.TextColumn(
                    "Criterion", width="medium"
                ),
                "Spearman \u03c1": st.column_config.TextColumn(
                    "Spearman \u03c1", width="large"
                ),
            },
        )
        summary_text = (
            str(sens_summary.iloc[0]["spearman_vs_baseline"])
            if not sens_summary.empty else ""
        )
        st.caption(
            "Each row: effect of \u00b10.10 shift on one criterion weight "
            "(others rescaled proportionally). "
            "Spearman \u03c1\u00a0< 1 = ranking changed; "
            "ring change = at least one start-up crossed a threshold."
            + (f" \u2014 {summary_text}" if summary_text else "")
        )


main()
