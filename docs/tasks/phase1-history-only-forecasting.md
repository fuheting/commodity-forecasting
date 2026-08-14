# Phase 1 AI-Agent Execution Plan

## Purpose

Execute Phase 1 as a bounded, evidence-backed monthly Arabica history-only forecast workflow. This plan expands the P1-01 through P1-09 gates in `docs/roadmap.md`; it does not authorize Phase 2 work.

Authoritative inputs:

- `docs/roadmap.md`
- `docs/poc_scope.md`
- `docs/data_scope.md`
- `docs/timecopilot_capabilities.md`
- `.omx/specs/deep-interview-phase1-roadmap-execution-plan.md`
- `.omx/plans/prd-phase1-history-only-forecasting.md`
- `.omx/plans/test-spec-phase1-history-only-forecasting.md`

## Fixed Contract

- Target: World Bank Pink Sheet `Coffee, Arabica`, monthly, `$/kg`.
- Model input: `unique_id | ds | y`.
- Evaluation: exactly 12 rolling origins, one-month step, exactly 60 training months, exactly 3 forecast months.
- Point metrics: MAE and RMSE.
- Probabilistic metrics: empirical coverage and mean width for intervals; mean pinball loss per quantile and empirical quantile coverage for quantiles.
- Validation is revised-workbook pseudo-real-time, not vintage-real-time. The publication-availability policy and revision limitation must be explicit.
- No numeric forecast-quality pass threshold.
- `blocked` and `unsupported` are evidence classifications, not task-completion states.

## Sequence and Stops

```text
P1-01 -> P1-02 -> P1-03 -> P1-04 [USER DECISION]
      -> P1-05 -> P1-06 -> P1-07 -> P1-08 -> P1-09
```

Do not start P1-05 until the P1-04 approval record exists. Do not mark Phase 1 complete unless P1-01 through P1-08 pass and P1-09 verifies the evidence.

## Non-Goals

- Covariates, future covariates, or custom covariate adapters.
- New model adapters or model-level probabilistic functionality.
- Fine-tuning, ensembles, exhaustive benchmarking, or hyperparameter search.
- API refresh, futures settlement data, external data, trading logic, or production infrastructure.
- A custom XLSX parser.
- Treating undocumented behavior or resource fit as established.

## P1-01 — Dependency and Readiness Contract

**Context:** The user authorized one minimal XLSX dependency. `openpyxl==3.1.5` is installed in `.venv`, successfully opens the preserved workbook, and locates `Coffee, Arabica` in `Monthly Prices`; P1-01 remains incomplete until that dependency and evidence are made reproducible in the repository.

**Scope:** Declare `openpyxl>=3.1,<4` as the direct XLSX reader, then define Phase 1 contracts, paths, evidence classification, workbook-read readiness, and the publication-availability policy.

**Constraints:** Custom XLSX parsers are prohibited. Authorization applies only to the minimal reader dependency, not unrelated packages. Do not describe the evaluation as vintage-real-time. Preserve the raw workbook unchanged.

**Dependencies:** Phase 0 completion evidence and the preserved workbook.

**Write paths:**

- `src/commodity_forecasting/phase1/__init__.py`
- `src/commodity_forecasting/phase1/contracts.py`
- `src/commodity_forecasting/phase1/paths.py`
- `src/commodity_forecasting/phase1/evidence.py`
- `src/commodity_forecasting/phase1/readiness.py`
- `tests/unit/test_phase1_reader_contract.py`
- `docs/findings/phase1/dependency_readiness.md`
- `docs/findings/phase1/evidence/dependency_readiness.json`
- `pyproject.toml` only after explicit authorization for one reader dependency

**Tests:** Reader-availability and explicit-error cases; Phase 1 path resolution; evidence-schema classifications; monthly timestamp parsing; publication-policy presence; raw-workbook hash unchanged.

**Exit criteria:** `pass` only when the declared reader installs reproducibly, reads `Monthly Prices`, finds `Coffee, Arabica`, preserves the raw hash, and the contracts validate. A later reader failure is `blocked` and leaves P1-01 unchecked.

**Non-goals:** Target transformation, model screening, forecasting, or adapter work.

## P1-02 — Monthly Target Pipeline

