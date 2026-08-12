# Data Scope

## 1. Purpose

Define the raw-data collection scope, minimum catalog metadata, and time-aware preparation rules for the PoC.

Datasource selection is a Phase 0 decision. Raw-data collection may be broad; model features should remain selective.

## 2. Raw Data Categories

### 1. Price & Liquidity

- ICE Coffee C prices
- Robusta futures prices
- individual contracts where accessible
- continuous front-month series
- futures curve / nearby contracts
- settlement and OHLC where available
- volume
- open interest

### 2. FX & Macro

- USD index
- BRL
- VND
- other macro series only when justified

### 3. Weather & Geospatial

- precipitation
- temperature
- soil moisture
- drought or crop-condition indicators

Prioritize economically relevant coffee-producing regions.

### 4. Market Positioning

- CFTC Commitment of Traders data
- managed-money and commercial positioning
- gross and net position measures

### 5. Physical Inventory

- ICE certified stocks
- exchange-deliverable inventory
- other clearly defined physical inventory series

### 6. Supply, Demand & Trade Flows

- production and crop estimates
- exports and imports
- consumption and shipments
- ending stocks

### 7. Cross-Market & Substitution

Raw inputs may include related market prices such as Arabica and Robusta.

Derived features may include:

- Arabica–Robusta spread
- Arabica / Robusta ratio
- calendar spreads
- curve slope

Preserve the underlying raw series separately from derived features.

## 3. Data Layers

Use three logical layers:

- **Raw:** source-faithful downloaded data.
- **Standardized:** normalized timestamps, identifiers, units, and field names.
- **Model-ready:** experiment-specific weekly target and feature tables.

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
ICE Coffee C
→ continuous front-month price
→ weekly frequency
→ last available settlement of each week
```

A provider-constructed continuous series may be used directly.

Record the provider, source identifier, and documented roll or adjustment methodology when available. Unknown roll methodology is an acceptable PoC limitation.

Phase 1 model-ready target format should be compatible with TimeCopilot:

```text
unique_id | ds | y
```

## 6. Covariate Preparation

Maintain a project-level weekly analytical dataset independent of any one model adapter.

Each candidate feature should have:

- a stable feature name;
- a documented raw source;
- a weekly aggregation rule;
- a missing-value rule;
- an availability class: `past_only`, `known_future`, `static`, or `unknown`.

Do not classify a feature as `known_future` merely because its realized future values exist in historical data.

## 7. Mandatory Time-Aware Rules

At forecast origin `T`, model inputs must not contain information that would only become available after `T`.

- Use walk-forward or rolling-origin validation.
- Do not use random train/test splits.
- Fit learned transforms only on the training window.
- Lagged and rolling features may use only current and past observations.
- Centered rolling windows are prohibited.
- Do not backward-fill past observations using future values.
- Do not interpolate across a validation boundary using future information.
- Weekly target aggregation may use only observations from that week.
- Respect known publication or release lags when aligning external data.
- Past-only covariates must end at the forecast origin.
- Future-horizon covariate values may be supplied only if they are genuinely known at the forecast origin.
- If revised historical data is used because vintage data is unavailable, record the limitation; full historical-vintage reconstruction is not required for the PoC.