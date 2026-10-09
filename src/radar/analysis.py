"""Analysis functions for RQ1-RQ4 and the sensitivity table."""

from __future__ import annotations

import hashlib
import logging
import math
import tempfile
from pathlib import Path

import pandas as pd

from radar.config import ScoringConfig, load_scoring_config, load_startups_config
from radar.paths import (
    collection_report_path,
    extracted_csv_path,
    radar_csv_path,
    raw_dir,
    review_sheet_path,
)
from radar.scoring import NON_SCORED_RINGS

logger = logging.getLogger(__name__)

# README markers — these MUST match what is in README.md
RESULTS_START = "<!-- RESULTS:START -->"
RESULTS_END = "<!-- RESULTS:END -->"
SNAPSHOT_START = "<!-- SNAPSHOT:START -->"
SNAPSHOT_END = "<!-- SNAPSHOT:END -->"


# ── Markdown table helper (no tabulate dependency) ────────────────────────────


def _df_to_md_table(df: pd.DataFrame) -> str:
    """Render a DataFrame as a pipe-delimited markdown table.

    Deterministic, stdlib-only replacement for ``df.to_markdown()``.
    """
    if df.empty:
        return "(no data)\n"
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    rows: list[str] = []
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if pd.isna(v):
                cells.append("")
            else:
                cells.append(str(v))
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *rows]) + "\n"


# ── Utility ──────────────────────────────────────────────────────────────────


def _spearman_rho(ranks_a: list[float], ranks_b: list[float]) -> str:
    """Spearman rho as Pearson on ranks. Returns 'n/a' if n<3."""
    n = len(ranks_a)
    if n < 3:
        return "n/a"
    mean_a = sum(ranks_a) / n
    mean_b = sum(ranks_b) / n
    cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(ranks_a, ranks_b))
    std_a = math.sqrt(sum((a - mean_a) ** 2 for a in ranks_a))
    std_b = math.sqrt(sum((b - mean_b) ** 2 for b in ranks_b))
    if std_a == 0 or std_b == 0:
        return "n/a"
    return f"{cov / (std_a * std_b):.4f}"


