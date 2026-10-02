"""Transparent, deterministic, rule-based scoring from configs/scoring.yaml."""

import logging
from pathlib import Path

import pandas as pd

from radar.config import ScoringConfig

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path("data/processed")
RADAR_FILE = PROCESSED_DIR / "radar.csv"


def _criterion_score(hits: int, saturation: int) -> float:
    """Score a single criterion 0-5: min(5, hits/saturation * 5)."""
    return min(5.0, (hits / saturation) * 5.0)


def _assign_theme(row: pd.Series, quadrant_ids: list[str]) -> str:
    """Assign theme by highest quadrant hit count. Ties go to alphabetically first id."""
    best_id = ""
    best_hits = -1
    for qid in sorted(quadrant_ids):
        hits_col = f"{qid}_hits"
        hits = int(row.get(hits_col, 0))
        if hits > best_hits:
            best_hits = hits
            best_id = qid
    return best_id


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


def score_row(
    row: pd.Series,
    cfg: ScoringConfig,
    weights: dict[str, float] | None = None,
) -> dict:
    """Score a single reviewed row. Returns a dict with score breakdown."""
    if weights is None:
        weights = {k: c.weight for k, c in cfg.criteria.items()}

    # Normalise weights to sum to 1
    total_weight = sum(weights.values())
    if total_weight > 0:
        weights = {k: v / total_weight for k, v in weights.items()}

    scores: dict[str, float] = {}
    weighted_sum = 0.0

    for crit_name, crit_cfg in cfg.criteria.items():
        override_col = f"{crit_name}_override"
        hits_col = f"{crit_name}_hits"

        override_val = row.get(override_col)
        if pd.notna(override_val) and str(override_val).strip() != "":
            score = float(override_val)
            logger.debug("Using override for %s.%s: %.1f", row.get("slug", "?"), crit_name, score)
        else:
            hits = int(row.get(hits_col, 0))
            score = _criterion_score(hits, crit_cfg.saturation)

        score = max(0.0, min(5.0, score))
        scores[f"{crit_name}_score"] = score
        weighted_sum += score * weights.get(crit_name, 0.0)

    total_score = (weighted_sum / 5.0) * 100.0

    # Theme assignment
    theme_override = row.get("theme_override")
    if pd.notna(theme_override) and str(theme_override).strip() != "":
        theme = str(theme_override).strip()
    else:
        theme = _assign_theme(row, list(cfg.quadrants.keys()))

    ring = _ring_label(total_score, cfg)

    return {
        **scores,
        "total_score": round(total_score, 2),
        "theme": theme,
        "ring": ring,
    }


def score_dataframe(
    df: pd.DataFrame,
    cfg: ScoringConfig,
    weights: dict[str, float] | None = None,
    dataset_kind: str = "real",
) -> pd.DataFrame:
    """Score all rows and return the full radar DataFrame."""
    if df.empty:
        logger.warning("No rows to score")
        return df

    score_rows = []
    for _, row in df.iterrows():
        score_rows.append(score_row(row, cfg, weights))

    scores_df = pd.DataFrame(score_rows)
    result = pd.concat([df.reset_index(drop=True), scores_df], axis=1)
    result["dataset_kind"] = dataset_kind

    # Stable sort by total_score descending, then slug ascending
    result = result.sort_values(
        ["total_score", "slug"], ascending=[False, True]
    ).reset_index(drop=True)

    return result


def save_radar(df: pd.DataFrame, output_path: Path | None = None) -> Path:
    """Save the scored radar DataFrame to CSV."""
    output_path = output_path or RADAR_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info("Radar saved to %s (%d rows)", output_path, len(df))
    return output_path
