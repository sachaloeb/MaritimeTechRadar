"""CLI: radar {collect, extract, review-sheet, score, run, validate, analyse, status}."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from radar.config import load_scoring_config, load_startups_config
from radar.logging_setup import setup_logging
from radar.paths import (
    FIXTURES_DIR,
    collection_report_path,
    extracted_csv_path,
    manifest_path,
    raw_dir,
    review_sheet_path,
)

__version__ = "0.1.0"

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar",
        description="Maritime Tech Radar: config-driven pipeline for ranking "
        "public maritime/port-tech start-ups.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Subcommands with their flags
    collect_p = sub.add_parser(
        "collect", help="Fetch pages from configured URLs"
    )
    collect_p.add_argument("--refresh", action="store_true",
                           help="Re-fetch even if cache exists")
    collect_p.add_argument("--offline", action="store_true",
                           help="Use cached pages only, no network")
    collect_p.add_argument("--demo", "--fixtures", action="store_true",
                           dest="demo", help="Use demo/fixture data")

    extract_p = sub.add_parser(
        "extract", help="Parse cached HTML into structured fields"
    )
    extract_p.add_argument("--offline", action="store_true",
                           help="Use cached pages only")
    extract_p.add_argument("--demo", "--fixtures", action="store_true",
                           dest="demo", help="Use demo data")

    review_p = sub.add_parser(
        "review-sheet", help="Generate or merge the human review CSV"
    )
    review_p.add_argument("--demo", "--fixtures", action="store_true",
                          dest="demo", help="Use demo data")
    review_p.add_argument("--force-new", action="store_true",
                          help="Start a fresh sheet (backs up existing)")

    score_p = sub.add_parser(
        "score", help="Score reviewed rows → radar.csv"
    )
    score_p.add_argument("--demo", "--fixtures", action="store_true",
                         dest="demo", help="Use demo data")

    run_p = sub.add_parser(
        "run", help="collect → extract → review-sheet (stops for review)"
    )
    run_p.add_argument("--refresh", action="store_true")
    run_p.add_argument("--offline", action="store_true")
    run_p.add_argument("--demo", "--fixtures", action="store_true",
                       dest="demo", help="Use demo data")
    run_p.add_argument("--force-new", action="store_true")

    validate_p = sub.add_parser(
        "validate", help="Check configs, overrides, and data integrity"
    )
    validate_p.add_argument("--demo", "--fixtures", action="store_true",
                            dest="demo", help="Validate demo data")

    analyse_p = sub.add_parser(
        "analyse", help="Run RQ1-RQ4 analysis and write reports"
    )
    analyse_p.add_argument("--demo", "--fixtures", action="store_true",
                           dest="demo", help="Analyse demo data")

    status_p = sub.add_parser(
        "status", help="Show per-start-up pipeline status (read-only)"
    )
    status_p.add_argument("--demo", "--fixtures", action="store_true",
                          dest="demo", help="Show demo status")

    return parser


# ── Shared validation ────────────────────────────────────────────────────────


def validate_state(
    demo: bool = False,
) -> tuple[list[str], list[str]]:
    """Shared validation used by both ``radar validate`` and ``radar score``.

    Returns (errors, warnings).  Errors mean the pipeline should refuse to
    proceed.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── Config validation ──────────────────────────────────────────────
    try:
        startups_cfg = load_startups_config()
    except Exception as exc:
        errors.append(f"startups.yaml: {exc}")
        return errors, warnings

    try:
        scoring_cfg = load_scoring_config()
    except Exception as exc:
        errors.append(f"scoring.yaml: {exc}")
        return errors, warnings

    # Denylisted URLs
    from radar.collector import _is_denied
    for s in startups_cfg.startups:
        for url in s.urls:
            if _is_denied(url, scoring_cfg.denylist):
                errors.append(
                    f"Denylisted URL in config: {url} (slug: {s.slug})"
                )

    # ── Review sheet checks ────────────────────────────────────────────
    rpath = review_sheet_path(demo)
    if not rpath.exists():
        warnings.append(f"Review sheet not found at {rpath}")
        return errors, warnings

    df = pd.read_csv(rpath)

    # Normalise booleans
    for col in ("reviewed", "excluded"):
        if col in df.columns:
            df[col] = (
                df[col].astype(str).str.strip().str.lower()
                .isin(["true", "1", "yes"])
            )
        else:
            df[col] = False

    # Excluded without reason
    if "exclusion_reason" in df.columns:
        excluded = df[df["excluded"]]
        missing_reason = excluded[
            excluded["exclusion_reason"].isna()
            | (excluded["exclusion_reason"].astype(str).str.strip() == "")
        ]
        for _, row in missing_reason.iterrows():
            errors.append(
                f"Excluded row '{row['slug']}' has no exclusion_reason"
            )

    # Override validation
    valid_themes = set(scoring_cfg.quadrants.keys())
    reviewed = df[df["reviewed"] & ~df["excluded"]]
    for _, row in reviewed.iterrows():
        slug = str(row.get("slug", "?"))
        for crit in scoring_cfg.criteria:
            ov = row.get(f"{crit}_override")
            if pd.notna(ov) and str(ov).strip() != "":
                try:
                    v = float(ov)
                    if not (0 <= v <= 5):
                        errors.append(
                            f"{slug}: {crit}_override={v} not in [0, 5]"
                        )
                except ValueError:
                    errors.append(
                        f"{slug}: {crit}_override='{ov}' not a number"
                    )

        tov = row.get("theme_override")
        if pd.notna(tov) and str(tov).strip() != "":
            if str(tov).strip() not in valid_themes:
                errors.append(
                    f"{slug}: theme_override='{tov}' not a valid theme"
                )

    # Source count check (real mode only)
    if not demo and "source_count" in df.columns:
        low = reviewed[reviewed["source_count"] < 2]
        for _, row in low.iterrows():
            errors.append(
                f"Reviewed row '{row['slug']}' has source_count="
                f"{int(row['source_count'])} < 2 (real mode requires >=2)"
            )

    # ── Warnings ───────────────────────────────────────────────────────
    non_excluded = df[~df["excluded"]]
    n_active = len(non_excluded)
    if n_active < 5:
        warnings.append(f"Only {n_active} non-excluded start-ups (recommend 5-8)")
    elif n_active > 8:
        warnings.append(f"{n_active} non-excluded start-ups (recommend 5-8)")

    unreviewed = non_excluded[~non_excluded["reviewed"]]
    if not unreviewed.empty:
        slugs = unreviewed["slug"].tolist()
        warnings.append(f"Unreviewed rows remain: {slugs}")

    # Nominal review check
    for _, row in reviewed.iterrows():
        slug = str(row.get("slug", "?"))
        has_override = False
        for crit in scoring_cfg.criteria:
            ov = row.get(f"{crit}_override")
            if pd.notna(ov) and str(ov).strip() != "":
                has_override = True
                break
        tov = row.get("theme_override")
        if pd.notna(tov) and str(tov).strip() != "":
            has_override = True
        notes = row.get("notes", "")
        has_notes = pd.notna(notes) and str(notes).strip() != ""
        rm = row.get("review_minutes")
        has_minutes = pd.notna(rm) and str(rm).strip() != ""
        if not has_override and not has_notes and not has_minutes:
            warnings.append(
                f"{slug}: reviewed with no overrides, no notes, "
                f"no review_minutes (review may be nominal)"
            )

    # Zero usable pages not excluded
    if "source_count" in df.columns:
        zero_pages = non_excluded[non_excluded["source_count"] == 0]
        for _, row in zero_pages.iterrows():
            warnings.append(
                f"{row['slug']}: zero usable pages, not yet excluded"
            )

    # ── Evidence quality invariant ─────────────────────────────────────────
    if "evidence_quality_pages" not in df.columns:
        warnings.append(
            "evidence_quality_pages column absent from review sheet — "
            "run `radar run --offline && radar score` to regenerate"
        )
    elif (
        "evidence_quality_hits" in df.columns
        and "evidence_quality_matched" in df.columns
    ):
        for _, row in df.iterrows():
            slug = str(row.get("slug", "?"))
            hits = row.get("evidence_quality_hits")
            pages = row.get("evidence_quality_pages")
            if pd.isna(hits) or pd.isna(pages):
                continue
            matched_raw = row.get("evidence_quality_matched", "")
            matched_str = "" if pd.isna(matched_raw) else str(matched_raw)
            kw_count = len([k for k in matched_str.split("|") if k.strip()])
            expected = int(pages) + kw_count
            actual = int(hits)
            if actual != expected:
                errors.append(
                    f"{slug}: evidence_quality_hits={actual} != "
                    f"evidence_quality_pages={int(pages)} + "
                    f"{kw_count} keywords (expected {expected})"
                )

    return errors, warnings


