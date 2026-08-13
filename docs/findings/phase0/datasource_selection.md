# Phase 0 Datasource Selection

- Selected primary: `world_bank_pink_sheet_monthly_arabica`
- Selected fallback: `not_applicable_for_static_monthly_poc`
- Recommended primary candidate: `world_bank_pink_sheet_monthly_arabica`
- Recommended fallback candidate: `deferred_api_or_ice_selection`

The official workbook is already downloaded, checksummed, preserved in the raw layer, and proven to contain the selected monthly Coffee, Arabica series. ICE Coffee C settlement and automated/API datasource selection are deferred because they are unnecessary for the lean monthly PoC.

## Phase 1 gate

Phase 1 may build the monthly Arabica target from the preserved workbook. Any API refresh path, Barchart KC*0 access, or ICE raw-contract settlement workflow is future work outside Phase 0.

The active PoC uses a monthly World Bank Arabica indicator price, not futures settlement data.

Evidence: `docs/findings/phase0/evidence/datasource_selection.json`
