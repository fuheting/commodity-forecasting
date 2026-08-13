# Roadmap

## Current Status: Phase 0 Complete; Phase 1 Ready

> Phase 0 evidence supports a lean monthly Arabica PoC using the preserved World Bank Pink Sheet workbook. Do not add API acquisition or futures settlement work to the active PoC unless the scope is explicitly revised.

State markers:

- `[x]` complete
- `[-]` in progress
- `[ ]` planned

---

## Phase 0: Capability & Data Discovery (Complete)

- [x] Define the PoC forecast contract and scope. Evidence: `docs/poc_scope.md` defines the World Bank `Coffee, Arabica` monthly target, 60-month context, 3-month horizon, required probabilistic outputs, leakage-safe evaluation, non-goals, failure boundary, and Phase 0 decision authority.
- [x] **Covariate-support smoke test:** T0's native `future_covariates` path executed successfully, while TimeCopilot 0.0.30's T0 integration exposed only the univariate path. Evidence: `docs/findings/phase0/covariate_support.md` and `docs/findings/phase0/evidence/covariate_support.json`.
- [x] **Probabilistic-adapter smoke test:** TimeCopilot 0.0.30's T0 adapter returned quantile columns for `quantiles=[0.1, 0.5, 0.9]` and interval columns for `level=[80]`; simultaneous `level` and `quantiles` is unsupported. Evidence: `docs/findings/phase0/probabilistic_adapters.md` and `docs/findings/phase0/evidence/probabilistic_adapters.json`.
- [x] **Natural-language capability smoke test:** a credential-free deterministic PydanticAI FunctionModel drove TimeCopilot through feature, cross-validation, forecast, and anomaly tools and returned non-empty analysis plus a query-specific response. Evidence: `docs/findings/phase0/natural_language.md` and `docs/findings/phase0/evidence/natural_language.json`. This validates the agent/tool contract, not external-provider language quality.
- [x] **Datasource smoke test and workbook adoption:** the official World Bank Pink Sheet workbook was downloaded without datasource credentials and proves a complete monthly `Coffee, Arabica` target plus candidate past covariates from `1960M01` through `2026M07`. Evidence: `docs/findings/phase0/world_bank_pink_sheet_availability.md`, `docs/findings/phase0/evidence/world_bank_pink_sheet_availability.json`, `docs/findings/phase0/datasource_selection.md`, and `docs/findings/phase0/evidence/datasource_selection.json`.
- [x] Select the active static PoC datasource. The selected source is `world_bank_pink_sheet_monthly_arabica`; API refresh and futures settlement datasource selection are deferred future work. Evidence: `docs/adr/0001-adopt-world-bank-pink-sheet.md` and `docs/findings/phase0/evidence/datasource_selection.json`.
- [x] Generate the initial `data_catalog`. The accepted catalog is `data/catalog/phase0/world_bank_arabica_catalog.json`. Evidence: `docs/findings/phase0/data_catalog.md` and `docs/findings/phase0/evidence/data_catalog.json`.
- [x] Record Phase 0 decisions and limitations. Evidence: `docs/findings/phase0/decisions.md`, `docs/findings/phase0/limitations.md`, `docs/findings/phase0/evidence/decision_rollup.json`, `docs/findings/phase0/roadmap_exit.md`, and `docs/findings/phase0/evidence/roadmap_exit.json` cross-link every conclusion to SM-01 through SM-07 and preserve open unknowns.

**Exit condition:** the PoC forecast contract and scope are defined; native covariate support is empirically recorded; natural-language forecast analysis is empirically demonstrated; at least one model adapter is shown to return the required probabilistic outputs; any required custom-adapter work is added to the roadmap; the static monthly World Bank `Coffee, Arabica` workbook source is adopted; the initial data catalog exists; and Phase 0 decisions and findings are recorded.

---

## Phase 1: Monthly Arabica History-Only Forecasting (Planned)

- [ ] Build the monthly `Coffee, Arabica` target-data pipeline from the preserved workbook.
- [ ] Run history-only TimeCopilot forecasting with a 60-month context and 3-month horizon.
- [ ] Implement time-series-aware historical validation.
- [ ] Evaluate probabilistic forecast results.
- [ ] Exercise TimeCopilot natural-language forecast, analysis, and explanation.

---

## Phase 2: Monthly Arabica Covariate Forecasting (Planned)

- [ ] Select a small past-covariate subset and any useful static covariates from the collected data.
- [ ] Verify that the selected TimeCopilot path consumes past covariates; add a minimal adapter only if the model supports them but the integration omits them.
- [ ] Run covariate-informed forecasts only where feature availability is valid at the forecast origin.
- [ ] Retain history-only fallback for unsupported models.
- [ ] Compare covariate-informed results with history-only baselines.

---

## Deferred Future Work

- [ ] Evaluate automated World Bank refresh or API acquisition after the static-workbook PoC.
- [ ] Revisit futures settlement datasources only if the project scope returns to settlement forecasting.
- [ ] Revisit a compatible T0 adapter path for future covariates only if future covariates enter scope.
- [ ] Add external weather, macro, positioning, supply, demand, or trade-flow covariates only after their availability timing is documented.

---

## PoC Closeout (Planned)

- [ ] Summarize results, capability limits, datasource limits, and next-step recommendation.
