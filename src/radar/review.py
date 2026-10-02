"""Generate and load the human review CSV."""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REVIEW_DIR = Path("data/review")
REVIEW_FILE = REVIEW_DIR / "review_sheet.csv"

# Override columns that reviewers can fill in
OVERRIDE_COLS = [
    "maritime_relevance_override",
    "theme_fit_override",
    "maturity_signals_override",
    "evidence_quality_override",
    "theme_override",
    "notes",
    "reviewed",
]


def generate_review_sheet(
    extracted_rows: list[dict],
    output_path: Path | None = None,
) -> Path:
    """Write extracted data to a review CSV with empty override columns."""
    output_path = output_path or REVIEW_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(extracted_rows)

    for col in OVERRIDE_COLS:
        if col not in df.columns:
            if col == "reviewed":
                df[col] = False
            else:
                df[col] = ""

    df.to_csv(output_path, index=False)
    logger.info("Review sheet written to %s (%d rows)", output_path, len(df))
    return output_path


def load_review_sheet(
    path: Path | None = None,
    include_unreviewed: bool = False,
) -> pd.DataFrame:
    """Load the review CSV. By default, only returns rows where reviewed=True."""
    path = path or REVIEW_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Review sheet not found at {path}. Run 'radar run' first to generate it."
        )

    df = pd.read_csv(path)

    # Normalise the reviewed column
    df["reviewed"] = df["reviewed"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])

    if not include_unreviewed:
        reviewed = df[df["reviewed"]]
        logger.info(
            "Loaded %d reviewed rows out of %d total from %s",
            len(reviewed),
            len(df),
            path,
        )
        return reviewed

    logger.info("Loaded all %d rows from %s", len(df), path)
    return df
