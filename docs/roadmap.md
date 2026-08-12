# Roadmap

## Current Status: Phase 0 (Capability & Data Discovery)

> 📍 **YOU ARE HERE:** validating required TimeCopilot capabilities and candidate data sources. Do not proceed to Phase 1 until all Phase 0 tasks are marked `[x]`.

State markers:

- `[x]` complete
- `[-]` in progress
- `[ ]` planned

---

## Phase 0: Capability & Data Discovery (Active)

- [-] Define the PoC forecast contract and scope.
- [ ] **Covariate-support smoke test:** verify which TimeCopilot integrations natively consume past and/or known-future covariates; if none meets the PoC requirement, add custom-adapter implementation and validation to the roadmap.
- [ ] **Natural-language capability smoke test:** verify that the TimeCopilot agent accepts a forecast query and returns non-empty forecast analysis and a query-specific response; record the LLM, provider, credential, and tool-use requirements.
- [ ] **Probabilistic-adapter smoke test:** verify which candidate model adapters return requested prediction intervals and/or quantiles through `level` and `quantiles`; identify at least one compatible adapter for Phase 1 and record unsupported adapter/output combinations.
- [ ] **Datasource smoke test:** compare candidate Coffee C data sources for availability, programmatic access, historical coverage, and required fields.
- [ ] Select the primary Coffee C datasource and practical fallback.
- [ ] Generate the initial `data_catalog`.
- [ ] Record Phase 0 decisions and limitations.

**Exit condition:** the PoC forecast contract and scope are defined; native covariate support is empirically recorded; natural-language forecast analysis is empirically demonstrated; at least one model adapter is shown to return the required probabilistic outputs; any required custom-adapter work is added to the roadmap; a usable Coffee C datasource and fallback are selected; the initial data catalog exists; and Phase 0 decisions and findings are recorded.

---

## Phase 1: History-Only Forecasting (Planned)

- [ ] Build the Coffee C target-data pipeline.
- [ ] Run history-only TimeCopilot forecasting.
- [ ] Implement time-series-aware historical validation.
- [ ] Evaluate probabilistic forecast results.
- [ ] Exercise TimeCopilot natural-language forecast, analysis, and explanation.

---

## Phase 2: Covariate Forecasting (Planned)

- [ ] Select a small covariate subset from the collected raw data.
- [ ] Run covariate-informed forecasts.
- [ ] Retain history-only fallback for unsupported models.
- [ ] Compare covariate-informed results with history-only baselines.

---

## PoC Closeout (Planned)

- [ ] Summarize results, capability limits, datasource limits, and next-step recommendation.
