# World Bank Pink Sheet Availability

## Result

The official World Bank monthly workbook downloaded successfully without datasource credentials and is preserved unchanged at `data/raw/world_bank/pink_sheet/CMO-Historical-Data-Monthly.xlsx`.

- Workbook update date: `2026-08-04`
- Monthly history: `1960M01` through `2026M07`
- Monthly observations: `799`
- Price-series columns: `71`
- Price series complete over the entire history: `48`
- SHA-256: `7902a77505ebdc5d202ce65f666c2ee1b04b626f042d7738ed3e6f7d112c8433`

## Arabica proxy

`Coffee, Arabica` contains 799 non-missing monthly observations in `$/kg`. The latest downloaded observation is `7.91` for `2026M07`.

This field is a monthly Arabica indicator-price proxy, not an ICE Coffee C settlement field. It did not satisfy the superseded weekly continuous-front-month contract and is now the adopted PoC target under `docs/adr/0001-adopt-world-bank-pink-sheet.md`.

## Candidate covariates

The same workbook contains complete monthly histories for several possible past-only covariates:

| Column | Unit | History | Missing values |
|---|---|---|---:|
| `Coffee, Robusta` | `$/kg` | 1960M01–2026M07 | 0 |
| `Cocoa` | `$/kg` | 1960M01–2026M07 | 0 |
| `Tea, avg 3 auctions` | `$/kg` | 1960M01–2026M07 | 0 |
| `Crude oil, average` | `$/bbl` | 1960M01–2026M07 | 0 |
| `Sugar, world` | `$/kg` | 1960M01–2026M07 | 0 |
| `Urea` | `$/mt` | 1960M01–2026M07 | 0 |

These columns are candidates rather than a selected feature set. Their realized monthly values are `past_only`, not `known_future`. The workbook does not embed historical release timestamps, so backtesting must align observations to publication availability and must not expose a month before its release.

Evidence: `docs/findings/phase0/evidence/world_bank_pink_sheet_availability.json`
