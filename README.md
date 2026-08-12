# Commodity Futures Forecasting with TimeCopilot

A lean proof-of-concept project for probabilistic commodity futures forecasting using TimeCopilot.

The initial use case is **ICE Coffee C**:

- target: continuous front-month price level
- weekly value: last available settlement of each week
- forecast frequency: weekly
- forecast horizon: 12 weeks
- historical context: 260 weeks

## PoC Structure

**Phase 1:** history-only forecasting and historical validation.

**Phase 2:** structured covariate forecasting where the TimeCopilot integration actually supports covariates; unsupported models may remain history-only.

The PoC also includes TimeCopilot natural-language forecast queries, analysis, and explanation.

Multimodal inputs, model fine-tuning, trading strategies, and production deployment are out of scope.

## Current Status

**Phase 0 — Capability & Data Discovery**

Phase 0 determines:

- actual TimeCopilot covariate support;
- usable datasource candidates;
- the initial data catalog.

See `docs/roadmap.md` for implementation progress.