# ── Fixture loading ──────────────────────────────────────────────────────────


def _load_fixtures(
    scoring_cfg: Any, demo: bool = True
) -> tuple[dict[str, list[Path]], dict[str, str]]:
    """Build collected dict from test fixture HTML files.

    Returns (collected, slug_to_name).
    """
    from radar.collector import url_to_cache_path

    fixture_htmls = list(FIXTURES_DIR.glob("*.html"))
    if not fixture_htmls:
        logger.error("No fixture HTML files in %s", FIXTURES_DIR)
        sys.exit(1)

    rd = raw_dir(demo)
    rd.mkdir(parents=True, exist_ok=True)

    collected: dict[str, list[Path]] = {}
    slug_to_name: dict[str, str] = {}

    for html_path in sorted(fixture_htmls):
        if html_path.stem == "empty_page":
            continue
        slug = f"demo-{html_path.stem.replace('_', '-')}"
        name = html_path.stem.replace("_", " ").title() + " (Demo)"
        url = f"https://demo.example.com/{html_path.stem}"
        cache_path = url_to_cache_path(url, demo)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        content = html_path.read_text(encoding="utf-8")
        record = {
            "url": url,
            "fetched_at": "2026-01-15T12:00:00+00:00",
            "http_status": 200,
            "content_hash": "fixture",
            "error": None,
            "content": content,
        }
        cache_path.write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
        collected[slug] = [cache_path]
        slug_to_name[slug] = name

    return collected, slug_to_name


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_collect(args: argparse.Namespace) -> dict[str, list[Path]]:
    from radar.collector import (
        collect_all,
        write_collection_report,
        write_manifest,
    )

    startups_cfg = load_startups_config()
    scoring_cfg = load_scoring_config()

    if not startups_cfg.startups:
        logger.error(
            "No start-ups in configs/startups.yaml. Add 5-8 entries first."
        )
        sys.exit(1)

    collected, results = collect_all(
        startups_cfg, scoring_cfg,
        refresh=getattr(args, "refresh", False),
        offline=getattr(args, "offline", False),
        demo=args.demo,
    )
    total = sum(len(v) for v in collected.values())
    logger.info(
        "Collection: %d usable pages for %d start-ups", total, len(collected)
    )

    write_collection_report(results, collection_report_path(args.demo))
    write_manifest(results, manifest_path(args.demo))

    return collected


