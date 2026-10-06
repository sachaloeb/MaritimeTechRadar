"""CLI entry point: radar {collect, extract, review-sheet, score, run, validate, analyse}."""

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

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar",
        description="Maritime Tech Radar: config-driven pipeline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Subcommands with their flags
    collect_p = sub.add_parser("collect", help="Fetch pages")
    collect_p.add_argument("--refresh", action="store_true")
    collect_p.add_argument("--offline", action="store_true")
    collect_p.add_argument("--demo", "--fixtures", action="store_true", dest="demo")

    extract_p = sub.add_parser("extract", help="Parse cached HTML")
    extract_p.add_argument("--offline", action="store_true")
    extract_p.add_argument("--demo", "--fixtures", action="store_true", dest="demo")

    review_p = sub.add_parser("review-sheet", help="Generate review CSV")
    review_p.add_argument("--demo", "--fixtures", action="store_true", dest="demo")
    review_p.add_argument("--force-new", action="store_true")

    score_p = sub.add_parser("score", help="Score reviewed rows")
    score_p.add_argument("--demo", "--fixtures", action="store_true", dest="demo")

    run_p = sub.add_parser("run", help="collect→extract→review-sheet")
    run_p.add_argument("--refresh", action="store_true")
    run_p.add_argument("--offline", action="store_true")
    run_p.add_argument("--demo", "--fixtures", action="store_true", dest="demo")
    run_p.add_argument("--force-new", action="store_true")

    validate_p = sub.add_parser("validate", help="Validate config and data")
    validate_p.add_argument("--demo", "--fixtures", action="store_true", dest="demo")

    analyse_p = sub.add_parser("analyse", help="Run analysis (RQ1-RQ4)")
    analyse_p.add_argument("--demo", "--fixtures", action="store_true", dest="demo")

    return parser


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

    # For real data, check source_count >= 2
    if not args.demo and "source_count" in reviewed_df.columns:
        low = reviewed_df[reviewed_df["source_count"] < 2]
        if not low.empty:
            slugs = low["slug"].tolist()
            logger.error(
                "Scored rows must have >=2 source pages (real data). "
                "Failing slugs: %s", slugs,
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
    errors: list[str] = []
    warnings: list[str] = []

    # Check startups.yaml
    try:
        startups_cfg = load_startups_config()
    except Exception as exc:
        errors.append(f"startups.yaml: {exc}")
        startups_cfg = None

    if startups_cfg is not None:
        n = len(startups_cfg.startups)
        if n == 0:
            errors.append("startups.yaml: no start-ups configured")
        elif n < 5:
            warnings.append(f"startups.yaml: only {n} start-ups (recommend 5-8)")
        elif n > 8:
            warnings.append(f"startups.yaml: {n} start-ups (recommend 5-8)")

        # Check for denylisted URLs
        scoring_cfg = load_scoring_config()
        for s in startups_cfg.startups:
            for url in s.urls:
                from radar.collector import _is_denied
                if _is_denied(url, scoring_cfg.denylist):
                    errors.append(
                        f"Denylisted URL in config: {url} (slug: {s.slug})"
                    )

    # Check review sheet
    rpath = review_sheet_path(args.demo)
    if rpath.exists():
        from radar.review import load_review_sheet
        df = load_review_sheet(rpath, include_unreviewed=True)

        # Check excluded rows have reasons
        if "excluded" in df.columns and "exclusion_reason" in df.columns:
            excluded = df[
                df["excluded"].astype(str).str.lower().isin(["true", "1", "yes"])
            ]
            missing_reason = excluded[
                excluded["exclusion_reason"].isna()
                | (excluded["exclusion_reason"].astype(str).str.strip() == "")
            ]
            for _, row in missing_reason.iterrows():
                errors.append(
                    f"Excluded row '{row['slug']}' has no exclusion_reason"
                )

        # Validate overrides
        scoring_cfg = load_scoring_config()
        valid_themes = set(scoring_cfg.quadrants.keys())
        reviewed = df[
            df["reviewed"].astype(str).str.lower().isin(["true", "1", "yes"])
        ]
        for _, row in reviewed.iterrows():
            slug = row.get("slug", "?")
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
