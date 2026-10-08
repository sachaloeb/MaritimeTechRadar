# Results (Real data, n=5)

Data as of: 2026-10-07T18:02:11.406461+00:00. Exploratory analysis only — sample size is too small for statistical claims.

## RQ1: Coverage

| criterion | share_overridden | mean_auto_score | mean_reviewed_score |
| --- | --- | --- | --- |
| maritime_relevance | 0.0 | 3.0 | 3.0 |
| theme_fit | 0.0 | 4.5 | 4.5 |
| maturity_signals | 0.0 | 1.8333 | 1.8333 |
| evidence_quality | 0.0 | 2.6667 | 2.6667 |
| theme | 0.0 |  |  |

## RQ2: Review effect

RQ2 is trivial for this snapshot: no criterion overrides were applied, so automatic and reviewed scores are identical.

| slug | auto_score | reviewed_score | auto_ring | reviewed_ring | ring_changed | auto_rank | reviewed_rank | rank_change | spearman_rho |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| orca-ai | 79.33 | 79.33 | Pilot-ready | Pilot-ready | False | 1.0 | 1.0 | 0 | 1.0000 |
| portchain | 69.33 | 69.33 | Promising | Promising | False | 2.0 | 2.0 | 0 | 1.0000 |
| cydome | 60.17 | 60.17 | Promising | Promising | False | 3.0 | 3.0 | 0 | 1.0000 |
| searoutes | 51.04 | 51.04 | Promising | Promising | False | 4.0 | 4.0 | 0 | 1.0000 |
| norsepower | 41.79 | 41.79 | Early | Early | False | 5.0 | 5.0 | 0 | 1.0000 |

## RQ3: Weight sensitivity

| criterion | delta | new_weight | clipped | rank_changes | max_rank_shift | ring_changes | spearman_vs_baseline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| maritime_relevance | -0.1 | 0.2 | False | 0 | 0 | 0 | 1.0000 |
| maritime_relevance | 0.1 | 0.4 | False | 0 | 0 | 0 | 1.0000 |
| theme_fit | -0.1 | 0.15 | False | 0 | 0 | 1 | 1.0000 |
| theme_fit | 0.1 | 0.35 | False | 0 | 0 | 1 | 1.0000 |
| maturity_signals | -0.1 | 0.15 | False | 0 | 0 | 0 | 1.0000 |
| maturity_signals | 0.1 | 0.35 | False | 0 | 0 | 1 | 1.0000 |
| evidence_quality | -0.1 | 0.1 | False | 0 | 0 | 1 | 1.0000 |
| evidence_quality | 0.1 | 0.3 | False | 0 | 0 | 0 | 1.0000 |
| SUMMARY |  |  |  | 0 |  | 4 | 0/8 scenarios with rank change |

## RQ4: Refresh cost

| metric | value |
| --- | --- |
| review_minutes | not recorded |
| pages_cache_hit | 10 |
| pages_failed_or_blocked | 0 |
| pages_usable_total | 10 |
| reproducibility | identical (extracted + radar) |
| extracted_csv_hash | 1d3d72759c81ca7a |
| radar_csv_hash | 612b766f63fed2bc |

## Limitations

- Keyword matching is context-blind: navigation labels, footers and bios can match.
- theme_fit saturates quickly from a single quadrant.
- Maturity vocabulary is narrow.
- Human overrides exist for exactly this reason.
- Sample size is exploratory (n=5-8), no statistical power.
