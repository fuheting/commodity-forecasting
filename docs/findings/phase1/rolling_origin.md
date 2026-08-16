# Phase 1 Monthly Rolling-Origin Forecasting

- Run ID: `P1-06-20260816142818Z`
- Classification: `pass`
- Marker state: `pass_final`
- Reference model: `autogluon/chronos-2-small`
- Execution runner: `timecopilot_live`
- Execution mode: `zero_shot_forecast_only`
- TimeCopilot version: `0.0.30`
- Chronos adapter package version: `0.2.2`
- Network policy: `offline_cache_only`
- Cache policy: `explicit_hf_hub_cache`
- P1-05 evidence SHA-256: `d87ea4c8d3c0cc4fb2e7fd24174cc24b329fdc58242fc018eb4965db4b11fcf3`
- Publication label: `revised_workbook_pseudo_real_time`
- Availability proxy: `strict_prior_month`
- Vintage limitation: Historical release timestamps and vintages are not available in the preserved workbook. Strict prior-month eligibility is a conservative simulation assumption, not a verified historical publication date; the latest workbook can contain revisions.

## Schedule

- Origins: `2026-03-01, 2026-04-01, 2026-05-01`
- Cutoffs: `2026-02-01, 2026-03-01, 2026-04-01`
- Historic context: `60` months
- Forecast horizon: `3` months

## Zero-shot and publication contract

- History-only context is passed through public forecast calls; no per-origin fitting, fine-tuning, calibration, or weight updates are performed.
- Point forecasts are authoritative; interval and quantile outputs are independent supported probabilistic requests.
- The revised workbook is labeled pseudo-real-time. Historical release timestamps and vintages are unavailable, so strict prior-month eligibility is a conservative proxy rather than vintage-real-time evidence.
- Write order: `forecasts.csv, rolling_origin.md, rolling_origin.json`.

Machine-readable evidence: `docs/findings/phase1/evidence/rolling_origin.json`