def cmd_extract(
    args: argparse.Namespace,
    collected: dict[str, list[Path]] | None = None,
    slug_to_name: dict[str, str] | None = None,
) -> list[dict]:
    from radar.extractor import extract_all

    scoring_cfg = load_scoring_config()

    if args.demo and collected is None:
        collected, slug_to_name = _load_fixtures(scoring_cfg, demo=True)
    elif collected is None:
        startups_cfg = load_startups_config()
        if not startups_cfg.startups:
            logger.error("No start-ups configured.")
            sys.exit(1)
        if slug_to_name is None:
            slug_to_name = {s.slug: s.name for s in startups_cfg.startups}
        from radar.collector import collect_all
        collected, _ = collect_all(
            startups_cfg, scoring_cfg, offline=True, demo=args.demo
        )

    rows = extract_all(collected, scoring_cfg, slug_to_name=slug_to_name)
    if not rows:
        logger.error("No data extracted.")
        sys.exit(1)

    interim_path = extracted_csv_path(args.demo)
    interim_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(interim_path, index=False)
    logger.info("Extracted %d rows to %s", len(rows), interim_path)
    return rows


def cmd_review_sheet(
    args: argparse.Namespace,
    extracted_rows: list[dict] | None = None,
) -> Path:
    from radar.review import generate_review_sheet

    if extracted_rows is None:
        ipath = extracted_csv_path(args.demo)
        if not ipath.exists():
            logger.error("No extracted data. Run 'radar extract' first.")
            sys.exit(1)
        extracted_rows = pd.read_csv(ipath).to_dict("records")

    path = generate_review_sheet(
        extracted_rows,
        demo=args.demo,
        force_new=getattr(args, "force_new", False),
    )
    logger.info(
        "Review sheet: %s\n"
        "  → Set 'reviewed' to 'true' for approved rows.\n"
        "  → Then run 'radar score' to generate the radar.",
        path,
    )
    return path


