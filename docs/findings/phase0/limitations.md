# Phase 0 Limitations

## Unknowns

- World Bank workbook historical release timestamps are not embedded, so publication availability must be enforced conservatively.
- Automated World Bank API or refresh acquisition is not selected for the PoC.
- Barchart KC*0 entitled historical settlement retrieval remains unverified future work.
- Coffee C-specific ICE history start and usage limits remain unverified future work.
- Nasdaq Data Link SCF Coffee C mapping, fields, access, and roll methodology remain unknown.
- FAOSTAT programmatic access remains unknown after the API host returned error 521.
- External-provider LLM language quality and credentials were not tested.

## Boundaries

- The active target is a World Bank monthly Arabica indicator price, not an ICE Coffee C futures settlement series.
- The workbook is a static downloaded artifact and does not provide automatic refresh.
- The covariate smoke proved an adapter exposure gap; the covariate-informed PoC experiment remains Phase 2 work.
- No predefined accuracy or calibration threshold applies, and Phase 0 did not run the real backtest.

Evidence: `docs/findings/phase0/evidence/decision_rollup.json`
