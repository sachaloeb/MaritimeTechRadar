"""Generate, merge, and load the human review CSV."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from radar.paths import review_sheet_path

logger = logging.getLogger(__name__)

# Columns that reviewers fill in — never overwritten by pipeline re-runs
HUMAN_COLS = [
    "maritime_relevance_override",
    "theme_fit_override",
    "maturity_signals_override",
    "evidence_quality_override",
    "theme_override",
    "notes",
    "reviewed",
    "excluded",
    "exclusion_reason",
    "review_minutes",
]


def _backup_sheet(path: Path) -> Path:
    """Copy existing review sheet to backups/ with UTC timestamp."""
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = backup_dir / f"review_sheet_{ts}.csv"
    shutil.copy2(path, dest)
    logger.info("Backed up review sheet to %s", dest)
    return dest


def generate_review_sheet(
    extracted_rows: list[dict],
    output_path: Path | None = None,
    demo: bool = False,
    force_new: bool = False,
) -> Path:
    """Write or merge extracted data into a review CSV.

    If the sheet exists and force_new is False:
      - Back up the existing sheet
      - Merge by slug: keep all human columns from existing rows,
        refresh extracted columns, add new slugs as unreviewed,
        keep removed slugs but log a warning.
    """
    output_path = output_path or review_sheet_path(demo)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    new_df = pd.DataFrame(extracted_rows)

    # Ensure all human columns exist in new_df with defaults
    for col in HUMAN_COLS:
        if col not in new_df.columns:
            if col in ("reviewed", "excluded"):
                new_df[col] = False
            elif col == "review_minutes":
                new_df[col] = pd.NA
            else:
                new_df[col] = ""

    if output_path.exists() and force_new:
        _backup_sheet(output_path)
        # Fall through to fresh write below

    if output_path.exists() and not force_new:
        _backup_sheet(output_path)
        existing = pd.read_csv(output_path)

        if "slug" in existing.columns and "slug" in new_df.columns:
            # Merge: keep human columns from existing, refresh extracted
            existing_slugs = set(existing["slug"].tolist())
            new_slugs = set(new_df["slug"].tolist())

            # Warn about removed slugs
            removed = existing_slugs - new_slugs
            for s in sorted(removed):
                logger.warning(
                    "Slug '%s' no longer in extracted data but kept in review sheet", s
                )

            # Build merged dataframe
            extracted_cols = [
                c for c in new_df.columns if c not in HUMAN_COLS
            ]

            # For existing slugs: update extracted columns, keep human columns
            merged_rows = []
            for _, new_row in new_df.iterrows():
                slug = new_row["slug"]
                existing_match = existing[existing["slug"] == slug]
                if not existing_match.empty:
                    row_dict = {}
                    # Take extracted columns from new data
                    for c in extracted_cols:
                        row_dict[c] = new_row.get(c, "")
                    # Take human columns from existing data
                    ex_row = existing_match.iloc[0]
                    for c in HUMAN_COLS:
                        if c in ex_row.index:
                            row_dict[c] = ex_row[c]
                        else:
                            row_dict[c] = new_row.get(c, "")
                    merged_rows.append(row_dict)
                else:
                    merged_rows.append(new_row.to_dict())

            # Keep removed slugs from existing
            for _, ex_row in existing[
                existing["slug"].isin(removed)
            ].iterrows():
                merged_rows.append(ex_row.to_dict())

            result = pd.DataFrame(merged_rows)
            result.to_csv(output_path, index=False)
            logger.info(
                "Review sheet merged to %s (%d rows: %d updated, %d new, %d kept-removed)",
                output_path, len(result),
                len(existing_slugs & new_slugs),
                len(new_slugs - existing_slugs),
                len(removed),
            )
            return output_path

    new_df.to_csv(output_path, index=False)
    logger.info("Review sheet written to %s (%d rows)", output_path, len(new_df))
    return output_path


def load_review_sheet(
    path: Path | None = None,
    demo: bool = False,
    include_unreviewed: bool = False,
) -> pd.DataFrame:
    """Load the review CSV. By default, only returns rows where reviewed=True."""
    path = path or review_sheet_path(demo)
    if not path.exists():
        raise FileNotFoundError(
            f"Review sheet not found at {path}. Run 'radar run' first."
        )

    df = pd.read_csv(path)

    # Normalise boolean columns
    for col in ("reviewed", "excluded"):
        if col in df.columns:
            df[col] = (
                df[col].astype(str).str.strip().str.lower()
                .isin(["true", "1", "yes"])
            )
        else:
            df[col] = False

    if not include_unreviewed:
        reviewed = df[df["reviewed"] & ~df["excluded"]]
        logger.info(
            "Loaded %d reviewed (non-excluded) rows out of %d total from %s",
            len(reviewed), len(df), path,
        )
        return reviewed

    logger.info("Loaded all %d rows from %s", len(df), path)
    return df