def cmd_score(args: argparse.Namespace) -> None:
    from radar.review import load_review_sheet
    from radar.scoring import save_radar, score_dataframe

    scoring_cfg = load_scoring_config()
    rpath = review_sheet_path(args.demo)

    if not rpath.exists():
        logger.error("No review sheet at %s. Run 'radar run' first.", rpath)
        sys.exit(1)

    # Run shared validation — refuse on any error
    errors, warnings = validate_state(demo=args.demo)
    for w in warnings:
        logger.warning("VALIDATE: %s", w)
    if errors:
        for e in errors:
            logger.error("VALIDATE: %s", e)
        logger.error(
            "Scoring refused: %d validation error(s). "
            "Fix the issues above and retry.", len(errors)
        )
        sys.exit(1)

    dataset_kind = "demo" if args.demo else "real"

    if args.demo:
        # Auto-mark all rows as reviewed for demo mode
        df = pd.read_csv(rpath)
        df["reviewed"] = True
        df.to_csv(rpath, index=False)
        logger.info("Demo: auto-marked %d rows as reviewed", len(df))

    reviewed_df = load_review_sheet(rpath, include_unreviewed=False)

    if reviewed_df.empty:
        logger.error(
            "No reviewed rows in %s. Mark rows as reviewed=true.", rpath
        )
        sys.exit(1)

    # Also load unreviewed for inclusion in radar.csv
    all_df = load_review_sheet(rpath, include_unreviewed=True)

    result = score_dataframe(
        all_df, scoring_cfg,
        dataset_kind=dataset_kind,
        include_unreviewed=True,
    )
    save_radar(result, demo=args.demo)
    scored_count = len(result[result["ring"] != "Unreviewed"])
    logger.info(
        "Radar: %d scored, %d unreviewed",
        scored_count, len(result) - scored_count,
    )


