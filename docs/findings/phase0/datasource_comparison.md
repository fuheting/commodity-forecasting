# Phase 0 Datasource Comparison

The selected raw workbook is preserved under `data/raw/`; this comparison embeds metadata only.

| Candidate | Series kind | Read outcome | Coverage | Roll methodology |
|---|---|---|---|---|
| World Bank Commodity Price Data (Pink Sheet) | `static_monthly_workbook` | success | 1960M01 to 2026M07 | not_applicable |
| Barchart cmdtyView for Excel | `provider_continuous_front_month` | credential_blocked | unknown to unknown | options documented; selected=unknown; adjustment=unknown |
| ICE Futures U.S. | `raw_contracts_for_later_construction` | credential_blocked | unknown to unknown | unknown |
| Nasdaq Data Link | `unknown` | access_blocked | unknown to unknown | unknown |
| FRED | `unsupported` | success | 2026-08-03 to 2026-08-07 | not_applicable |
| World Bank Indicators API | `unsupported` | success | 2021 to 2023 | not_applicable |
| NASA POWER | `unsupported` | success | 2026-01-01 to 2026-01-05 | not_applicable |
| Copernicus CDS / ERA5 | `unsupported` | metadata_only | 1940 to present | not_applicable |
| NOAA NCEI CDO | `unsupported` | credential_blocked | unknown to unknown | not_applicable |
| CFTC Public Reporting / COT | `unsupported` | success | 2006-06-13 to 2026-08-04 | not_applicable |
| USDA FAS PSD | `unsupported` | credential_blocked | unknown to unknown | not_applicable |
| FAOSTAT | `unsupported` | provider_unavailable | unknown to unknown | not_applicable |
| UN Comtrade | `unsupported` | success | 2022 to 2022 | not_applicable |

Official source locators:

- https://www.worldbank.org/en/research/commodity-markets
- data/raw/world_bank/pink_sheet/source_metadata.json
- docs/findings/phase0/evidence/world_bank_pink_sheet_availability.json
- https://docs.barchart.com/cmdty-excel-docs/syntax-and-functions/
- https://docs.barchart.com/cmdty-excel-docs/history/
- https://www.ice.com/products/15/coffee-c-futures/data
- https://developer.ice.com/fixed-income-data-services/catalog/ice-futures-us
- https://docs.data.nasdaq.com/docs/data-organization
- https://docs.data.nasdaq.com/v1.0/docs/in-depth-usage
- https://docs.data.nasdaq.com/docs/parameters-1
- https://fred.stlouisfed.org/docs/api/fred/overview.html
- https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation
- https://power.larc.nasa.gov/docs/services/api/
- https://cds.climate.copernicus.eu/how-to-api
- https://www.ncei.noaa.gov/cdo-web/webservices/v2
- https://dev.socrata.com/foundry/publicreporting.cftc.gov/kh3c-gbw2
- https://apps.fas.usda.gov/opendata/swagger/ui/index
- https://www.fao.org/faostat/en/#data
- https://uncomtrade.org/docs/un-comtrade-api/