**Context:** Phase 0 proved the workbook contains the target but did not create standardized or model-ready artifacts. The existing Phase 0 fixture and window helper are weekly-specific.

**Scope:** Extract `Coffee, Arabica`, normalize the monthly timestamp, preserve the price level, and produce deterministic standardized and `unique_id | ds | y` model-ready tables.

**Constraints:** No future fill, backward fill, cross-boundary interpolation, centered windows, frequency conversion, or covariates. Use the publication policy from P1-01. Never overwrite raw data.

**Dependencies:** P1-01 must pass.

**Write paths:**

- `src/commodity_forecasting/phase1/target_pipeline.py`
- `tests/unit/test_phase1_target_pipeline.py`
- `data/standardized/world_bank/pink_sheet/coffee_arabica_monthly.csv`
- `data/model_ready/world_bank_pink_sheet_monthly_arabica/target.csv`
- `docs/findings/phase1/target_pipeline.md`
- `docs/findings/phase1/evidence/target_pipeline.json`

**Tests:** Exact target-column selection; numeric/non-null `y`; canonical `unique_id`; unique, monotonic monthly `ds`; expected first/last period and row count from the preserved source; deterministic output hash; raw hash unchanged; invalid timestamp and missing-target failures.

**Exit criteria:** Both derived artifacts are reproducible, schema-valid, monthly, ordered, target-only, and linked to passing evidence.

**Non-goals:** Feature engineering, imputation using future values, covariates, or model selection.

## P1-03 — Official-Document Edge-Feasibility Screen

**Context:** Local loading does not establish edge feasibility or TimeCopilot adapter support. Candidate eligibility must be established before runtime use.

**Scope:** Screen artifact variants for Chronos/Chronos-2, FlowState, Moirai, PatchTST-FM, Sundial, TabPFN, TiRex/TiRex-2, TimesFM, and Toto/Toto-2. Record T0 as excluded because the current documentation does not establish an open-source implementation, and TimeGPT as excluded because its integration is API-backed.

For each variant record: official source URL; source version/date; retrieval timestamp; applicable installed package versions; artifact identity and size; runtime/framework; device support; offline support; documented memory/VRAM requirement; fit against the recorded 16 GB GPU target; license/usage constraints; monthly history-only 60x3 support; TimeCopilot 0.0.30 adapter exposure; probabilistic output kind; result; notes; unknowns.

**Constraints:** Official/upstream evidence and observed local package metadata only. Every required field must be verified for `eligible`; any required `unknown` yields `unknown/ineligible`. Model-native support is not TimeCopilot support. Do not download weights or run models in this task.

**Dependencies:** P1-02 must pass so the exact Phase 1 input contract is fixed.

**Write paths:**

- `src/commodity_forecasting/phase1/screening.py`
- `tests/unit/test_phase1_screening_schema.py`
- `docs/findings/phase1/model_screening.md`
- `docs/findings/phase1/evidence/model_screening.json`

**Tests:** Candidate-universe completeness; required fields; source version and `retrieved_at`; applicable installed package versions; variant-level classification; 16 GB fit rule; explicit unknown preservation; T0/TimeGPT exclusion reasons; rejection of eligibility inferred from missing evidence.

**Exit criteria:** Every candidate family and relevant artifact variant has an evidence-backed classification, and the eligible candidate list contains no required unknowns.

**Non-goals:** Runtime testing, downloading all candidate weights, comparative accuracy testing, or user approval.

## P1-04 — User Approval of Eligible Shortlist

**Context:** Documentation-based eligibility is necessary but does not authorize execution.

**Scope:** Present the P1-03 eligible list, evidence summary, exclusions, and unknowns. Capture the user's exact approved candidate variants and order in a machine-readable record, including the SHA-256 hash of `model_screening.json` used for the decision.

**Constraints:** This is a hard stop. Do not default-select, add candidates, download weights, or run compatibility tests. Only explicitly approved variants may proceed.

**Dependencies:** P1-03 must pass.

**Write paths:**

- `src/commodity_forecasting/phase1/selection.py`
- `tests/unit/test_phase1_shortlist_gate.py`
- `docs/findings/phase1/shortlist_approval.md`
- `docs/findings/phase1/evidence/shortlist_approval.json`

