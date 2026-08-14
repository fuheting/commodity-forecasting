# Phase 0 Datasource Metadata

The compact candidate metadata is embedded in `docs/findings/phase0/evidence/datasource_metadata.json`.

Local layer destinations remain separate:

- `world_bank_pink_sheet_monthly_arabica`: raw `data/raw/world_bank/pink_sheet/`; standardized `data/standardized/world_bank/pink_sheet/`
- `barchart_cmdtyview_kc_star_0`: raw `data/raw/barchart/coffee_c/`; standardized `data/standardized/barchart/coffee_c/`
- `ice_futures_us_coffee_c_contracts`: raw `data/raw/ice/coffee_c/`; standardized `data/standardized/ice/coffee_c/`
- `nasdaq_data_link_scf_candidate`: raw `data/raw/nasdaq_data_link/coffee_c/`; standardized `data/standardized/nasdaq_data_link/coffee_c/`
- `fred_fx_macro`: raw `data/raw/fred/`; standardized `data/standardized/fred/`
- `world_bank_indicators`: raw `data/raw/world_bank/`; standardized `data/standardized/world_bank/`
- `nasa_power_weather`: raw `data/raw/nasa_power/`; standardized `data/standardized/nasa_power/`
- `copernicus_cds_era5`: raw `data/raw/copernicus_era5/`; standardized `data/standardized/copernicus_era5/`
- `noaa_ncei_cdo`: raw `data/raw/noaa_cdo/`; standardized `data/standardized/noaa_cdo/`
- `cftc_cot_coffee_c`: raw `data/raw/cftc_cot/coffee_c/`; standardized `data/standardized/cftc_cot/coffee_c/`
- `usda_fas_psd`: raw `data/raw/usda_fas_psd/`; standardized `data/standardized/usda_fas_psd/`
- `faostat`: raw `data/raw/faostat/`; standardized `data/standardized/faostat/`
- `un_comtrade`: raw `data/raw/un_comtrade/coffee/`; standardized `data/standardized/un_comtrade/coffee/`

Model-ready output is intentionally deferred to Phase 1 and must not overwrite either layer.
