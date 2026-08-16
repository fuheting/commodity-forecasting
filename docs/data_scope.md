# Data Scope

## 1. Purpose

Define the raw-data collection scope, minimum catalog metadata, and time-aware preparation rules for the PoC.

The active PoC dataset is the preserved World Bank Commodity Price Data (Pink Sheet) monthly workbook. API refresh and futures settlement datasource selection are deferred future work.

## 2. Active Raw Data Scope

### World Bank Pink Sheet Workbook

- Raw artifact: `data/raw/world_bank/pink_sheet/CMO-Historical-Data-Monthly.xlsx`
- Provenance: `data/raw/world_bank/pink_sheet/source_metadata.json`
- Availability evidence: `docs/findings/phase0/world_bank_pink_sheet_availability.md`
- Target column: `Coffee, Arabica`
- Native frequency: monthly
- Unit: `$/kg`
- History: `1960M01` through `2026M07`

Candidate same-workbook covariates are past covariates:

- `Coffee, Robusta`
- `Cocoa`
- `Tea, avg 3 auctions`
- `Crude oil, average`
- `Sugar, world`
- `Urea`

The workbook does not embed historical release timestamps. Backtests must not treat a monthly observation as available before publication.

## 3. Data Layers

Use three logical layers:

- **Raw:** source-faithful downloaded data.
- **Standardized:** normalized timestamps, identifiers, units, and field names.
- **Model-ready:** experiment-specific monthly target and feature tables.

Do not overwrite raw data during cleaning or feature engineering.

## 4. Minimum Data Catalog Schema

Each catalog entry should contain:

| Field | Requirement |
|---|---|
| `dataset_id` | required |
| `category` | required |
| `name` | required |
| `source_provider` | required |
| `source_locator` | required |
| `access_method` | required |
| `native_frequency` | required |
| `fields` | required |
| `programmatic_access` | required |
| `auth_required` | required |
| `status` | required |
| `history_start` / `history_end` | if established |
| `unit` | if known |
| `availability_rule` | if relevant |
| `revision_behavior` | if known |
| `roll_methodology` | if documented |
| `license_or_usage_note` | if relevant |
| `notes` | optional |

Use explicit `unknown` values rather than inferred metadata.

## 5. Target Construction

Canonical PoC target:

```text
World Bank Pink Sheet workbook
-> Coffee, Arabica
-> monthly frequency
-> price level in $/kg
```

Phase 1 model-ready target format should be compatible with TimeCopilot:

```text
unique_id | ds | y
```

The active contract uses a 60-month historical context and a 3-month forecast horizon.

## 6. Covariate Preparation

Maintain a project-level monthly analytical dataset independent of any one model adapter.

Each candidate feature should have:

- a stable feature name;
- a documented raw source;
- a monthly alignment rule;
- a missing-value rule;
- an availability class: `past`, `future`, `static`, or `unknown`.

- **Past covariates** are known only into the past, such as measurements.
- **Future covariates** are known into the future, such as planned holidays or forecasts from another model.
- **Static covariates** are constant over time, such as product IDs or coffee origin.

The Pink Sheet workbook does not provide future covariates, so the active PoC disregards them. Its candidate time-varying covariates are past covariates.

## 7. Mandatory Time-Aware Rules

At forecast origin `T`, model inputs must not contain information that would only become available after `T`.

- Use walk-forward or rolling-origin validation.
- Do not use random data splits.
- For zero-shot Time Series Foundation Model inference, do not fit, fine-tune, calibrate, or update model weights; if a learned preprocessing transform is introduced later, fit it only on the historic-context window.
- Lagged and rolling features may use only current and past observations.
- Centered rolling windows are prohibited.
- Do not backward-fill past observations using future values.
- Do not interpolate across a validation boundary using future information.
- Monthly target preparation may use only observations available by the forecast origin.
- Respect known publication or release lags when aligning external data.
- Past covariates must end at the forecast origin.
- Do not supply future covariates in the active PoC.
- If revised historical data is used because vintage data is unavailable, record the limitation; full historical-vintage reconstruction is not required for the PoC.

## 8. Deferred Datasource Work

The active PoC does not require API datasource selection. Historical findings for Barchart, ICE, Nasdaq, FRED, NASA POWER, CFTC, USDA, FAOSTAT, UN Comtrade, and related sources remain recorded under `docs/findings/phase0/`.

Future work may revisit:

- automated World Bank acquisition or refresh;
- futures settlement sources;
- external weather, macro, positioning, supply, demand, or trade-flow covariates.

Any future datasource must preserve raw downloads separately, record unknown behavior as `unknown`, and respect publication timing.
