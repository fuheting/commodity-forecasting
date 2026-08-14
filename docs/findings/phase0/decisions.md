# Phase 0 Decisions

## Covariate

T0 native known-future covariates executed; TimeCopilot 0.0.30 T0 adapter omits them, so scoped compatible-adapter work is roadmapped.

Evidence: `docs/findings/phase0/evidence/covariate_support.json`

## Probabilistic

TimeCopilot 0.0.30 T0 adapter is selected for quantiles and level-derived intervals; simultaneous level and quantiles is unsupported.

Evidence: `docs/findings/phase0/evidence/probabilistic_adapters.json`

## Natural Language

The credential-free deterministic TimeCopilot agent/tool contract passed all four tool calls and returned query-specific analysis.

Evidence: `docs/findings/phase0/evidence/natural_language.json`

## Datasource

The downloaded World Bank Pink Sheet workbook is selected as the static monthly PoC source for Coffee, Arabica. ICE, Barchart, Nasdaq, and API refresh selection remain future work.

Evidence: `docs/findings/phase0/evidence/datasource_selection.json`

## Catalog

The initial monthly Arabica catalog passed schema and layer separation with the selected workbook target source and deferred futures/API candidates.

Evidence: `docs/findings/phase0/evidence/data_catalog.json`