def _average_ranks(scores: list[float]) -> list[float]:
    """Compute average ranks for a list of scores (higher score = lower rank)."""
    n = len(scores)
    indexed = sorted(enumerate(scores), key=lambda x: -x[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = sum(range(i + 1, j + 1)) / (j - i)
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


# ── RQ1: Coverage ────────────────────────────────────────────────────────────


def rq1_coverage(radar_df: pd.DataFrame, cfg: ScoringConfig) -> pd.DataFrame:
    """Per criterion: share overridden, mean TRUE automatic score, mean final score."""
    from radar.scoring import score_row

    scored = radar_df[
        ~radar_df["ring"].isin(NON_SCORED_RINGS)
    ].copy()
    if scored.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    for crit_name in cfg.criteria:
        ov_col = f"{crit_name}_override"
        score_col = f"{crit_name}_score"
        n = len(scored)
        overridden = 0
        if ov_col in scored.columns:
            overridden = scored[ov_col].apply(
                lambda v: pd.notna(v) and str(v).strip() != ""
            ).sum()

        # True automatic scores: re-score with all overrides blanked
        auto_scores: list[float] = []
        for _, row in scored.iterrows():
            auto_row = row.copy()
            for c in cfg.criteria:
                auto_row[f"{c}_override"] = ""
            auto_row["theme_override"] = ""
            auto_result = score_row(auto_row, cfg)
            auto_scores.append(auto_result[f"{crit_name}_score"])

        mean_auto = round(sum(auto_scores) / len(auto_scores), 4) if auto_scores else 0
        mean_final = (
            round(float(scored[score_col].mean()), 4) if score_col in scored.columns else 0
        )

        rows.append({
            "criterion": crit_name,
            "share_overridden": round(overridden / n, 4) if n > 0 else 0,
            "mean_auto_score": mean_auto,
            "mean_reviewed_score": mean_final,
        })

    # Theme override share
    n = len(scored)
    theme_ov = 0
    if "theme_override" in scored.columns:
        theme_ov = scored["theme_override"].apply(
            lambda v: pd.notna(v) and str(v).strip() != ""
        ).sum()
    rows.append({
        "criterion": "theme",
        "share_overridden": round(theme_ov / n, 4) if n > 0 else 0,
        "mean_auto_score": pd.NA,
        "mean_reviewed_score": pd.NA,
    })

    return pd.DataFrame(rows)


# ── RQ2: Review effect ───────────────────────────────────────────────────────


def rq2_review_effect(
    radar_df: pd.DataFrame, cfg: ScoringConfig
) -> pd.DataFrame:
    """Compare automatic vs reviewed scores; report rank/ring changes."""
    from radar.scoring import score_row

    scored = radar_df[
        ~radar_df["ring"].isin(NON_SCORED_RINGS)
    ].copy()
    if scored.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    auto_scores: list[float] = []
    reviewed_scores: list[float] = []

    for _, row in scored.iterrows():
        slug = row.get("slug", "?")
        reviewed_total = row.get("total_score", 0)

        # Compute automatic score (blank all overrides)
        auto_row = row.copy()
        for crit in cfg.criteria:
            auto_row[f"{crit}_override"] = ""
        auto_row["theme_override"] = ""

        auto_result = score_row(auto_row, cfg)
        auto_total = auto_result["total_score"]

        auto_scores.append(auto_total)
        reviewed_scores.append(reviewed_total)

        rows.append({
            "slug": slug,
            "auto_score": auto_total,
            "reviewed_score": reviewed_total,
            "auto_ring": auto_result["ring"],
            "reviewed_ring": row.get("ring", ""),
            "ring_changed": auto_result["ring"] != row.get("ring", ""),
        })

    result = pd.DataFrame(rows)

    # Compute rank changes
    auto_ranks = _average_ranks(auto_scores)
    rev_ranks = _average_ranks(reviewed_scores)
    result["auto_rank"] = auto_ranks
    result["reviewed_rank"] = rev_ranks
    result["rank_change"] = [
        int(a - r) for a, r in zip(auto_ranks, rev_ranks)
    ]
    result["spearman_rho"] = _spearman_rho(auto_ranks, rev_ranks)

    return result


# ── RQ3: Weight sensitivity ─────────────────────────────────────────────────


def rq3_weight_sensitivity(
    radar_df: pd.DataFrame, cfg: ScoringConfig
) -> pd.DataFrame:
    """For each criterion and delta {-0.10, +0.10}, report rank/ring changes."""
    from radar.scoring import score_dataframe

    scored = radar_df[
        ~radar_df["ring"].isin(NON_SCORED_RINGS)
    ].copy()
    if scored.empty:
        return pd.DataFrame()

    base_weights = {k: c.weight for k, c in cfg.criteria.items()}
    base_result = score_dataframe(scored.copy(), cfg)
    base_order = list(base_result["slug"])
    base_rings = dict(zip(base_result["slug"], base_result["ring"]))
    base_scores = list(base_result["total_score"])
    base_ranks = _average_ranks(base_scores)

    # Map slug → baseline rank (computed once; order is stable)
    base_rank_by_slug = dict(zip(base_order, base_ranks))

    rows: list[dict] = []
    for crit_name in cfg.criteria:
        for delta in [-0.10, 0.10]:
            new_w = max(0.0, min(1.0, base_weights[crit_name] + delta))
            clipped = new_w != base_weights[crit_name] + delta

            # Scale other weights proportionally
            other_total = sum(
                v for k, v in base_weights.items() if k != crit_name
            )
            remaining = 1.0 - new_w
            new_weights = {}
            for k, v in base_weights.items():
                if k == crit_name:
                    new_weights[k] = new_w
                elif other_total > 0:
                    new_weights[k] = v * remaining / other_total
                else:
                    new_weights[k] = remaining / (len(base_weights) - 1)

            alt_result = score_dataframe(
                scored.copy(), cfg, weights=new_weights
            )
            alt_order = list(alt_result["slug"])
            alt_rings = dict(zip(alt_result["slug"], alt_result["ring"]))
            alt_scores = list(alt_result["total_score"])
            alt_ranks = _average_ranks(alt_scores)

            # Align scenario ranks to baseline order by slug (bug fix: was
            # paired by position, giving rho=1 even when rankings changed)
            alt_rank_by_slug = dict(zip(alt_order, alt_ranks))
            paired_base = [
                base_rank_by_slug[s]
                for s in base_order if s in alt_rank_by_slug
            ]
            paired_alt = [
                alt_rank_by_slug[s]
                for s in base_order if s in alt_rank_by_slug
            ]

            rank_changes = sum(
                1 for a, b in zip(base_order, alt_order) if a != b
            )
            max_shift = 0
            for i, slug in enumerate(base_order):
                if slug in alt_order:
                    max_shift = max(
                        max_shift, abs(i - alt_order.index(slug))
                    )

            ring_changes = sum(
                1 for s in base_order
                if base_rings.get(s) != alt_rings.get(s)
            )

            rows.append({
                "criterion": crit_name,
                "delta": delta,
                "new_weight": round(new_w, 4),
                "clipped": clipped,
                "rank_changes": rank_changes,
                "max_rank_shift": max_shift,
                "ring_changes": ring_changes,
                "spearman_vs_baseline": _spearman_rho(paired_base, paired_alt),
            })

    # Summary row
    any_rank = sum(1 for r in rows if r["rank_changes"] > 0)
    any_ring = sum(1 for r in rows if r["ring_changes"] > 0)
    rows.append({
        "criterion": "SUMMARY",
        "delta": pd.NA,
        "new_weight": pd.NA,
        "clipped": pd.NA,
        "rank_changes": any_rank,
        "max_rank_shift": pd.NA,
        "ring_changes": any_ring,
        "spearman_vs_baseline": f"{any_rank}/{len(rows)} scenarios with rank change",
    })

    return pd.DataFrame(rows)


# ── RQ4: Refresh cost ────────────────────────────────────────────────────────


def rq4_refresh_cost(demo: bool = False) -> pd.DataFrame:
    """Review minutes, collection outcomes, offline reproducibility check."""
    rows: list[dict] = []

    # Review minutes
    rpath = review_sheet_path(demo)
    if rpath.exists():
        df = pd.read_csv(rpath)
        if "review_minutes" in df.columns:
            mins = pd.to_numeric(df["review_minutes"], errors="coerce")
            valid = mins.dropna()
            if not valid.empty:
                rows.append({"metric": "mean_review_minutes",
                             "value": str(round(valid.mean(), 2))})
                rows.append({"metric": "median_review_minutes",
                             "value": str(round(valid.median(), 2))})
            else:
                rows.append({"metric": "review_minutes",
                             "value": "not recorded"})
        else:
            rows.append({"metric": "review_minutes",
                         "value": "column missing"})

    # Collection outcomes
    cpath = collection_report_path(demo)
    if cpath.exists():
        cr = pd.read_csv(cpath)
        for outcome in sorted(cr["outcome"].unique()):
            rows.append({
                "metric": f"pages_{outcome}",
                "value": str(len(cr[cr["outcome"] == outcome])),
            })
        from radar.collector import FAILED_OR_BLOCKED
        blocked = cr[cr["outcome"].isin(list(FAILED_OR_BLOCKED))]
        rows.append({"metric": "pages_failed_or_blocked",
                     "value": str(len(blocked))})
        usable = cr[cr["outcome"].isin(["fetched", "cache_hit"])]
        rows.append({"metric": "pages_usable_total",
                     "value": str(len(usable))})

    # Offline reproducibility check
    rd = raw_dir(demo)
    epath = extracted_csv_path(demo)
    radar_path = radar_csv_path(demo)

    if rd.exists() and any(rd.glob("*.json")):
        repro_result = _check_reproducibility(demo)
        rows.append({"metric": "reproducibility", "value": repro_result})
    else:
        rows.append({"metric": "reproducibility",
                     "value": "not checkable: raw cache missing"})

    # File hashes
    if epath.exists():
        h = hashlib.sha256(epath.read_bytes()).hexdigest()[:16]
        rows.append({"metric": "extracted_csv_hash", "value": h})
    if radar_path.exists():
        h = hashlib.sha256(radar_path.read_bytes()).hexdigest()[:16]
        rows.append({"metric": "radar_csv_hash", "value": h})

    return pd.DataFrame(rows)


def _check_reproducibility(demo: bool = False) -> str:
    """Re-extract and re-score in a temp dir; compare sha256 to tracked files."""
    try:
        from radar.collector import collect_all
        from radar.extractor import extract_all
        from radar.review import load_review_sheet
        from radar.scoring import score_dataframe

        startups_cfg = load_startups_config()
        scoring_cfg = load_scoring_config()
        slug_to_name = {s.slug: s.name for s in startups_cfg.startups}

        collected, _ = collect_all(
            startups_cfg, scoring_cfg, offline=True, demo=demo
        )
        rows = extract_all(collected, scoring_cfg, slug_to_name=slug_to_name)
        if not rows:
            return "not checkable: extraction produced 0 rows"

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)

            # Write re-extracted CSV
            repro_extracted = td_path / "extracted.csv"
            pd.DataFrame(rows).to_csv(repro_extracted, index=False)

            # Compare to tracked extracted.csv
            epath = extracted_csv_path(demo)
            extracted_match = False
            if epath.exists():
                orig_hash = hashlib.sha256(epath.read_bytes()).hexdigest()
                repro_hash = hashlib.sha256(
                    repro_extracted.read_bytes()
                ).hexdigest()
                extracted_match = orig_hash == repro_hash

            # Re-score from the review sheet
            rpath = review_sheet_path(demo)
            radar_match = False
            if rpath.exists():
                review_df = load_review_sheet(rpath, include_unreviewed=True)
                if not review_df.empty:
                    dk = "demo" if demo else "real"
                    result = score_dataframe(
                        review_df, scoring_cfg,
                        dataset_kind=dk, include_unreviewed=True,
                    )
                    repro_radar = td_path / "radar.csv"
                    result.to_csv(repro_radar, index=False)

                    radar_path = radar_csv_path(demo)
                    if radar_path.exists():
                        orig_hash = hashlib.sha256(
                            radar_path.read_bytes()
                        ).hexdigest()
                        repro_hash = hashlib.sha256(
                            repro_radar.read_bytes()
                        ).hexdigest()
                        radar_match = orig_hash == repro_hash

            if extracted_match and radar_match:
                return "identical (extracted + radar)"
            parts = []
            parts.append(
                "extracted: " + ("match" if extracted_match else "DIFFERS")
            )
            parts.append(
                "radar: " + ("match" if radar_match else "DIFFERS")
            )
            return "; ".join(parts)

    except Exception as exc:
        return f"not checkable: {exc}"


# ── Report generation ────────────────────────────────────────────────────────


def run_analysis(demo: bool = False) -> None:
    """Run all analyses and write reports."""
    cfg = load_scoring_config()
    radar_path = radar_csv_path(demo)

    reports_dir = Path("reports/demo") if demo else Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    if not radar_path.exists():
        logger.warning("No radar.csv found at %s", radar_path)
        results_md = "# Results\n\nNo scored data available.\n"
        if demo:
            results_md += "\nRun `make demo` to generate demo data.\n"
        else:
            results_md += (
                "\nRun the pipeline and review data first.\n"
            )
        (reports_dir / "results.md").write_text(results_md, encoding="utf-8")
        logger.info("Wrote %s/results.md (no data)", reports_dir)
        return

    radar_df = pd.read_csv(radar_path)
    scored = radar_df[~radar_df["ring"].isin(NON_SCORED_RINGS)]

    if scored.empty:
        results_md = "# Results\n\nNo reviewed/scored data available.\n"
        (reports_dir / "results.md").write_text(results_md, encoding="utf-8")
        logger.info("Wrote %s/results.md (no scored data)", reports_dir)
        return

    is_demo = radar_df.get("dataset_kind", pd.Series(["real"])).iloc[0] == "demo"
    n = len(scored)

    # Compute data-as-of
    all_dates: list[str] = []
    if "source_fetched_at" in radar_df.columns:
        for val in radar_df["source_fetched_at"].dropna():
            all_dates.extend(str(val).split("|"))
    data_as_of = max(d for d in all_dates if d.strip()) if all_dates else "unknown"

    rq1 = rq1_coverage(radar_df, cfg)
    rq1.to_csv(reports_dir / "rq1_coverage.csv", index=False)

    rq2 = rq2_review_effect(radar_df, cfg)
    rq2.to_csv(reports_dir / "rq2_review_effect.csv", index=False)

    rq3 = rq3_weight_sensitivity(radar_df, cfg)
    rq3.to_csv(reports_dir / "rq3_weight_sensitivity.csv", index=False)

    rq4 = rq4_refresh_cost(demo)
    rq4.to_csv(reports_dir / "rq4_refresh_cost.csv", index=False)

    # Build results.md
    data_label = "SYNTHETIC DEMO" if is_demo else "Real"
    results_md = f"# Results ({data_label} data, n={n})\n\n"
    results_md += (
        f"Data as of: {data_as_of}. "
        "Exploratory analysis only — sample size is too small for "
        "statistical claims.\n\n"
    )

    if is_demo:
        results_md += (
            "> **Warning:** These results are from synthetic demo data "
            "and do not represent real start-ups.\n\n"
        )

    results_md += "## RQ1: Coverage\n\n"
    results_md += _df_to_md_table(rq1) + "\n"

    results_md += "## RQ2: Review effect\n\n"
    # Check if any overrides exist
    has_overrides = False
    for crit in cfg.criteria:
        ov_col = f"{crit}_override"
        if ov_col in scored.columns:
            if scored[ov_col].apply(
                lambda v: pd.notna(v) and str(v).strip() != ""
            ).any():
                has_overrides = True
                break
    if not has_overrides:
        results_md += (
            "RQ2 is trivial for this snapshot: no criterion overrides "
            "were applied, so automatic and reviewed scores are identical.\n\n"
        )
    results_md += _df_to_md_table(rq2) + "\n"

    results_md += "## RQ3: Weight sensitivity\n\n"
    if n < 5:
        results_md += (
            f"*n={n} is too small for meaningful sensitivity conclusions.*\n\n"
        )
    results_md += _df_to_md_table(rq3) + "\n"

    results_md += "## RQ4: Refresh cost\n\n"
    results_md += _df_to_md_table(rq4) + "\n"

    # Standing limitations
    results_md += "## Limitations\n\n"
    results_md += (
        "- Keyword matching is context-blind: navigation labels, footers "
        "and bios can match.\n"
        "- theme_fit saturates quickly from a single quadrant.\n"
        "- Maturity vocabulary is narrow.\n"
        "- Human overrides exist for exactly this reason.\n"
        "- Sample size is exploratory (n=5-8), no statistical power.\n"
    )

    (reports_dir / "results.md").write_text(results_md, encoding="utf-8")
    logger.info("Reports written to %s/", reports_dir)

    # Update README only for real data, never for demo
    if not demo:
        _update_readme(results_md, n, data_as_of, is_demo)


def _update_readme(
    results_md: str, n: int, data_as_of: str, is_demo: bool
) -> None:
    """Update README between markers. Loud error if markers are missing."""
    readme_path = Path("README.md")
    if not readme_path.exists():
        logger.warning("README.md not found, skipping results update")
        return

    content = readme_path.read_text(encoding="utf-8")

    # Update results block
    if RESULTS_START not in content or RESULTS_END not in content:
        raise ValueError(
            f"README.md is missing result markers "
            f"({RESULTS_START} / {RESULTS_END}). "
            f"Add them and retry."
        )
    before = content[: content.index(RESULTS_START) + len(RESULTS_START)]
    after = content[content.index(RESULTS_END):]
    content = before + "\n\n" + results_md + "\n" + after

    # Update snapshot block
    if SNAPSHOT_START in content and SNAPSHOT_END in content:
        label = "demo" if is_demo else "real"
        snap = f" n={n}, data as of {data_as_of}, dataset: {label} "
        sbefore = content[: content.index(SNAPSHOT_START) + len(SNAPSHOT_START)]
        safter = content[content.index(SNAPSHOT_END):]
        content = sbefore + snap + safter

    readme_path.write_text(content, encoding="utf-8")
    logger.info("Updated README.md results and snapshot blocks")
