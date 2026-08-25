# Commodity Price Forecasting with TimeCopilot

A lean proof of concept for monthly probabilistic forecasting of the World Bank Pink Sheet `Coffee, Arabica` price series.

The fixed experiment uses a 60-month history, a 3-month horizon, and three one-month-step rolling origins. It reports point and probabilistic metrics without a performance threshold. The validation is revised-workbook pseudo-real-time, not historical-vintage real-time.

## Status

Phase 0 discovery and Phase 1 execution tasks P1-01 through P1-09 are complete. The P1-09 exit rollup validates that the Phase 1 roadmap matches passing canonical evidence.

See `docs/roadmap.md` for evidence-linked status and `docs/architecture.md` for the code layout.

## Structure

```text
src/commodity_forecasting/   reusable installed code
  data/                      target contracts, workbook extraction, CSV codec
  forecasting/               leakage-safe rolling-origin orchestration
  evaluation/                deterministic point and probabilistic metrics
  analysis/                  provider-neutral analysis/result helpers
  integrations/              optional external-library adapters

tools/
  capability_probes/         completed historical capability checks
  workflows/                 repository evidence, runtime, and publication workflows

tests/
  unit/                      focused deterministic behavior
  integration/               component and artifact interactions
  acceptance/                repository evidence and workflow contracts
  fixtures/                  historical probe inputs
  support/                   test-only builders
```

Production code does not import repository tools, tests, findings, roadmap state, or historical phase packages.

## Setup

Python 3.10 or newer is required.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Install the optional TimeCopilot runtime only for explicit live checks:

```bash
.venv/bin/python -m pip install -e '.[dev,live]'
```

## Verification

The default suite is credential-free and excludes tests marked `live`:

```bash
.venv/bin/pytest -q
.venv/bin/mypy src tools tests
```

Run optional live checks explicitly after installing the `live` extra and satisfying their GPU, network, cache, or credential prerequisites:

```bash
.venv/bin/pytest -q -m live
```

The P1-08 live exercise reads `DEEPSEEK_API_KEY` from `.env`; the value is never written to evidence.

## Repository workflows

Repository-specific evidence and roadmap operations are intentionally not installed as application APIs. Run them from the checkout with an explicit root. Examples:

```bash
.venv/bin/python -m tools.workflows.target_publication publish --repo-root "$PWD"
.venv/bin/python -m tools.workflows.backtest_publication --repo-root "$PWD" --validate-publication
.venv/bin/python -m tools.workflows.evaluation_publication --repo-root "$PWD" --validate-publication
.venv/bin/python -m tools.workflows.natural_language_exercise --repo-root "$PWD" --validate-publication
```

Use each module's `--help` for its publish, validate, live, and roadmap actions. Historical evidence and accepted data remain under `docs/findings/` and `data/`; refactoring does not regenerate them.

Multimodal input, fine-tuning, trading logic, production infrastructure, new datasource acquisition, and speculative covariate adapters remain out of scope.
