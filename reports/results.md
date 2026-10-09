# Results (Real data, n=5)

Data as of: 2026-10-07T18:02:11.406461+00:00. Exploratory analysis only — sample size is too small for statistical claims.

## RQ1: Coverage

| criterion | share_overridden | mean_auto_score | mean_reviewed_score |
| --- | --- | --- | --- |
| maritime_relevance | 0.0 | 3.0 | 3.0 |
| theme_fit | 0.0 | 4.5 | 4.5 |
| maturity_signals | 0.6 | 1.8333 | 3.4333 |
| evidence_quality | 0.4 | 2.6667 | 3.2333 |
| theme | 0.4 |  |  |

## RQ2: Review effect

| slug | auto_score | reviewed_score | auto_ring | reviewed_ring | ring_changed | auto_rank | reviewed_rank | rank_change | spearman_rho |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| orca-ai | 79.33 | 79.33 | Pilot-ready | Pilot-ready | False | 1.0 | 1.0 | 0 | 0.9000 |
| cydome | 60.17 | 77.0 | Promising | Pilot-ready | True | 3.0 | 2.0 | 1 | 0.9000 |
| portchain | 69.33 | 74.67 | Promising | Pilot-ready | True | 2.0 | 3.0 | -1 | 0.9000 |
| searoutes | 51.04 | 61.88 | Promising | Promising | False | 4.0 | 4.0 | 0 | 0.9000 |
| norsepower | 41.79 | 60.13 | Early | Promising | True | 5.0 | 5.0 | 0 | 0.9000 |

## RQ3: Weight sensitivity

| criterion | delta | new_weight | clipped | rank_changes | max_rank_shift | ring_changes | spearman_vs_baseline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| maritime_relevance | -0.1 | 0.2 | False | 0 | 0 | 0 | 1.0000 |
| maritime_relevance | 0.1 | 0.4 | False | 0 | 0 | 0 | 1.0000 |
| theme_fit | -0.1 | 0.15 | False | 2 | 1 | 0 | 0.9000 |
| theme_fit | 0.1 | 0.35 | False | 0 | 0 | 0 | 1.0000 |
| maturity_signals | -0.1 | 0.15 | False | 0 | 0 | 0 | 1.0000 |
| maturity_signals | 0.1 | 0.35 | False | 2 | 1 | 0 | 0.9000 |
| evidence_quality | -0.1 | 0.1 | False | 0 | 0 | 0 | 1.0000 |
| evidence_quality | 0.1 | 0.3 | False | 0 | 0 | 0 | 1.0000 |
| SUMMARY |  |  |  | 2 |  | 0 | 2/8 scenarios with rank change |

## RQ4: Refresh cost

| metric | value |
| --- | --- |
| mean_review_minutes | 12.6 |
| median_review_minutes | 12.0 |
| pages_cache_hit | 10 |
| pages_failed_or_blocked | 0 |
| pages_usable_total | 10 |
| reproducibility | identical (extracted + radar) |
| extracted_csv_hash | 34db653d40170284 |
| radar_csv_hash | 2ab36e525cd4944a |

## Limitations

- Keyword matching is context-blind: navigation labels, footers and bios can match.
- theme_fit saturates quickly from a single quadrant.
- Maturity vocabulary is narrow.
- Human overrides exist for exactly this reason.
- Sample size is exploratory (n=5-8), no statistical power.
