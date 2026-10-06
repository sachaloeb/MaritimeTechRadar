"""Transparent, deterministic, rule-based scoring from configs/scoring.yaml."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from radar.config import ScoringConfig

logger = logging.getLogger(__name__)


def _criterion_score(hits: int, saturation: int) -> float:
    """Score a single criterion 0-5: min(5, hits/saturation * 5)."""
    return min(5.0, (hits / saturation) * 5.0)


def _assign_theme(row: pd.Series, quadrant_ids: list[str]) -> str:
    """Assign theme by highest quadrant hit count.

    Ties go to alphabetically first id.
    All-zero -> "unassigned" (D7 fix).
    """
    best_id = ""
    best_hits = 0  # Start at 0 so all-zero gives "unassigned"
    for qid in sorted(quadrant_ids):
        hits_col = f"{qid}_hits"
        val = row.get(hits_col)
        if pd.isna(val):
            raise ValueError(
                f"Missing column '{hits_col}' for slug '{row.get('slug', '?')}'"
            )
        hits = int(val)
        if hits > best_hits:
            best_hits = hits
            best_id = qid
    return best_id if best_id else "unassigned"


def _ring_label(total_score: float, cfg: ScoringConfig) -> str:
    rings = cfg.rings
    if total_score >= rings.pilot_ready:
        return "Pilot-ready"
    elif total_score >= rings.promising:
        return "Promising"
    elif total_score >= rings.early:
        return "Early"
    else:
        return "Watch"


def _validate_override(
    value: object, slug: str, column: str, valid_range: tuple[float, float] = (0.0, 5.0)
) -> float | None:
    """Validate a numeric override. Returns float or None if blank."""
    if pd.isna(value) or str(value).strip() == "":
        return None
    try:
        fval = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Invalid override for slug '{slug}', column '{column}': "
            f"expected a number in [{valid_range[0]}, {valid_range[1]}], got '{value}'"
        ) from exc
    if not (valid_range[0] <= fval <= valid_range[1]):
        raise ValueError(
            f"Override out of range for slug '{slug}', column '{column}': "
            f"{fval} not in [{valid_range[0]}, {valid_range[1]}]"
        )
    return fval


def _validate_theme_override(
    value: object, slug: str, valid_themes: set[str]
) -> str | None:
    """Validate theme_override. Returns theme id or None if blank."""
    if pd.isna(value) or str(value).strip() == "":
        return None
    theme = str(value).strip()
    if theme not in valid_themes:
        raise ValueError(
            f"Invalid theme_override for slug '{slug}': '{theme}' "
            f"not in {sorted(valid_themes)}"
        )
    return theme


def score_row(
    row: pd.Series,
    cfg: ScoringConfig,
    weights: dict[str, float] | None = None,
) -> dict:
    """Score a single reviewed row. Returns a dict with score breakdown."""
    slug = str(row.get("slug", "?"))
    valid_themes = set(cfg.quadrants.keys())

    if weights is None:
        weights = {k: c.weight for k, c in cfg.criteria.items()}

    # Normalise weights to sum to 1
    total_weight = sum(weights.values())
    if total_weight == 0:
        raise ValueError(
            "All criterion weights are zero — cannot score"
        )
    weights = {k: v / total_weight for k, v in weights.items()}

    scores: dict[str, float] = {}
    overridden: list[str] = []
    weighted_sum = 0.0

    for crit_name, crit_cfg in cfg.criteria.items():
        override_col = f"{crit_name}_override"
        hits_col = f"{crit_name}_hits"

        override_val = _validate_override(
            row.get(override_col), slug, override_col
        )

        if override_val is not None:
            score = override_val
            overridden.append(crit_name)
            logger.debug(
                "Using override for %s.%s: %.1f", slug, crit_name, score
            )
        else:
            hits_val = row.get(hits_col)
            if pd.isna(hits_val):
                raise ValueError(
                    f"Missing column '{hits_col}' for slug '{slug}'"
                )
            hits = int(hits_val)
            score = _criterion_score(hits, crit_cfg.saturation)

        score = max(0.0, min(5.0, score))
        scores[f"{crit_name}_score"] = score
        weighted_sum += score * weights.get(crit_name, 0.0)

    total_score = (weighted_sum / 5.0) * 100.0

    # Theme assignment
    theme_ov = _validate_theme_override(
        row.get("theme_override"), slug, valid_themes
    )
    if theme_ov is not None:
        theme = theme_ov
        overridden.append("theme")
    else:
        theme = _assign_theme(row, list(cfg.quadrants.keys()))

    ring = _ring_label(total_score, cfg)

    return {
        **scores,
        "total_score": round(total_score, 2),
        "theme": theme,
        "ring": ring,
        "overridden_fields": "|".join(sorted(overridden)),
    }


def score_dataframe(
    df: pd.DataFrame,
    cfg: ScoringConfig,
    weights: dict[str, float] | None = None,
    dataset_kind: str = "real",
    include_unreviewed: bool = False,
) -> pd.DataFrame:
    """Score reviewed rows. Optionally include unreviewed rows with empty scores.

    Excluded rows are never included.
    """
    if df.empty:
        logger.warning("No rows to score")
        return df

    # Drop any pre-existing output columns to avoid duplicates on re-scoring
    output_cols = (
        ["total_score", "theme", "ring", "dataset_kind", "overridden_fields"]
        + [f"{c}_score" for c in cfg.criteria]
    )
    df = df.drop(columns=[c for c in output_cols if c in df.columns])

    # Normalise reviewed/excluded columns
    for col in ("reviewed", "excluded"):
        if col in df.columns:
            df[col] = (
                df[col].astype(str).str.strip().str.lower()
                .isin(["true", "1", "yes"])
            )
        else:
            df[col] = False

    # Split: exclude excluded rows entirely
    non_excluded = df[~df["excluded"]].copy()
    reviewed = non_excluded[non_excluded["reviewed"]].copy()
    unreviewed = non_excluded[~non_excluded["reviewed"]].copy()

    # Score reviewed rows
    score_rows = []
    for _, row in reviewed.iterrows():
        score_rows.append(score_row(row, cfg, weights))

    if score_rows:
        scores_df = pd.DataFrame(score_rows)
        scored = pd.concat(
            [reviewed.reset_index(drop=True), scores_df], axis=1
        )
    else:
        scored = reviewed.copy()

    scored["dataset_kind"] = dataset_kind

    if include_unreviewed and not unreviewed.empty:
        # Add unreviewed with empty score columns and ring "Unreviewed"
        for col in [f"{c}_score" for c in cfg.criteria]:
            if col not in unreviewed.columns:
                unreviewed[col] = pd.NA
        for col in ["total_score", "theme", "ring", "overridden_fields"]:
            if col not in unreviewed.columns:
                unreviewed[col] = pd.NA
        unreviewed["ring"] = "Unreviewed"
        unreviewed["dataset_kind"] = dataset_kind

        # Assign theme for unreviewed if possible (for display)
        for idx, row in unreviewed.iterrows():
            try:
                unreviewed.at[idx, "theme"] = _assign_theme(
                    row, list(cfg.quadrants.keys())
                )
            except ValueError:
                unreviewed.at[idx, "theme"] = "unassigned"

        result = pd.concat([scored, unreviewed], ignore_index=True)
    else:
        result = scored

    # Stable sort: scored rows by total_score desc then slug asc;
    # unreviewed at the end
    if not result.empty:
        result = result.sort_values(
            ["ring", "total_score", "slug"],
            ascending=[True, False, True],
            key=lambda col: (
                col.map({
                    "Pilot-ready": 0, "Promising": 1, "Early": 2,
                    "Watch": 3, "Unreviewed": 4,
                }) if col.name == "ring" else col
            ),
            na_position="last",
        ).reset_index(drop=True)

    return result


def save_radar(
    df: pd.DataFrame, output_path: Path | None = None, demo: bool = False
) -> Path:
    """Save the scored radar DataFrame to CSV."""
    from radar.paths import radar_csv_path
    output_path = output_path or radar_csv_path(demo)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info("Radar saved to %s (%d rows)", output_path, len(df))
    return output_path
