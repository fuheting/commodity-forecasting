# Responsibility-Based Refactor Plan

## Scope and stop condition

This refactor changes structure, naming, and dependency boundaries without adding forecasting capabilities. It is complete when:

- reusable target preparation, rolling-origin forecasting, evaluation, and analysis helpers live under `src/commodity_forecasting` in responsibility-based modules;
- historical capability probes, evidence publication, roadmap mutation, environment diagnostics, and live acceptance workflows live outside the installed package;
- no production module imports tests, fixtures, repository tools, findings, or roadmap state;
- the historical `phase0` and `phase1` Python package paths are removed rather than kept as compatibility wrappers;
- accepted data, finding, and evidence artifacts are unchanged;
- leakage-safe 60-month / 3-month / 3-origin behavior and its regression coverage remain intact;
- the test suite and configured quality gates have fresh results.

P1-09 is not part of this refactor. It remains incomplete until its separate exit-rollup acceptance evidence exists.

## Behavior lock

- Baseline test suite: `437 passed, 1 skipped` with `.venv/bin/pytest -q`.
- Baseline mypy: 23 existing errors, all in `tests/unit/test_phase1_evaluation.py`; production modules pass the configured check.
- Existing accepted files under `data/` and `docs/findings/` are treated as immutable migration fixtures.
- No live model, GPU download, network probe, or DeepSeek request is required to validate this structural change.

## Responsibility map

| Current area | Current responsibility and dependencies | Boundary problems / assumptions | Planned action |
| --- | --- | --- | --- |
| `commodity_forecasting.__init__` | Public package version | Version must remain aligned with package metadata | Keep the established public surface; avoid adding a versioning framework for this PoC |
| `phase0.contracts`, `evidence`, `guards`, `paths` | Historical evidence schemas, weekly fixture validation, catalog and roadmap gates | Mix unrelated acceptance concerns; paths reach into `tests/fixtures`; weekly assumptions are not the monthly runtime contract | Move to capability-probe tooling/test support; retain no production dependency |
| `phase0.fixtures` | Generates and hashes synthetic weekly fixtures | Test fixture generation in production; unused writers | Move only used helpers to `tests/support`; delete unused generation paths |
| `phase0.smoke_*` | Seven completed capability/data probes, report publication, and CLIs | Acceptance logic in production; TimeCopilot/environment dependencies; frozen Phase 0 assumptions | Move and rename under `tools/capability_probes`; keep historical evidence paths stable |
| `phase1.contracts` | Reader/source constants and publication-availability policy | Mixes P1-01 evidence identity, Pink Sheet configuration, and reusable time-awareness | Split reusable policy/source inputs from readiness-tool constants |
| `phase1.paths` | Implicit checkout-root and fixed artifact paths | Repository layout hidden in installed production | Move to repository tooling; require explicit roots at workflow boundaries |
| `phase1.evidence` | P1-01 evidence validation and atomic finding writes | Generic name for task-specific acceptance behavior | Rename and move with dependency-readiness tooling |
| `phase1.readiness` | Workbook probe, installed-package inspection, clean-install subprocess, evidence, roadmap, CLI | Network/filesystem/process/domain/acceptance responsibilities combined | Rename and move to workflow tooling; extract reusable month parsing/source reading |
| `phase1.target_pipeline` | Target extraction and CSV codec plus evidence/publication/roadmap/CLI | Reusable transformation depends on readiness/evidence and hard-coded Arabica paths/identity | Extract source configuration, target rows, workbook reader, and CSV codec to `data`; keep publication workflow in tools |
| `phase1.screening` | Frozen model inventory, source validation, package/AST observation, report publication, roadmap, CLI | 1,847-line historical acceptance module with embedded catalogs | Move to model-screening tooling; split schema/observation/publication where it reduces coupling |
| `phase1.selection` | Approval record validation/publication and runtime gate | Human approval artifact logic presented as runtime production | Move and rename to shortlist-approval tooling |
| `phase1.runtime_compatibility` | CUDA discovery, subprocess workers, adapter attempts, output validation, selection, evidence/roadmap/CLI | Diagnostics, integration, orchestration, and acceptance combined | Move to runtime-compatibility tooling; keep only reusable adapter/result normalization in integrations if needed |
| `phase1.rolling_origin` | Schedule, leakage controls, adapter protocol, response reconciliation, CSV, live adapter, evidence/publication/roadmap/CLI | Core forecast logic coupled to exact P1-05 hash/model/dates and repository artifacts | Extract configurable backtesting core and TimeCopilot adapter; keep PoC publication workflow in tools |
| `phase1.evaluation` | Input normalization, metrics, grouped results, evidence/publication/roadmap/CLI | Generic metrics coupled to fixed P1-07 artifact schema | Extract evaluation core; keep fixed evidence/publication workflow in tools |
| `phase1.natural_language` | Credentials, input loading, dataframe construction, agent execution, message parsing, evidence/publication, subprocess/CLI | Provider, model, query, artifact, environment, and acceptance behavior combined | Extract reusable analysis input/result helpers; move live/evidence workflow to tools |
| `tests/smoke` | Mixture of historical probes, fake-adapter integration, mocked units, and live gates | Test classification does not describe dependencies or behavior | Reorganize into `unit`, `integration`, and `acceptance`; isolate live tests with explicit markers |
| oversized `tests/unit/test_phase1_*` | Strong regression coverage for schemas, publication, CLI, and core math | Names follow milestones; several are integration/acceptance tests | Rename/move by capability; split only where responsibility boundaries are clear |
| `pyproject.toml`, README, `.env.example` | Minimal packaging and stale project guidance | Mypy not declared in dev extra; no test tiers; README status and credential example stale | Update dependency/test metadata and document the new responsibility/command surface |

## Project-specific assumption classification

- Generic production behavior: finite numeric serialization, canonical monthly CSV parsing, leakage-safe schedule construction, adapter protocol, response validation, MAE/RMSE/interval/quantile metrics, query-token/result extraction.
- Explicit configuration/input: World Bank workbook sheet/column/hash, target ID, expected date range, context/horizon/origin counts, selected model, quantiles, provider/query.
- Test or acceptance behavior: P1 task IDs, evidence schemas, exact evidence hashes/run IDs, finding paths, roadmap regexes, GPU/environment probes, clean-install checks, secret-safe diagnostic publication.
- Example/historical behavior: weekly Coffee C fixtures and completed Phase 0 capability probes.
- Obsolete behavior: unused fixture writers, unused path helpers, empty phase namespaces, duplicate internal entry paths after migration.

## Cleanup passes

1. Add architecture/import-boundary and artifact-immutability regression checks.
2. Move Phase 0 probes and fixture helpers out of production; remove production-to-test imports.
3. Extract target preparation, backtesting, evaluation, and analysis core modules with explicit configuration.
4. Move and rename remaining readiness, screening, approval, runtime, publication, and roadmap workflows under `tools`.
5. Reorganize tests by capability/tier and update all imports and subprocess command paths.
6. Delete both phase packages, duplicate implementations, unused helpers, and obsolete internal entrypoints.
7. Update package metadata, README, architecture documentation, task-history notes, and roadmap maintenance evidence.
8. Run targeted tests after each boundary, then full pytest, mypy, bytecode compilation, package build/install smoke, and an import-boundary audit.

## Fallback review gate

Broad exception handling in live/evidence workflows is preserved only where it converts external failures into explicit, sanitized non-pass evidence and has regression coverage. Silent defaults, swallowed failures, environment-based test mutation, duplicate execution paths, and compatibility shims will be removed. Ambiguous fallback behavior will stay outside the reusable core and be called out in the final report.
