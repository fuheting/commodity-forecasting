# Architecture

## Responsibility map

The installed package contains only reusable forecasting behavior:

```text
data inputs/configuration
        |
        v
data extraction and target codec
        |
        v
rolling-origin forecasting core <--- optional integrations
        |
        v
deterministic evaluation
        |
        v
provider-neutral analysis helpers
```

Repository workflows and tests depend inward on this core. The core never imports them.

## Production boundaries

### `commodity_forecasting.data`

Owns target rows, monthly validation, explicit workbook-source configuration, read-only extraction, and canonical target CSV parsing/serialization. Generic validation takes a `MonthlyTargetContract`; World Bank Pink Sheet assumptions are isolated in `data.sources.world_bank_pink_sheet`.

### `commodity_forecasting.forecasting`

Owns the forecast-only adapter protocol, rolling-origin configuration and windows, leakage-safe schedule construction, response reconciliation, orchestration, result validation, and deterministic CSV serialization. Model identity, context, horizon, origin count, expected dates, quantiles, and output columns enter through explicit configuration.

### `commodity_forecasting.evaluation`

Owns normalized evaluation rows, configurable origin/horizon/interval/quantile contracts, MAE, RMSE, interval coverage and width, pinball loss, quantile coverage, and aggregate/per-horizon grouping.

### `commodity_forecasting.analysis`

Owns provider-neutral dataframe construction, Unicode-stable query matching, sanitized message-history extraction, and structured analysis output normalization. Provider credentials, subprocesses, evidence publication, and roadmap behavior remain outside this package.

### `commodity_forecasting.integrations`

Owns optional external-library adapters. Imports of heavyweight or optional dependencies are lazy so deterministic package imports do not require TimeCopilot, a model runtime, credentials, or a GPU.

## Repository tooling

`tools/capability_probes` preserves the completed historical Phase 0 checks. These probes may use historical fixtures and optional dependencies; they do not define the active monthly application contract.

`tools/workflows` owns repository-specific dependency readiness, target/evidence publication, model screening and approval, runtime diagnostics, backtest/evaluation publication, natural-language live execution, and roadmap consistency. These workflows accept an explicit repository root and may depend on the reusable package. They are not imported by production code.

Historical evidence and task identifiers remain in tooling and `docs/findings`. They are deliberately absent from generic production modules.

## Test boundaries

- `tests/unit`: deterministic, focused behavior and architecture rules.
- `tests/integration`: workbook/artifact and multi-component interactions.
- `tests/acceptance`: repository workflow, evidence, publication, and historical probe contracts.
- `tests/fixtures` and `tests/support`: test-only data and builders.
- `live` marker: optional model, GPU, network, or credential checks excluded from the default suite.

An AST-based architecture test prevents production imports of `tests`, `tools`, or historical phase namespaces. A separate acceptance test verifies that accepted `data/` and `docs/findings/` files remain unchanged from the Git index.

## Explicit PoC configuration

The active workflow still intentionally fixes World Bank Arabica, 60 historic months, a 3-month horizon, three origins, the approved reference model, and recorded evidence bindings. Those values live in source-specific configuration or repository workflow modules. They are not embedded in generic data, forecasting, evaluation, or analysis behavior.

## Dependency direction

```text
tests / repository tools
            |
            v
application configuration and optional integrations
            |
            v
data -> forecasting -> evaluation / analysis helpers
```

No layer points upward. Production has no dependency on findings, roadmap state, fixtures, examples, developer diagnostics, or historical implementation phases.