**Tests:** Missing approval blocks execution; rejected or unknown candidates cannot be approved; only exact approved variants pass; order is stable; a screening-evidence hash mismatch invalidates prior approval.

**Exit criteria:** The user-approved variants, order, and current screening-evidence hash are durably recorded, validate against P1-03, and gate all downstream runtime entry points. Any later screening change returns execution to P1-04.

**Non-goals:** Runtime testing, model ranking, or reference selection.

## P1-05 — Runtime Compatibility and Reference Selection

**Context:** Official documentation cannot prove the installed TimeCopilot adapter behaves as required on the local machine.

**Scope:** Smoke-test every approved variant with the Phase 1 target and a single 60-month/3-month history-only forecast. Record load success, offline/local execution, device and peak-memory observations where measurable, point output, probabilistic output, columns, duration, classification, and errors. Select one reference using: contract completeness, then smallest verified edge footprint, then P1-04 order.

**Constraints:** Approved variants only. Request intervals or quantiles separately if the adapter rejects simultaneous requests. No adapter modifications, accuracy ranking, tuning, or full backtests.

**Dependencies:** P1-04 must pass.

**Write paths:**

- `src/commodity_forecasting/phase1/runtime_compatibility.py`
- `tests/smoke/test_phase1_runtime_compatibility.py`
- `docs/findings/phase1/runtime_compatibility.md`
- `docs/findings/phase1/evidence/runtime_compatibility.json`

**Tests:** Approval gate is enforced; 60x3 input; point output exists; at least one supported probabilistic form exists; output timestamps/shapes are correct; failures are classified; selection rule is deterministic.

**Exit criteria:** At least one approved variant passes the full runtime contract and one evidence-backed reference is selected. Otherwise P1-05 remains incomplete.

**Non-goals:** Custom adapters, broad benchmarking, model-quality selection, or training.

## P1-06 — Monthly Rolling-Origin Forecasting

**Context:** Phase 1 requires leakage-safe historical evidence beyond a single forecast.

**Scope:** Implement monthly window generation and run the reference model at exactly 12 origins, one month apart, each with exactly 60 training months and 3 forecast months. Persist origin, cutoff, training span, forecast span, actuals, point forecasts, and supported probabilistic outputs.

**Constraints:** History only. No reuse of the weekly Phase 0 helper unchanged. Apply the P1-01 publication policy. Label the run revised-workbook pseudo-real-time and record the missing-vintage limitation.

**Dependencies:** P1-05 must pass.

**Write paths:**

- `src/commodity_forecasting/phase1/rolling_origin.py`
- `tests/unit/test_phase1_rolling_origin.py`
- `tests/smoke/test_phase1_rolling_origin.py`
- `data/model_ready/world_bank_pink_sheet_monthly_arabica/rolling_origin/forecasts.csv`
- `docs/findings/phase1/rolling_origin.md`
- `docs/findings/phase1/evidence/rolling_origin.json`

**Tests:** Exactly 12 origins; one-month step; 60 training rows; 3 future rows; calendar-month continuity; train end precedes forecast start; no post-origin inputs; deterministic schedule and serialized schema.

**Exit criteria:** All 12 runs pass the window and output contracts and the artifacts record their cutoffs, spans, probabilistic form, and vintage limitation.

**Non-goals:** Covariate backtests, ensembles, tuning, or additional origin schedules.

## P1-07 — Point and Probabilistic Evaluation

**Context:** Forecast quality is evidence, not a numerical success gate.

**Scope:** Compute MAE and RMSE over all origin/horizon rows. For intervals, compute empirical coverage and mean interval width. For quantiles, compute mean pinball loss per quantile and empirical quantile coverage. Report per-horizon and aggregate results.

**Constraints:** Use only P1-06 outputs and matching actuals. No random splits, alternative primary metrics, threshold, model-zoo ranking, or post-hoc tuning.

**Dependencies:** P1-06 must pass.

**Write paths:**

- `src/commodity_forecasting/phase1/evaluation.py`
- `tests/unit/test_phase1_evaluation.py`
- `docs/findings/phase1/evaluation.md`
- `docs/findings/phase1/evidence/evaluation.json`

