"""Centralised data paths. Every module imports paths from here — no hard-coded paths."""

from pathlib import Path

_PROJECT_ROOT = Path(".")


def data_root(demo: bool = False) -> Path:
    """Return the root data directory for real or demo mode."""
    if demo:
        return _PROJECT_ROOT / "data" / "demo"
    return _PROJECT_ROOT / "data"


def raw_dir(demo: bool = False) -> Path:
    return data_root(demo) / "raw"


def interim_dir(demo: bool = False) -> Path:
    return data_root(demo) / "interim"


def review_dir(demo: bool = False) -> Path:
    return data_root(demo) / "review"


def processed_dir(demo: bool = False) -> Path:
    return data_root(demo) / "processed"


def review_sheet_path(demo: bool = False) -> Path:
    return review_dir(demo) / "review_sheet.csv"


def radar_csv_path(demo: bool = False) -> Path:
    return processed_dir(demo) / "radar.csv"


def extracted_csv_path(demo: bool = False) -> Path:
    return interim_dir(demo) / "extracted.csv"


def collection_report_path(demo: bool = False) -> Path:
    return interim_dir(demo) / "collection_report.csv"


def manifest_path(demo: bool = False) -> Path:
    return raw_dir(demo) / "MANIFEST.csv"


def review_backup_dir(demo: bool = False) -> Path:
    return review_dir(demo) / "backups"


CONFIGS_DIR = _PROJECT_ROOT / "configs"
FIXTURES_DIR = _PROJECT_ROOT / "tests" / "fixtures"
