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

Execution plan: `docs/tasks/phase1-history-only-forecasting.md`.

- [x] **P1-01 — Dependency/readiness contract.** Use the approved minimal `openpyxl>=3.1,<4` reader, define Phase 1 paths and evidence contracts, and record the publication-availability policy; `openpyxl==3.1.5` has read the preserved workbook and located `Coffee, Arabica` in `Monthly Prices`. Custom XLSX parsers remain prohibited. Evidence: `docs/findings/phase1/dependency_readiness.md` and `docs/findings/phase1/evidence/dependency_readiness.json`.
- [x] **P1-02 — Monthly target pipeline.** Depends on P1-01. The preserved workbook's monthly `Coffee, Arabica` series is published as separate standardized and model-ready `unique_id / ds / y` artifacts with 799 contiguous months from `1960M01` through `2026M07`; the raw workbook hash remains unchanged. Evidence: `docs/findings/phase1/target_pipeline.md`, `docs/findings/phase1/evidence/target_pipeline.json`, and `tests/unit/test_phase1_target_pipeline.py`.
- [x] **P1-03 — Official-document edge-feasibility screen.** Depends on P1-02. Screen every documented local-capable Time Series Foundation Model family at the artifact-variant level against official evidence and the recorded 16 GB GPU target; required unknowns are not eligible. Evidence: `docs/findings/phase1/model_screening.md` and `docs/findings/phase1/evidence/model_screening.json`.
- [x] **P1-04 — User shortlist approval gate.** Depends on P1-03. The exact ordered shortlist is durably bound to the current P1-03 evidence hash; the user explicitly accepted the recorded unknown risks for those variants, and every downstream runtime request must match the approved identities and order. Evidence: `docs/findings/phase1/shortlist_approval.md`, `docs/findings/phase1/evidence/shortlist_approval.json`, and `tests/unit/test_phase1_shortlist_gate.py`.
- [x] **P1-05 — Runtime compatibility and reference selection.** Depends on P1-04. Test only the approved shortlist through TimeCopilot, require point plus supported probabilistic output, and select one reference by contract completeness, verified edge footprint, then user-approved order. Evidence: `docs/findings/phase1/runtime_compatibility.md` and `docs/findings/phase1/evidence/runtime_compatibility.json`.
- [x] **P1-06 — Monthly rolling-origin forecasts.** Depends on P1-05. Run exactly 3 one-month-step origins using exactly 60 historic-context months and a 3-month horizon, history only. The zero-shot Time Series Foundation Model remains frozen; no per-origin fitting, fine-tuning, or weight updates occur. Evidence: forecast artifacts and `docs/findings/phase1/rolling_origin.md`.
- [x] **P1-07 — Point and probabilistic evaluation.** Depends on P1-06. Report MAE and RMSE plus interval coverage/width or quantile pinball loss/coverage, without a performance threshold. Evidence: `docs/findings/phase1/evaluation.md` and `docs/findings/phase1/evidence/evaluation.json`.
- [x] **P1-08 — Natural-language exercise.** Depends on P1-06. Use PydanticAI's native DeepSeek provider through TimeCopilot (`deepseek:deepseek-v4-flash`); no custom DeepSeek adapter is required. Load `DEEPSEEK_API_KEY` from `.env` without persisting its value, then require non-empty forecast analysis and a query-specific response on the Phase 1 workflow. Evidence: `docs/findings/phase1/natural_language.md` and `docs/findings/phase1/evidence/natural_language.json`.
- [ ] **P1-09 — Evidence rollup and Phase 1 exit.** Depends on P1-01 through P1-08. Cross-link all evidence, decisions, unknowns, and limitations, then update task status only where acceptance evidence passes. Evidence: `docs/findings/phase1/exit_rollup.md` and `docs/findings/phase1/evidence/exit_rollup.json`.

**Exit condition:** P1-01 through P1-08 have passing acceptance evidence; the monthly pipeline is reproducible and leakage-safe; the screened shortlist was explicitly approved before runtime tests; one approved reference model produced the required 3 rolling-origin probabilistic forecasts; point accuracy and probabilistic calibration are reported without a score gate; the natural-language workflow passes; and P1-09 confirms that the roadmap matches the evidence. `blocked` and `unsupported` records are valid findings but do not complete a task or Phase 1.

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
