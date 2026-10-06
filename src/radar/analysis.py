"""Analysis functions for RQ1-RQ4 and the sensitivity table."""

from __future__ import annotations

import hashlib
import logging
import math
from pathlib import Path

import pandas as pd

from radar.config import ScoringConfig, load_scoring_config
from radar.paths import (
    collection_report_path,
    extracted_csv_path,
    radar_csv_path,
    review_sheet_path,
)

logger = logging.getLogger(__name__)


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
    """Per criterion: share overridden, mean auto score, mean evidence_quality score."""
    scored = radar_df[radar_df["ring"] != "Unreviewed"].copy()
    if scored.empty:
        return pd.DataFrame()

    rows = []
    for crit_name in cfg.criteria:
        ov_col = f"{crit_name}_override"
        score_col = f"{crit_name}_score"
        n = len(scored)
        overridden = 0
        if ov_col in scored.columns:
            overridden = scored[ov_col].apply(
                lambda v: pd.notna(v) and str(v).strip() != ""
            ).sum()
        mean_score = scored[score_col].mean() if score_col in scored.columns else 0
        rows.append({
            "criterion": crit_name,
            "share_overridden": round(overridden / n, 4) if n > 0 else 0,
            "mean_auto_score": round(mean_score, 4),
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
    })

    # Total correction share
    total_fields = n * (len(cfg.criteria) + 1)  # +1 for theme
    total_overridden = sum(r["share_overridden"] * n for r in rows)
    rows.append({
        "criterion": "TOTAL",
        "share_overridden": round(total_overridden / total_fields, 4)
        if total_fields > 0 else 0,
        "mean_auto_score": pd.NA,
    })

    return pd.DataFrame(rows)


# ── RQ2: Review effect ───────────────────────────────────────────────────────


def rq2_review_effect(
    radar_df: pd.DataFrame, cfg: ScoringConfig
) -> pd.DataFrame:
    """Compare automatic vs reviewed scores; report rank/ring changes."""
    from radar.scoring import score_row

    scored = radar_df[radar_df["ring"] != "Unreviewed"].copy()
    if scored.empty:
        return pd.DataFrame()

    rows = []
    auto_scores = []
    reviewed_scores = []

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

    scored = radar_df[radar_df["ring"] != "Unreviewed"].copy()
    if scored.empty:
        return pd.DataFrame()

    base_weights = {k: c.weight for k, c in cfg.criteria.items()}
    base_result = score_dataframe(scored.copy(), cfg)
    base_order = list(base_result["slug"])
    base_rings = dict(zip(base_result["slug"], base_result["ring"]))
    base_scores = list(base_result["total_score"])
    base_ranks = _average_ranks(base_scores)

    rows = []
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
                "spearman_vs_baseline": _spearman_rho(base_ranks, alt_ranks),
            })

    return pd.DataFrame(rows)


# ── RQ4: Refresh cost ────────────────────────────────────────────────────────


def rq4_refresh_cost(demo: bool = False) -> pd.DataFrame:
    """Review minutes and collection outcome stats."""
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
        for outcome in cr["outcome"].unique():
            rows.append({
                "metric": f"pages_{outcome}",
                "value": str(len(cr[cr["outcome"] == outcome])),
            })
        blocked = cr[cr["outcome"].isin([
            "robots_denied", "denylist", "http_error",
            "network_error", "cached_failure",
        ])]
        rows.append({"metric": "pages_failed_or_blocked",
                     "value": str(len(blocked))})

    # Offline reproducibility
    epath = extracted_csv_path(demo)
    radar_path = radar_csv_path(demo)
    if epath.exists():
        h = hashlib.sha256(epath.read_bytes()).hexdigest()[:16]
        rows.append({"metric": "extracted_csv_hash", "value": h})
    if radar_path.exists():
        h = hashlib.sha256(radar_path.read_bytes()).hexdigest()[:16]
        rows.append({"metric": "radar_csv_hash", "value": h})

    return pd.DataFrame(rows)


# ── Report generation ────────────────────────────────────────────────────────


def run_analysis(demo: bool = False) -> None:
    """Run all analyses and write reports."""
    cfg = load_scoring_config()
    radar_path = radar_csv_path(demo)

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

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
        logger.info("Wrote reports/results.md (no data)")
        return

    radar_df = pd.read_csv(radar_path)
    scored = radar_df[radar_df["ring"] != "Unreviewed"]

    if scored.empty:
        results_md = "# Results\n\nNo reviewed/scored data available.\n"
        (reports_dir / "results.md").write_text(results_md, encoding="utf-8")
        logger.info("Wrote reports/results.md (no scored data)")
        return

    is_demo = radar_df.get("dataset_kind", pd.Series(["real"])).iloc[0] == "demo"

    rq1 = rq1_coverage(radar_df, cfg)
    rq1.to_csv(reports_dir / "rq1_coverage.csv", index=False)

    rq2 = rq2_review_effect(radar_df, cfg)
    rq2.to_csv(reports_dir / "rq2_review_effect.csv", index=False)

    rq3 = rq3_weight_sensitivity(radar_df, cfg)
    rq3.to_csv(reports_dir / "rq3_weight_sensitivity.csv", index=False)

    rq4 = rq4_refresh_cost(demo)
    rq4.to_csv(reports_dir / "rq4_refresh_cost.csv", index=False)

    # Build results.md
    n = len(scored)
    data_label = "SYNTHETIC DEMO" if is_demo else "Real"
    results_md = f"# Results ({data_label} data, n={n})\n\n"

    if is_demo:
        results_md += (
            "> **Warning:** These results are from synthetic demo data "
            "and do not represent real start-ups.\n\n"
        )

    results_md += "## RQ1: Coverage\n\n"
    results_md += rq1.to_markdown(index=False) + "\n\n"

    results_md += "## RQ2: Review effect\n\n"
    results_md += rq2.to_markdown(index=False) + "\n\n"

    results_md += "## RQ3: Weight sensitivity\n\n"
    results_md += rq3.to_markdown(index=False) + "\n\n"

    results_md += "## RQ4: Refresh cost\n\n"
    results_md += rq4.to_markdown(index=False) + "\n\n"

    (reports_dir / "results.md").write_text(results_md, encoding="utf-8")
    logger.info("Reports written to reports/")

    # Update README between markers
    readme_path = Path("README.md")
    if readme_path.exists():
        content = readme_path.read_text(encoding="utf-8")
        start_marker = "<!-- RESULTS:START -->"
        end_marker = "<!-- RESULTS:END -->"
        if start_marker in content and end_marker in content:
            before = content[: content.index(start_marker) + len(start_marker)]
            after = content[content.index(end_marker):]
            block = f"\n\n{results_md}\n"
            readme_path.write_text(
                before + block + after, encoding="utf-8"
            )
            logger.info("Updated README.md results block")
