# ADR 0001: Adopt World Bank Pink Sheet for the PoC

## Context

The repository has an official World Bank Commodity Price Data workbook preserved at `data/raw/world_bank/pink_sheet/CMO-Historical-Data-Monthly.xlsx`, with provenance in `data/raw/world_bank/pink_sheet/source_metadata.json`.

Phase 0 evidence shows that the workbook contains a complete monthly `Coffee, Arabica` series from `1960M01` through `2026M07`, plus candidate monthly covariates. The factual availability record remains in `docs/findings/phase0/world_bank_pink_sheet_availability.md` and `docs/findings/phase0/evidence/world_bank_pink_sheet_availability.json`.

The original weekly ICE Coffee C settlement workflow is credential- and entitlement-gated. It is also a different target contract than the available monthly Arabica indicator price.

## Decision

Adopt the downloaded World Bank Pink Sheet workbook as the active static PoC dataset.

The active forecast contract is:

- target: World Bank `Coffee, Arabica`;
- unit: `$/kg`;
- frequency: monthly;
- historical context: 60 months;
- forecast horizon: 3 months;
- validation: time-series-aware historical backtesting.

Same-workbook covariate candidates are `past_only`; they are not `known_future` values.

## Drivers

- The workbook is already downloaded, checksummed, and preserved in the raw layer.
- The selected monthly target removes the Phase 0 credential blocker.
- The PoC stays lean and reproducible.
- The available workbook evidence does not prove ICE Coffee C settlement coverage.

## Alternatives

- Keep the weekly ICE Coffee C settlement target: rejected because access and settlement coverage remain unproven.
- Restart API datasource selection now: rejected because it is credential-gated and unnecessary for the static-workbook PoC.
- Use the workbook as supplemental covariates only: rejected because the adoption goal is to make it the active PoC dataset.

## Consequences

- The PoC forecasts a monthly Arabica indicator price, not futures settlement data.
- Futures roll methodology is not applicable to the active target.
- Historical publication timing is not embedded in the workbook, so backtests must conservatively respect publication availability.
- The static workbook does not provide automatic refresh.

## Follow-ups

- Revisit World Bank API refresh after the static PoC if automated acquisition becomes necessary.
- Revisit ICE, Barchart, or another settlement datasource only if the project returns to futures settlement forecasting.
- Record any future datasource roll rules, revision behavior, and entitlements as evidence rather than inference.
