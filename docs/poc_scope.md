# PoC Scope

## 1. Purpose

Evaluate whether TimeCopilot can support a reproducible commodity futures forecasting workflow with useful probabilistic forecasts and natural-language forecast analysis.

The first commodity is Arabica coffee. The PoC is a forecasting experiment, not a trading system.

## 2. Forecast Contract

| Item | Definition |
|---|---|
| Commodity | Arabica coffee |
| Instrument | ICE Coffee C futures |
| Target construction | Continuous front-month series |
| Target | Price level |
| Weekly target value | Last available settlement of the week |
| Forecast frequency | Weekly |
| Forecast horizon | 12 weeks |
| Historical context | 260 weeks |
| Validation | Time-series-aware historical backtesting |

A provider-constructed continuous front-month series is acceptable. Datasource availability, historical coverage, and ease of access are more important than transparent roll methodology for the PoC.

## 3. In Scope

### Phase 0 Enabling Work

- verify actual TimeCopilot covariate support;
- evaluate datasource candidates;
- select a primary Coffee C datasource and practical fallback;
- generate the initial data catalog.

### Phase 1 — History-Only Forecasting

- collect and prepare the Coffee C target series;
- run 12-week probabilistic forecasts from 260 weeks of target history;
- perform walk-forward / rolling-origin historical evaluation;
- use TimeCopilot natural-language forecast, analysis, and explanation capabilities.

### Phase 2 — Covariate Forecasting

- collect structured covariates during raw-data acquisition;
- select a small subset for modeling;
- use covariates only where the TimeCopilot integration demonstrably consumes them;
- allow unsupported models to fall back to history-only forecasting;
- require at least one valid covariate-informed experiment.

Raw data collection may be broader than the final model feature set.

## 4. Out of Scope

- multimodal forecasting inputs or document-processing pipelines;
- model fine-tuning;
- trading signals, execution, portfolio construction, or P&L optimization;
- real-time streaming or production deployment infrastructure;
- exhaustive feature or hyperparameter search;
- full historical-vintage reconstruction for revised external datasets.

## 5. PoC Success Criteria

The PoC is successful when:

1. the Coffee C history-only forecasting pipeline runs reproducibly end to end;
2. 12-week probabilistic forecasts can be evaluated without future leakage;
3. TimeCopilot natural-language forecast analysis works on the PoC workflow;
4. an initial structured commodity data catalog exists;
5. at least one valid covariate-informed experiment is completed.