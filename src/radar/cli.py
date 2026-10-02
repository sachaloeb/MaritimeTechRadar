"""CLI entry point: radar {collect, extract, review-sheet, score, run}."""

import argparse
import json
import logging
import sys
from pathlib import Path

from radar.config import load_scoring_config, load_startups_config
from radar.logging_setup import setup_logging

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path("tests/fixtures")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar",
        description="Maritime Tech Radar: config-driven pipeline for ranking port-tech start-ups.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Common flags
    for p in [sub.add_parser("collect", help="Fetch pages listed in startups.yaml"),
              sub.add_parser("extract", help="Parse cached HTML into structured fields"),
              sub.add_parser("review-sheet", help="Generate review CSV from extracted data"),
              sub.add_parser("score", help="Score reviewed rows and write radar.csv"),
              sub.add_parser("run", help="Run collect→extract→review-sheet, then stop for review")]:
        p.add_argument("--refresh", action="store_true", help="Re-fetch even if cached")
        p.add_argument("--offline", action="store_true", help="Use only cached pages")
        p.add_argument("--fixtures", action="store_true", help="Use synthetic test fixtures")

    return parser


def _load_fixtures(scoring_cfg):
    """Build collected dict from test fixture HTML files."""
    from radar.collector import RAW_DIR, _url_to_cache_path

    fixture_htmls = list(FIXTURES_DIR.glob("*.html"))
    if not fixture_htmls:
        logger.error("No fixture HTML files found in %s", FIXTURES_DIR)
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Create synthetic startups from fixtures
    collected = {}
    for i, html_path in enumerate(sorted(fixture_htmls)):
        if html_path.stem == "empty_page":
            continue
        slug = f"demo-{html_path.stem.replace('_', '-')}"
        url = f"https://demo.example.com/{html_path.stem}"
        cache_path = _url_to_cache_path(url)
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
        cache_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        collected[slug] = [cache_path]

    return collected


def cmd_collect(args):
    from radar.collector import collect_all

    startups_cfg = load_startups_config()
    scoring_cfg = load_scoring_config()

    if not startups_cfg.startups:
        logger.error(
            "No start-ups configured in configs/startups.yaml. "
            "Add 5-8 entries before running the pipeline."
        )
        sys.exit(1)

    result = collect_all(startups_cfg, scoring_cfg, refresh=args.refresh, offline=args.offline)
    total = sum(len(v) for v in result.values())
    logger.info("Collection complete: %d pages for %d start-ups", total, len(result))
    return result


def cmd_extract(args, collected=None):
    from radar.extractor import extract_all

    scoring_cfg = load_scoring_config()

    if args.fixtures:
        collected = _load_fixtures(scoring_cfg)
    elif collected is None:
        # Rebuild collected from config + cache
        startups_cfg = load_startups_config()
        if not startups_cfg.startups:
            logger.error("No start-ups configured. Add entries to configs/startups.yaml.")
            sys.exit(1)
        from radar.collector import collect_all
        collected = collect_all(startups_cfg, scoring_cfg, offline=True)

    rows = extract_all(collected, scoring_cfg)
    if not rows:
        logger.error("No data extracted. Check that pages have been collected.")
        sys.exit(1)

    # Save interim
    import pandas as pd
    interim_dir = Path("data/interim")
    interim_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    interim_path = interim_dir / "extracted.csv"
    df.to_csv(interim_path, index=False)
    logger.info("Extracted %d rows to %s", len(rows), interim_path)
    return rows


def cmd_review_sheet(args, extracted_rows=None):
    from radar.review import generate_review_sheet

    if extracted_rows is None:
        import pandas as pd
        interim_path = Path("data/interim/extracted.csv")
        if not interim_path.exists():
            logger.error("No extracted data found. Run 'radar extract' first.")
            sys.exit(1)
        extracted_rows = pd.read_csv(interim_path).to_dict("records")

    path = generate_review_sheet(extracted_rows)
    logger.info(
        "Review sheet ready at: %s\n"
        "  → Open this file, verify each row, and set 'reviewed' to 'true' for rows you approve.\n"
        "  → Then run 'radar score' to generate the final radar.",
        path,
    )
    return path


def cmd_score(args):
    import pandas as pd

    from radar.review import load_review_sheet
    from radar.scoring import save_radar, score_dataframe

    scoring_cfg = load_scoring_config()

    review_path = Path("data/review/review_sheet.csv")
    if not review_path.exists():
        logger.error("No review sheet found. Run 'radar run' first.")
        sys.exit(1)

    dataset_kind = "demo" if args.fixtures else "real"

    if args.fixtures:
        # Auto-mark all rows as reviewed for demo mode
        df = pd.read_csv(review_path)
        df["reviewed"] = True
        df.to_csv(review_path, index=False)
        logger.info("Demo mode: auto-marked all %d rows as reviewed", len(df))
        df = load_review_sheet(review_path, include_unreviewed=False)
    else:
        df = load_review_sheet(review_path, include_unreviewed=False)

    if df.empty:
        logger.error(
            "No reviewed rows found in %s. "
            "Mark rows as reviewed=true before scoring.",
            review_path,
        )
        sys.exit(1)

    result = score_dataframe(df, scoring_cfg, dataset_kind=dataset_kind)
    output = save_radar(result)
    logger.info("Radar generated: %s (%d start-ups scored)", output, len(result))


def cmd_run(args):
    """Run collect→extract→review-sheet, then stop for human review."""
    if args.fixtures:
        scoring_cfg = load_scoring_config()
        collected = _load_fixtures(scoring_cfg)
        rows = cmd_extract(args, collected=collected)
    else:
        cmd_collect(args)
        rows = cmd_extract(args)

    cmd_review_sheet(args, extracted_rows=rows)


def main():
    setup_logging()
    parser = _build_parser()
    args = parser.parse_args()

    commands = {
        "collect": cmd_collect,
        "extract": cmd_extract,
        "review-sheet": cmd_review_sheet,
        "score": cmd_score,
        "run": cmd_run,
    }

    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(130)
    except Exception:
        logger.exception("Fatal error")
        sys.exit(1)
