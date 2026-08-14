# Commodity Price Forecasting with TimeCopilot

A lean proof-of-concept project for probabilistic commodity price forecasting using TimeCopilot.

The active use case is the World Bank Pink Sheet **Coffee, Arabica** series:

- target: monthly price level in `$/kg`
- forecast horizon: 3 months
- historical context: 60 months

## PoC Structure

**Phase 1:** history-only forecasting and historical validation.

**Phase 2:** structured covariate forecasting where the TimeCopilot integration actually supports covariates; unsupported models may remain history-only.

The PoC also includes TimeCopilot natural-language forecast queries, analysis, and explanation.

Multimodal inputs, model fine-tuning, trading strategies, and production deployment are out of scope.

The weekly synthetic fixtures under `tests/fixtures/phase0/` are retained only to reproduce completed Phase 0 adapter-capability smoke tests. They do not define the active monthly forecast contract.

## Current Status

**Phase 0 — Complete; Phase 1 ready**

Phase 0 established:

- actual TimeCopilot covariate support;
- the preserved World Bank workbook as the static PoC source;
- the initial data catalog.

See `docs/roadmap.md` for implementation progress.
