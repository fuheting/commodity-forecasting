# Repository Instructions

These instructions apply to the entire repository.

## Project Context

This repository is a proof-of-concept commodity price forecasting project built around TimeCopilot.

The active PoC use case is monthly forecasting of the World Bank Pink Sheet `Coffee, Arabica` price series. The authoritative PoC boundary is defined in `docs/poc_scope.md`.

Read before implementation:

1. `docs/roadmap.md`
2. `docs/poc_scope.md`
3. `docs/data_scope.md`
4. `docs/timecopilot_capabilities.md`

## Mandatory Rules

- Must NOT introduce future time leakage in dataset preparation, feature engineering, validation, or evaluation.
- Must use time-series-aware validation, such as walk-forward or rolling-origin validation.
- Must NOT use random train/test splits for forecasting evaluation.
- Must NOT assume an underlying model capability is exposed through TimeCopilot; verify adapter/integration support first.
- Must NOT add a custom covariate adapter before the Phase 0 covariate smoke test shows one is needed.
- Must preserve raw downloaded data separately from processed data and derived features.
- Must record unknown datasource behavior, such as undocumented futures roll rules, as unknown rather than infer it.
- Must keep the PoC lean; do NOT add multimodal ingestion, fine-tuning, trading logic, production infrastructure, or unnecessary frameworks.
- Must update `docs/roadmap.md` after completing a roadmap task.
- Must NOT mark a roadmap task complete without evidence that its acceptance condition was met.

## Code Style

- Prefer small, explicit Python modules and functions.
- Use type hints on public interfaces.
- Keep I/O separate from deterministic transformations where practical.
- Use explicit configuration instead of hidden global state.
- Use `pathlib` for filesystem paths.
- Raise explicit errors for unsupported states; do not silently ignore unsupported inputs.
- Keep reusable logic out of notebooks.
- Add tests for timestamp handling, target construction, feature availability, and evaluation logic.

## Task Completion

Before finishing a task:

1. run relevant tests or smoke checks;
2. verify that no future leakage was introduced;
3. update affected documentation;
4. update `docs/roadmap.md`;
5. report unresolved assumptions or limitations.