**Tests:** Hand-calculated MAE/RMSE; interval coverage and width; quantile pinball loss and coverage; per-horizon and aggregate grouping; missing/duplicate forecast failures; no threshold field.

**Exit criteria:** The frozen metric set is reproducibly reported for every available required output and traceable to the 12-origin artifact.

**Non-goals:** A performance pass threshold, candidate ranking, or model changes.

## P1-08 — TimeCopilot Natural-Language Exercise

**Context:** Phase 1 must demonstrate the agent-level query path on the actual Arabica workflow, not only the Phase 0 synthetic contract. TimeCopilot 0.0.30 accepts a PydanticAI model/string, PydanticAI 2.28.0 provides a native DeepSeek provider, and a minimal `deepseek:deepseek-v4-flash` tool-call smoke passed; no custom DeepSeek adapter is needed.

**Scope:** Load `DEEPSEEK_API_KEY` from `.env` into the process without logging it, pass `deepseek:deepseek-v4-flash` through TimeCopilot's existing `llm` interface, and run one fixed query-specific forecast-analysis request. Record tool calls, provider/model identifiers, forecast analysis, and user-query response without secrets.

**Constraints:** Do not add a DeepSeek adapter or embed the key. The `.env` file is not evidence and must not be committed or copied. Non-empty analysis and query-specific response are required. A credential, proxy, or runtime blocker is recorded but does not complete P1-08 or Phase 1. Do not measure prose quality or build prompt infrastructure.

**Dependencies:** P1-06 must pass. P1-07 should run first in the solo sequence; P1-07 and P1-08 may run in parallel only under an explicitly coordinated team plan.

**Write paths:**

- `src/commodity_forecasting/phase1/natural_language.py`
- `tests/smoke/test_phase1_natural_language.py`
- `docs/findings/phase1/natural_language.md`
- `docs/findings/phase1/evidence/natural_language.json`

**Tests:** Native provider resolves to `deepseek-v4-flash`; `.env` key presence is checked without exposing its value; required TimeCopilot tool calls execute; analysis and query-specific answer are non-empty; evidence contains no secret material; proxy/credential failures classify as blocked without false completion.

**Exit criteria:** The Phase 1 natural-language run passes with both required outputs. Blocked or unsupported outcomes leave the task unchecked.

**Non-goals:** Provider comparison, language-quality scoring, new modalities, or prompt framework work.

## P1-09 — Evidence Rollup and Phase Exit

**Context:** Roadmap status must be derived from accepted evidence, not work claims.

**Scope:** Validate and cross-link all Phase 1 evidence, decisions, limitations, test commands, and task outcomes; publish the exit finding; update only those roadmap checkboxes backed by passing evidence.

**Constraints:** Do not convert `blocked`, `unsupported`, or `unknown` into success. Do not delete limitations. Do not change Phase 2 or deferred scope.

**Dependencies:** P1-01 through P1-08 must pass for Phase 1 exit. P1-09 may still publish an incomplete exit record when a predecessor is blocked, but it must remain unchecked.

**Write paths:**

- `src/commodity_forecasting/phase1/roadmap_exit.py`
- `tests/smoke/test_phase1_roadmap_exit.py`
- `docs/findings/phase1/exit_rollup.md`
- `docs/findings/phase1/evidence/exit_rollup.json`
- `docs/roadmap.md`

**Tests:** Required evidence inventory; file existence; evidence schema; task-to-evidence traceability; command/test status; incomplete-gate rejection; roadmap checkbox consistency; limitation preservation.

**Exit criteria:** P1-09 passes only when P1-01 through P1-08 pass and the roadmap matches the evidence. Otherwise the exit record reports the exact incomplete gate and Phase 1 remains planned/in progress.

**Non-goals:** Phase 2 execution, closeout recommendations beyond Phase 1 evidence, or unrelated documentation cleanup.

## Verification Order

1. Run the unit tests for P1-01 through P1-04 before any model execution.
2. Run only the approved P1-05 smoke matrix and select one reference.
3. Run P1-06 and validate every window before evaluation.
4. Run P1-07 and P1-08; both must pass.
5. Run P1-09, then the full unit and smoke suites plus static checks configured by the repository.
6. Re-read `docs/roadmap.md` and confirm that every checked task has linked passing evidence.
