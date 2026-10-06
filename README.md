# Maritime Tech Radar

A config-driven pipeline and single-page Streamlit dashboard that ranks a handful of public maritime/port-tech start-ups on a technology radar.

## Quick start

```bash
# Install (requires Python 3.11+ and uv)
make install

# Run the demo (synthetic data)
make demo
make app         # opens the dashboard at http://localhost:8501
```

## Real-data workflow

1. **Configure:** add 5–8 start-ups to `configs/startups.yaml`:
   ```yaml
   startups:
     - name: "Example Marine"
       slug: "example-marine"
       urls:
         - "https://examplemarine.com"
         - "https://examplemarine.com/about"
       notes: "Optional notes"
   ```

2. **Collect & extract:**
   ```bash
   uv run radar run
   ```
   This fetches the listed URLs (respecting robots.txt, rate limits, and the denylist), extracts structured data, and writes a review sheet to `data/review/review_sheet.csv`.

3. **Review (human step):** open `data/review/review_sheet.csv` in a spreadsheet editor. For each row:
   - Verify the extracted data is accurate
   - Optionally fill in override columns (`maritime_relevance_override`, `theme_override`, etc.)
   - Set `reviewed` to `true` for rows you approve

4. **Score:**
   ```bash
   uv run radar score
   ```
   This scores only reviewed rows and writes `data/processed/radar.csv`.

5. **Dashboard:**
   ```bash
   make app
   ```

## Scoring method

Each start-up is scored on four criteria (0–5 each), weighted and summed to a total score (0–100):

| Criterion | Weight | Method |
|-----------|--------|--------|
| Maritime relevance | 0.30 | Keyword hits from page text |
| Theme fit | 0.25 | Keyword hits matching quadrant themes |
| Maturity signals | 0.25 | Keywords: pilot, customer, funding, etc. |
| Evidence quality | 0.20 | Keywords: case study, whitepaper, etc. |

**Rings:** ≥70 "Pilot-ready", 50–69 "Promising", 30–49 "Early", <30 "Watch".

**Themes (quadrants):** Decarbonisation & Energy, Digitalisation & AI, Logistics & Operations, Safety & Security. Assigned by highest keyword hit count; ties go to the alphabetically first theme.

Reviewer overrides (filled in during the human review step) always take precedence over automatic scores.

All scoring parameters are editable in `configs/scoring.yaml`.

## Limitations

- **Heuristic keyword scoring** — not a substitute for expert evaluation.
- **Small sample size** — designed for n=5–8 start-ups.
- **Public sources only** — no proprietary databases, no login-walled content.
- **Point-in-time snapshot** — data is only as current as the last fetch.
- **No LLM calls** — scoring is deterministic and rule-based.

## Data provenance

Every fact shown in the dashboard carries:
- The source URL it was extracted from
- The date it was fetched
- Whether it was human-reviewed

The pipeline never invents, fabricates, or hallucinates data. Test fixtures use synthetic HTML pages and are clearly marked as `dataset_kind="demo"` with a prominent banner.

## Development

```bash
make test        # run pytest
make lint        # run ruff
make demo        # run pipeline on synthetic fixtures
```

## Deployment

The dashboard only needs `data/processed/radar.csv` to run. No scraping is required at deploy time:

```bash
streamlit run app/dashboard.py --server.headless true
```

## Design decisions

- **stdlib argparse** instead of click/typer to stay within the allowed dependency list.
- **`reviewed` column as a gate** — the scorer refuses to score unreviewed rows. This ensures the human review step cannot be skipped.
- **Deterministic jitter** on the radar chart (hash-based) so start-ups don't overlap but positions are stable across runs.

## License

MIT