def cmd_run(args: argparse.Namespace) -> None:
    """collect → extract → review-sheet, then stop for human review."""
    slug_to_name: dict[str, str] | None = None

    if args.demo:
        scoring_cfg = load_scoring_config()
        collected, slug_to_name = _load_fixtures(scoring_cfg, demo=True)
        rows = cmd_extract(args, collected=collected, slug_to_name=slug_to_name)
    else:
        startups_cfg = load_startups_config()
        slug_to_name = {s.slug: s.name for s in startups_cfg.startups}
        collected = cmd_collect(args)
        rows = cmd_extract(args, collected=collected, slug_to_name=slug_to_name)

    cmd_review_sheet(args, extracted_rows=rows)


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate configuration and data integrity."""
    errors, warnings = validate_state(demo=args.demo)

    for w in warnings:
        logger.warning("VALIDATE: %s", w)
    for e in errors:
        logger.error("VALIDATE: %s", e)

    if errors:
        logger.error("Validation failed with %d error(s)", len(errors))
        sys.exit(1)
    else:
        logger.info("Validation passed (%d warning(s))", len(warnings))


def cmd_analyse(args: argparse.Namespace) -> None:
    """Run analysis and write reports."""
    from radar.analysis import run_analysis
    run_analysis(demo=args.demo)


def cmd_status(args: argparse.Namespace) -> None:
    """Show per-start-up pipeline status (read-only)."""
    from radar.paths import radar_csv_path

    startups_cfg = load_startups_config()
    rpath = review_sheet_path(args.demo)
    radar_path = radar_csv_path(args.demo)

    print(f"{'Slug':<25} {'Pages':>5}  {'Review Status':<25}  {'Ring':<15}")
    print("-" * 75)

    # Load review sheet if it exists
    review_df: pd.DataFrame | None = None
    if rpath.exists():
        review_df = pd.read_csv(rpath)
        for col in ("reviewed", "excluded"):
            if col in review_df.columns:
                review_df[col] = (
                    review_df[col].astype(str).str.strip().str.lower()
                    .isin(["true", "1", "yes"])
                )
            else:
                review_df[col] = False

    # Load radar.csv if it exists
    radar_df: pd.DataFrame | None = None
    if radar_path.exists():
        radar_df = pd.read_csv(radar_path)

    totals = {"awaiting": 0, "reviewed": 0, "excluded": 0, "pages": 0}
    data_as_of = ""

    for s in startups_cfg.startups:
        pages = len(s.urls)
        review_status = "not in review sheet"
        ring = "-"

        if review_df is not None and s.slug in review_df["slug"].values:
            row = review_df[review_df["slug"] == s.slug].iloc[0]
            sc = int(row.get("source_count", 0)) if pd.notna(row.get("source_count")) else 0
            pages = sc

            if row.get("excluded", False):
                reason = str(row.get("exclusion_reason", "")).strip()
                review_status = f"excluded: {reason}" if reason else "excluded (no reason!)"
                totals["excluded"] += 1
            elif row.get("reviewed", False):
                review_status = "reviewed"
                totals["reviewed"] += 1
            else:
                review_status = "awaiting review"
                totals["awaiting"] += 1

            # Track data-as-of
            fetched = str(row.get("source_fetched_at", ""))
            for d in fetched.split("|"):
                d = d.strip()
                if d and (not data_as_of or d > data_as_of):
                    data_as_of = d
        else:
            totals["awaiting"] += 1

        totals["pages"] += pages

        if radar_df is not None and s.slug in radar_df["slug"].values:
            rrow = radar_df[radar_df["slug"] == s.slug].iloc[0]
            ring = str(rrow.get("ring", "-"))

        print(f"{s.slug:<25} {pages:>5}  {review_status:<25}  {ring:<15}")

    print("-" * 75)
    print(
        f"Total: {len(startups_cfg.startups)} start-ups, "
        f"{totals['pages']} usable pages, "
        f"{totals['reviewed']} reviewed, "
        f"{totals['awaiting']} awaiting, "
        f"{totals['excluded']} excluded"
    )
    if data_as_of:
        print(f"Data as of: {data_as_of}")


# ── Entry point ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)

    commands: dict[str, Any] = {
        "collect": cmd_collect,
        "extract": cmd_extract,
        "review-sheet": cmd_review_sheet,
        "score": cmd_score,
        "run": cmd_run,
        "validate": cmd_validate,
        "analyse": cmd_analyse,
        "status": cmd_status,
    }

    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception:
        logger.exception("Fatal error")
        sys.exit(1)
