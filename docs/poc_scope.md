# PoC Scope

## 1. Purpose

Evaluate whether TimeCopilot can support a reproducible commodity price forecasting workflow with useful probabilistic forecasts and natural-language forecast analysis.

The active commodity is Arabica coffee. The PoC is a forecasting experiment, not a trading system.

## 2. Forecast Contract

| Item | Definition |
|---|---|
| Commodity | Arabica coffee |
| Dataset | World Bank Commodity Price Data (Pink Sheet) workbook |
| Target construction | Monthly `Coffee, Arabica` series from the preserved workbook |
| Target | Price level in `$/kg` |
| Forecast frequency | Monthly |
| Forecast horizon | 3 months |
| Historical context | 60 months |
| Validation | Time-series-aware historical backtesting |
| Required outputs | Point forecast plus prediction intervals and/or quantile forecasts |
| Forecast-quality evidence | Report leakage-safe backtest accuracy and probabilistic calibration; no precommitted performance threshold |

The active source artifact is `data/raw/world_bank/pink_sheet/CMO-Historical-Data-Monthly.xlsx`. API refresh and futures settlement datasource selection are future work.

## 3. In Scope

### Phase 0 Enabling Work

- verify actual TimeCopilot covariate support;
- adopt the preserved World Bank Pink Sheet workbook as the active monthly Arabica dataset;
- generate the initial data catalog;
- record decisions, limitations, and future datasource follow-ups.

### Phase 1 — History-Only Forecasting

- prepare the monthly `Coffee, Arabica` target series;
- run 3-month probabilistic forecasts from 60 months of target history;
- perform walk-forward / rolling-origin historical evaluation;
- use TimeCopilot natural-language forecast, analysis, and explanation capabilities.

### Phase 2 — Covariate Forecasting

- select a small subset of past covariates and, where useful, static covariates;
- use covariates only where the TimeCopilot integration demonstrably consumes them;
- allow unsupported models to fall back to history-only forecasting;
- require at least one valid covariate-informed experiment.

The Pink Sheet workbook does not provide known future covariates, so the active PoC disregards them. The PoC may add an adapter only when a smoke test shows that the selected model natively supports past covariates but TimeCopilot does not expose them. It must not add model-level covariate or probabilistic functionality.

Raw data collection may be broader than the final model feature set.

## 4. Out of Scope

- multimodal forecasting inputs or document-processing pipelines;
- model fine-tuning;
- trading signals, execution, portfolio construction, or P&L optimization;
- real-time streaming or production deployment infrastructure;
- exhaustive feature or hyperparameter search;
- full historical-vintage reconstruction for revised external datasets;
- automated API refresh or futures settlement datasource selection for the active static-workbook PoC.

## 5. PoC Success Criteria

The PoC is successful when:

1. the monthly Arabica history-only forecasting pipeline runs reproducibly end to end;
2. 3-month probabilistic forecasts can be evaluated without future leakage;
3. TimeCopilot natural-language forecast analysis works on the PoC workflow;
4. an initial structured commodity data catalog exists;
5. at least one valid covariate-informed experiment is completed.

Reported forecast quality is evidence for the PoC, not a pass/fail model-performance gate. If any success criterion cannot be demonstrated, the PoC is not successful and the unmet criterion must be reported.

Phase 0 may finalize the monthly workbook adoption and compatible adapter choices from recorded smoke-test evidence. Other datasource and model behavior that remains undocumented must be recorded as `unknown`.
