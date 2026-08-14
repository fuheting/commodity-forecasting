# Phase 1 Monthly Target Pipeline

- Run ID: `P1-02-20260814T084205Z`
- Classification: `pass`
- Source: `Monthly Prices` / `Coffee, Arabica`
- Raw SHA-256 before: `7902a77505ebdc5d202ce65f666c2ee1b04b626f042d7738ed3e6f7d112c8433`
- Raw SHA-256 after: `7902a77505ebdc5d202ce65f666c2ee1b04b626f042d7738ed3e6f7d112c8433`
- Monthly extent: `1960M01` through `2026M07` (`799` rows)
- Schema: `unique_id,ds,y`
- Standardized SHA-256: `f360fc49d2537785ea4b5b51809cac8186048059121c5b16864a0ca25f06cbb7`
- Model-ready SHA-256: `f360fc49d2537785ea4b5b51809cac8186048059121c5b16864a0ca25f06cbb7`

## Publication-availability policy

- Evaluation label: `revised_workbook_pseudo_real_time`
- Availability proxy: `strict_prior_month`
- Limitation: Historical release timestamps and vintages are not available in the preserved workbook. Strict prior-month eligibility is a conservative simulation assumption, not a verified historical publication date; the latest workbook can contain revisions.
- Prohibited claim: Do not describe this evaluation as vintage-real-time.

## Transform boundary

The artifact contains only the observed monthly target level. No fill, interpolation, resampling, frequency conversion, scaling, differencing, covariates, engineered features, or future values were used.

Machine-readable evidence: `docs/findings/phase1/evidence/target_pipeline.json`
