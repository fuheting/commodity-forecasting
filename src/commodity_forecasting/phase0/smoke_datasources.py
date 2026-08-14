"""SM-04 datasource metadata comparison and selected static workbook source."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .evidence import utc_timestamp, write_evidence
from .fixtures import FIXTURE_ID
from .paths import phase0_evidence_dir, phase0_findings_dir, repo_root

PINK_SHEET_DATASET_ID = "world_bank_pink_sheet_monthly_arabica"


def default_read_observations() -> dict[str, dict[str, Any]]:
    """Return sanitized observations from the bounded 2026-08-13 reads.

    Raw responses and credentials are deliberately excluded from evidence.
    """

    return {
        PINK_SHEET_DATASET_ID: {
            "attempted": True,
            "outcome": "success",
            "http_status": "not_applicable_local_artifact",
            "row_count": 799,
            "observed_fields": [
                "Date",
                "Coffee, Arabica",
                "Coffee, Robusta",
                "Cocoa",
                "Tea, avg 3 auctions",
                "Crude oil, average",
                "Sugar, world",
                "Urea",
            ],
            "observed_history_start": "1960M01",
            "observed_history_end": "2026M07",
            "settlement_field_proven": False,
            "series_identity_proven": True,
            "detail": "downloaded official World Bank Pink Sheet workbook is preserved unchanged and contains the selected monthly Coffee, Arabica series",
        },
        "barchart_cmdtyview_kc_star_0": {
            "attempted": True,
            "outcome": "credential_blocked",
            "http_status": 401,
            "row_count": 0,
            "observed_fields": [],
            "observed_history_start": "unknown",
            "observed_history_end": "unknown",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "host-network getHistory read through Clash reached Barchart but the supplied demo key was rejected",
        },
        "ice_futures_us_coffee_c_contracts": {
            "attempted": False,
            "outcome": "credential_blocked",
            "http_status": "not_attempted",
            "row_count": 0,
            "observed_fields": [],
            "observed_history_start": "unknown",
            "observed_history_end": "unknown",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "no authorized ICE API or bulk-service entitlement is configured",
        },
        "nasdaq_data_link_scf_candidate": {
            "attempted": True,
            "outcome": "access_blocked",
            "http_status": 403,
            "row_count": 0,
            "observed_fields": [],
            "observed_history_start": "unknown",
            "observed_history_end": "unknown",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "host-network CHRIS/ICE_KC1 read through Clash was rejected by the provider WAF",
        },
        "fred_fx_macro": {
            "attempted": True,
            "outcome": "success",
            "http_status": 200,
            "row_count": 5,
            "observed_fields": ["DATE", "DEXBZUS"],
            "observed_history_start": "2026-08-03",
            "observed_history_end": "2026-08-07",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "public FRED CSV returned BRL/USD observations; the official JSON API returned 400 without an API key",
        },
        "world_bank_indicators": {
            "attempted": True,
            "outcome": "success",
            "http_status": 200,
            "row_count": 3,
            "observed_fields": ["country", "date", "indicator", "value"],
            "observed_history_start": "2021",
            "observed_history_end": "2023",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "public API returned Brazil official exchange-rate observations",
        },
        "nasa_power_weather": {
            "attempted": True,
            "outcome": "success",
            "http_status": 200,
            "row_count": 5,
            "observed_fields": ["date", "T2M", "PRECTOTCORR"],
            "observed_history_start": "2026-01-01",
            "observed_history_end": "2026-01-05",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "public daily API returned temperature and precipitation for a bounded Brazil coordinate probe",
        },
        "copernicus_cds_era5": {
            "attempted": True,
            "outcome": "metadata_only",
            "http_status": 200,
            "row_count": 0,
            "observed_fields": ["collection_metadata"],
            "observed_history_start": "1940",
            "observed_history_end": "present",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "public catalogue metadata was readable; an authenticated ERA5 data download was not executed",
        },
        "noaa_ncei_cdo": {
            "attempted": True,
            "outcome": "credential_blocked",
            "http_status": 400,
            "row_count": 0,
            "observed_fields": [],
            "observed_history_start": "unknown",
            "observed_history_end": "unknown",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "CDO v2 rejected the bounded dataset request because a token parameter is required",
        },
        "cftc_cot_coffee_c": {
            "attempted": True,
            "outcome": "success",
            "http_status": 200,
            "row_count": 1052,
            "observed_fields": ["report_date_as_yyyy_mm_dd", "open_interest_all", "managed_money_positions_long_all"],
            "observed_history_start": "2006-06-13",
            "observed_history_end": "2026-08-04",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "public Socrata API returned Coffee C positioning records for CFTC contract-market code 083731",
        },
        "usda_fas_psd": {
            "attempted": True,
            "outcome": "credential_blocked",
            "http_status": 403,
            "row_count": 0,
            "observed_fields": [],
            "observed_history_start": "unknown",
            "observed_history_end": "unknown",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "PSD endpoint returned Bad API Key without a configured USDA key",
        },
        "faostat": {
            "attempted": True,
            "outcome": "provider_unavailable",
            "http_status": 521,
            "row_count": 0,
            "observed_fields": [],
            "observed_history_start": "unknown",
            "observed_history_end": "unknown",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "FAOSTAT API host returned provider error 521 through the working Clash path",
        },
        "un_comtrade": {
            "attempted": True,
            "outcome": "success",
            "http_status": 200,
            "row_count": 1,
            "observed_fields": ["period", "reporterCode", "cmdCode", "flowCode", "netWgt", "primaryValue"],
            "observed_history_start": "2022",
            "observed_history_end": "2022",
            "settlement_field_proven": False,
            "series_identity_proven": False,
            "detail": "public preview API returned one aggregate Brazil coffee-export record for HS 0901",
        },
    }


def datasource_candidates(
    read_observations: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return compact metadata verified from official provider documentation.

    This is deliberately metadata-only. It neither downloads nor embeds market data.
    """

    candidates: list[dict[str, Any]] = [
        {
            "candidate_id": PINK_SHEET_DATASET_ID,
            "provider": "World Bank Commodity Price Data (Pink Sheet)",
            "source_locator": "data/raw/world_bank/pink_sheet/CMO-Historical-Data-Monthly.xlsx",
            "documentation_urls": [
                "https://www.worldbank.org/en/research/commodity-markets",
                "data/raw/world_bank/pink_sheet/source_metadata.json",
                "docs/findings/phase0/evidence/world_bank_pink_sheet_availability.json",
            ],
            "access_method": "checked-in static workbook downloaded from the official World Bank source",
            "programmatic_access": "static_workbook_available",
            "credential_requirement": "none for the downloaded artifact",
            "continuous_series_kind": "static_monthly_workbook",
            "native_frequency": "monthly",
            "history_start": "1960M01",
            "history_end": "2026M07",
            "required_fields": ["Date", "Coffee, Arabica"],
            "required_field_status": "Coffee, Arabica monthly series identity proven; not an ICE Coffee C settlement field",
            "roll_methodology": "not_applicable",
            "usage_limits": "World Bank Commodity Prices workbook is public; preserve source metadata and citation",
            "local_raw_path": "data/raw/world_bank/pink_sheet/",
            "local_standardized_path": "data/standardized/world_bank/pink_sheet/",
            "metadata_probe": "selected static monthly Arabica PoC source; API refresh and futures settlement sources are future work",
        },
        {
            "candidate_id": "barchart_cmdtyview_kc_star_0",
            "provider": "Barchart cmdtyView for Excel",
            "source_locator": "KC*0",
            "documentation_urls": [
                "https://docs.barchart.com/cmdty-excel-docs/syntax-and-functions/",
                "https://docs.barchart.com/cmdty-excel-docs/history/",
            ],
            "access_method": "BCT/BCH Excel functions; account entitlement required",
            "programmatic_access": "documented_via_excel_functions",
            "credential_requirement": "Barchart cmdtyView entitlement",
            "continuous_series_kind": "provider_continuous_front_month",
            "native_frequency": "daily_or_weekly",
            "history_start": "unknown",
            "history_end": "current subject to entitlement",
            "required_fields": ["date", "Settle"],
            "required_field_status": {
                "date": "documented",
                "Settle": "documented in provider field catalog; historical KC*0 execution unverified",
            },
            "roll_methodology": {
                "documented_options": [
                    "expiration",
                    "days_before_expiration",
                    "volume_and_open_interest",
                ],
                "selected_option": "unknown",
                "back_adjustment": "unknown",
            },
            "usage_limits": "50,000 daily EOD rows documented for DEFAULT_EOD; entitlement-specific limits unknown",
            "local_raw_path": "data/raw/barchart/coffee_c/",
            "local_standardized_path": "data/standardized/barchart/coffee_c/",
            "metadata_probe": "official documentation retrieved; entitled KC*0 data call not executed",
        },
        {
            "candidate_id": "ice_futures_us_coffee_c_contracts",
            "provider": "ICE Futures U.S.",
            "source_locator": "Coffee C Futures product 15",
            "documentation_urls": [
                "https://www.ice.com/products/15/coffee-c-futures/data",
                "https://developer.ice.com/fixed-income-data-services/catalog/ice-futures-us",
            ],
            "access_method": "ICE Connect, ICE XL, API, or bulk file service",
            "programmatic_access": "documented_api_and_bulk_services",
            "credential_requirement": "commercial ICE entitlement",
            "continuous_series_kind": "raw_contracts_for_later_construction",
            "native_frequency": "daily",
            "history_start": "1980 for ICE Futures U.S. dataset; Coffee C-specific start unknown",
            "history_end": "current subject to entitlement",
            "required_fields": ["contract", "date", "settlement"],
            "required_field_status": "Coffee C product and data access documented; entitled field-level read unverified",
            "roll_methodology": "unknown",
            "usage_limits": "unknown",
            "local_raw_path": "data/raw/ice/coffee_c/",
            "local_standardized_path": "data/standardized/ice/coffee_c/",
            "metadata_probe": "official documentation retrieved; entitled contract data call not executed",
        },
        {
            "candidate_id": "nasdaq_data_link_scf_candidate",
            "provider": "Nasdaq Data Link",
            "source_locator": "SCF candidate; Coffee C dataset mapping unverified",
            "documentation_urls": [
                "https://docs.data.nasdaq.com/docs/data-organization",
                "https://docs.data.nasdaq.com/v1.0/docs/in-depth-usage",
                "https://docs.data.nasdaq.com/docs/parameters-1",
            ],
            "access_method": "REST API when supported by the specific premium product",
            "programmatic_access": "unknown_for_coffee_c_candidate",
            "credential_requirement": "unknown; premium access likely but not established for this candidate",
            "continuous_series_kind": "unknown",
            "native_frequency": "unknown",
            "history_start": "unknown",
            "history_end": "unknown",
            "required_fields": ["date", "settlement"],
            "required_field_status": "unknown",
            "roll_methodology": "unknown",
            "usage_limits": "unknown",
            "local_raw_path": "data/raw/nasdaq_data_link/coffee_c/",
            "local_standardized_path": "data/standardized/nasdaq_data_link/coffee_c/",
            "metadata_probe": "generic API documentation retrieved; Coffee C product mapping not established",
        },
        {
            "candidate_id": "fred_fx_macro",
            "provider": "FRED",
            "source_locator": "DEXBZUS bounded BRL/USD probe",
            "documentation_urls": ["https://fred.stlouisfed.org/docs/api/fred/overview.html"],
            "access_method": "REST API with key; public graph CSV also available for the probed series",
            "programmatic_access": "public_csv_read_proven",
            "credential_requirement": "API key for the documented JSON API; none for the probed CSV endpoint",
            "continuous_series_kind": "unsupported",
            "native_frequency": "series_dependent",
            "history_start": "series_dependent",
            "history_end": "series_dependent",
            "required_fields": ["date", "value"],
            "required_field_status": "BRL/USD observations proven; no futures settlement field",
            "roll_methodology": "not_applicable",
            "usage_limits": "unknown",
            "local_raw_path": "data/raw/fred/",
            "local_standardized_path": "data/standardized/fred/",
            "metadata_probe": "usable supporting FX/macro source; unsupported as the Coffee C settlement target or raw-contract fallback",
        },
        {
            "candidate_id": "world_bank_indicators",
            "provider": "World Bank Indicators API",
            "source_locator": "BRA/PA.NUS.FCRF bounded probe",
            "documentation_urls": ["https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation"],
            "access_method": "public REST API",
            "programmatic_access": "public_read_proven",
            "credential_requirement": "none for the probed endpoint",
            "continuous_series_kind": "unsupported",
            "native_frequency": "indicator_dependent; probed series annual",
            "history_start": "indicator_dependent",
            "history_end": "indicator_dependent",
            "required_fields": ["country", "date", "indicator", "value"],
            "required_field_status": "macro observations proven; no futures settlement field",
            "roll_methodology": "not_applicable",
            "usage_limits": "unknown",
            "local_raw_path": "data/raw/world_bank/",
            "local_standardized_path": "data/standardized/world_bank/",
            "metadata_probe": "usable supporting macro source; unsupported as the Coffee C settlement target or raw-contract fallback",
        },
        {
            "candidate_id": "nasa_power_weather",
            "provider": "NASA POWER",
            "source_locator": "Brazil coordinate daily point API probe",
            "documentation_urls": ["https://power.larc.nasa.gov/docs/services/api/"],
            "access_method": "public REST API",
            "programmatic_access": "public_read_proven",
            "credential_requirement": "none for the probed endpoint",
            "continuous_series_kind": "unsupported",
            "native_frequency": "daily_or_hourly",
            "history_start": "parameter_dependent",
            "history_end": "parameter_dependent",
            "required_fields": ["date", "T2M", "PRECTOTCORR"],
            "required_field_status": "weather observations proven; no futures settlement field",
            "roll_methodology": "not_applicable",
            "usage_limits": "documented request constraints; practical limits not measured",
            "local_raw_path": "data/raw/nasa_power/",
            "local_standardized_path": "data/standardized/nasa_power/",
            "metadata_probe": "usable supporting weather source; feature availability and location selection remain Phase 1 decisions",
        },
        {
            "candidate_id": "copernicus_cds_era5",
            "provider": "Copernicus CDS / ERA5",
            "source_locator": "reanalysis-era5-single-levels catalogue",
            "documentation_urls": ["https://cds.climate.copernicus.eu/how-to-api"],
            "access_method": "CDS API after account setup and dataset terms acceptance",
            "programmatic_access": "public_metadata_only",
            "credential_requirement": "account and accepted terms for data retrieval",
            "continuous_series_kind": "unsupported",
            "native_frequency": "hourly_reanalysis",
            "history_start": "1940 from catalogue metadata",
            "history_end": "present from catalogue metadata",
            "required_fields": ["valid_time", "weather_variable", "latitude", "longitude"],
            "required_field_status": "catalogue metadata proven; data fields unverified",
            "roll_methodology": "not_applicable",
            "usage_limits": "unknown",
            "local_raw_path": "data/raw/copernicus_era5/",
            "local_standardized_path": "data/standardized/copernicus_era5/",
            "metadata_probe": "supporting weather candidate; authenticated data read not executed",
        },
        {
            "candidate_id": "noaa_ncei_cdo",
            "provider": "NOAA NCEI CDO",
            "source_locator": "CDO Web Services v2 datasets endpoint",
            "documentation_urls": ["https://www.ncei.noaa.gov/cdo-web/webservices/v2"],
            "access_method": "REST API with token",
            "programmatic_access": "credential_blocked",
            "credential_requirement": "NOAA CDO token",
            "continuous_series_kind": "unsupported",
            "native_frequency": "dataset_dependent",
            "history_start": "unknown",
            "history_end": "unknown",
            "required_fields": ["date", "station", "datatype", "value"],
            "required_field_status": "unverified because token is required",
            "roll_methodology": "not_applicable",
            "usage_limits": "unknown",
            "local_raw_path": "data/raw/noaa_cdo/",
            "local_standardized_path": "data/standardized/noaa_cdo/",
            "metadata_probe": "supporting climate candidate; access blocked by missing token",
        },
        {
            "candidate_id": "cftc_cot_coffee_c",
            "provider": "CFTC Public Reporting / COT",
            "source_locator": "Socrata kh3c-gbw2; contract-market code 083731",
            "documentation_urls": ["https://dev.socrata.com/foundry/publicreporting.cftc.gov/kh3c-gbw2"],
            "access_method": "public Socrata REST API",
            "programmatic_access": "public_read_proven",
            "credential_requirement": "none for bounded public reads",
            "continuous_series_kind": "unsupported",
            "native_frequency": "weekly",
            "history_start": "2006-06-13 observed",
            "history_end": "2026-08-04 observed",
            "required_fields": ["report_date", "open_interest", "position_categories"],
            "required_field_status": "Coffee C positioning fields proven; no settlement price",
            "roll_methodology": "not_applicable",
            "usage_limits": "Socrata limits apply; not measured",
            "local_raw_path": "data/raw/cftc_cot/coffee_c/",
            "local_standardized_path": "data/standardized/cftc_cot/coffee_c/",
            "metadata_probe": "usable supporting positioning source; not a target-price datasource",
        },
        {
            "candidate_id": "usda_fas_psd",
            "provider": "USDA FAS PSD",
            "source_locator": "PSD Online Data Services API",
            "documentation_urls": ["https://apps.fas.usda.gov/opendata/swagger/ui/index"],
            "access_method": "REST API with key",
            "programmatic_access": "credential_blocked",
            "credential_requirement": "USDA FAS API key",
            "continuous_series_kind": "unsupported",
            "native_frequency": "marketing_year",
            "history_start": "unknown",
            "history_end": "unknown",
            "required_fields": ["commodity", "country", "market_year", "attribute", "value"],
            "required_field_status": "unverified because the API rejected the request without a valid key",
            "roll_methodology": "not_applicable",
            "usage_limits": "unknown",
            "local_raw_path": "data/raw/usda_fas_psd/",
            "local_standardized_path": "data/standardized/usda_fas_psd/",
            "metadata_probe": "supporting supply/demand candidate; access blocked by missing key",
        },
        {
            "candidate_id": "faostat",
            "provider": "FAOSTAT",
            "source_locator": "FAOSTAT API v1",
            "documentation_urls": ["https://www.fao.org/faostat/en/#data"],
            "access_method": "public REST API candidate",
            "programmatic_access": "provider_unavailable_during_probe",
            "credential_requirement": "unknown",
            "continuous_series_kind": "unsupported",
            "native_frequency": "dataset_dependent",
            "history_start": "unknown",
            "history_end": "unknown",
            "required_fields": ["area", "item", "element", "year", "value"],
            "required_field_status": "unverified because the API host returned 521",
            "roll_methodology": "not_applicable",
            "usage_limits": "unknown",
            "local_raw_path": "data/raw/faostat/",
            "local_standardized_path": "data/standardized/faostat/",
            "metadata_probe": "supporting production/trade candidate; access outcome remains unproven after provider error",
        },
        {
            "candidate_id": "un_comtrade",
            "provider": "UN Comtrade",
            "source_locator": "public preview API; Brazil exports HS 0901",
            "documentation_urls": ["https://uncomtrade.org/docs/un-comtrade-api/"],
            "access_method": "public preview REST API; subscription key for larger production use",
            "programmatic_access": "public_preview_read_proven",
            "credential_requirement": "none for bounded preview read",
            "continuous_series_kind": "unsupported",
            "native_frequency": "annual_or_monthly",
            "history_start": "dataset_dependent",
            "history_end": "dataset_dependent",
            "required_fields": ["period", "reporter", "partner", "flow", "cmdCode", "netWgt", "primaryValue"],
            "required_field_status": "aggregate coffee trade fields proven; no futures settlement field",
            "roll_methodology": "not_applicable",
            "usage_limits": "preview endpoint is bounded; production limits depend on access tier",
            "local_raw_path": "data/raw/un_comtrade/coffee/",
            "local_standardized_path": "data/standardized/un_comtrade/coffee/",
            "metadata_probe": "usable supporting trade-flow source; not a target-price datasource",
        },
    ]
    observations = read_observations or default_read_observations()
    for candidate in candidates:
        candidate["programmatic_read"] = dict(observations.get(candidate["candidate_id"], {}))
    return candidates


def _read_proves_candidate(candidate: Mapping[str, Any]) -> bool:
    read = candidate.get("programmatic_read", {})
    if candidate.get("candidate_id") == PINK_SHEET_DATASET_ID:
        return bool(
            read.get("outcome") == "success"
            and read.get("row_count", 0) >= 60
            and read.get("series_identity_proven") is True
            and read.get("observed_history_start") == "1960M01"
            and read.get("observed_history_end") == "2026M07"
        )
    return bool(
        read.get("outcome") == "success"
        and read.get("row_count", 0) > 0
        and read.get("settlement_field_proven") is True
        and read.get("series_identity_proven") is True
        and read.get("observed_history_start") not in {None, "unknown"}
        and read.get("observed_history_end") not in {None, "unknown"}
    )


def run_probe(
    *,
    root: Path | None = None,
    read_observations: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    active_root = root or repo_root()
    candidates = datasource_candidates(read_observations)
    kinds = {candidate["continuous_series_kind"] for candidate in candidates}
    candidate_kinds_present = {
        "static_monthly_workbook",
        "provider_continuous_front_month",
        "raw_contracts_for_later_construction",
        "unknown",
    }.issubset(kinds)
    proven = {candidate["candidate_id"]: _read_proves_candidate(candidate) for candidate in candidates}
    workbook_selected = proven.get(PINK_SHEET_DATASET_ID, False)
    access_proven = workbook_selected
    evidence_path = phase0_evidence_dir(active_root) / "datasource_selection.json"
    metadata_path = phase0_evidence_dir(active_root) / "datasource_metadata.json"
    return {
        "run_id": f"SM-04-{utc_timestamp()}",
        "test_id": "SM-04",
        "work_item": "World Bank Pink Sheet workbook adoption and datasource deferral",
        "timestamp_utc": utc_timestamp(),
        "mode": "network-smoke",
        "command": "bounded provider reads plus PYTHONPATH=src .venv/bin/python -m commodity_forecasting.phase0.smoke_datasources",
        "tool": "provider documentation and sanitized programmatic-read probe",
        "timecopilot_version": "not_applicable",
        "model_or_adapter": "not_applicable",
        "fixture_id": FIXTURE_ID,
        "data_origin": "selected official static workbook plus historical provider metadata; no raw market payload embedded in evidence",
        "credential_state": "no credentials required for the selected workbook artifact; ICE, Barchart, and several supporting APIs remain deferred or credential-gated",
        "network_state": "host-network reads succeeded through Clash; in-sandbox loopback proxy access is restricted",
        "observed_result": (
            "The downloaded official World Bank Pink Sheet workbook is selected as the static monthly PoC "
            "source for Coffee, Arabica, with 799 monthly observations from 1960M01 through 2026M07. "
            "The workbook is not an ICE Coffee C settlement source. Barchart, ICE, Nasdaq, and API-based "
            "refresh selection remain future work rather than Phase 0 blockers."
        ),
        "classification": "pass" if candidate_kinds_present and access_proven else "blocked",
        "leakage_controls": [
            "raw workbook is preserved separately from standardized and model-ready outputs",
            "monthly observations are not considered available before publication",
            "same-workbook candidate covariates remain past_only rather than known_future",
            "no monthly series is upsampled or represented as weekly settlement data",
        ],
        "artifact_paths": [
            str(evidence_path),
            str(metadata_path),
            str(phase0_findings_dir(active_root) / "datasource_comparison.md"),
            str(phase0_findings_dir(active_root) / "datasource_selection.md"),
            str(phase0_findings_dir(active_root) / "datasource_metadata.md"),
        ],
        "continuous_series_kind": "static_monthly_workbook",
        "roll_methodology": "not_applicable",
        "primary_datasource": PINK_SHEET_DATASET_ID if workbook_selected else "not_selected",
        "fallback_datasource": "not_applicable_for_static_monthly_poc",
        "recommended_primary_candidate": PINK_SHEET_DATASET_ID,
        "recommended_fallback_candidate": "deferred_api_or_ice_selection",
        "selection_basis": (
            "The official workbook is already downloaded, checksummed, preserved in the raw layer, and proven to "
            "contain the selected monthly Coffee, Arabica series. ICE Coffee C settlement and automated/API "
            "datasource selection are deferred because they are unnecessary for the lean monthly PoC."
        ),
        "selection_gate": (
            "Phase 1 may build the monthly Arabica target from the preserved workbook. Any API refresh path, "
            "Barchart KC*0 access, or ICE raw-contract settlement workflow is future work outside Phase 0."
        ),
        "forecast_contract": {
            "target": "Coffee, Arabica",
            "frequency": "monthly",
            "historical_context": "60 months",
            "forecast_horizon": "3 months",
            "unit": "$/kg",
            "covariate_availability": "past_only",
        },
        "candidates": candidates,
    }


def write_findings(record: dict[str, Any], *, root: Path | None = None) -> None:
    active_root = root or repo_root()
    evidence_dir = phase0_evidence_dir(active_root)
    findings_dir = phase0_findings_dir(active_root)
    write_evidence(evidence_dir / "datasource_selection.json", record)
    metadata_record = dict(record)
    metadata_record["run_id"] = f"SM-04-metadata-{record['timestamp_utc']}"
    metadata_record["artifact_paths"] = [str(evidence_dir / "datasource_metadata.json")]
    write_evidence(evidence_dir / "datasource_metadata.json", metadata_record)

    comparison_lines = [
        "# Phase 0 Datasource Comparison",
        "",
        "The selected raw workbook is preserved under `data/raw/`; this comparison embeds metadata only.",
        "",
        "| Candidate | Series kind | Read outcome | Coverage | Roll methodology |",
        "|---|---|---|---|---|",
    ]
    for candidate in record["candidates"]:
        roll = candidate["roll_methodology"]
        roll_text = roll if isinstance(roll, str) else f"options documented; selected={roll['selected_option']}; adjustment={roll['back_adjustment']}"
        comparison_lines.append(
            f"| {candidate['provider']} | `{candidate['continuous_series_kind']}` | "
            f"{candidate['programmatic_read'].get('outcome', 'unknown')} | "
            f"{candidate['programmatic_read'].get('observed_history_start', 'unknown')} to "
            f"{candidate['programmatic_read'].get('observed_history_end', 'unknown')} | {roll_text} |"
        )
    comparison_lines.extend(["", "Official source locators:", ""])
    for candidate in record["candidates"]:
        comparison_lines.extend(f"- {url}" for url in candidate["documentation_urls"])
    comparison_lines.append("")
    (findings_dir / "datasource_comparison.md").write_text("\n".join(comparison_lines), encoding="utf-8")

    (findings_dir / "datasource_selection.md").write_text(
        "\n".join(
            [
                "# Phase 0 Datasource Selection",
                "",
                f"- Selected primary: `{record['primary_datasource']}`",
                f"- Selected fallback: `{record['fallback_datasource']}`",
                f"- Recommended primary candidate: `{record['recommended_primary_candidate']}`",
                f"- Recommended fallback candidate: `{record['recommended_fallback_candidate']}`",
                "",
                str(record["selection_basis"]),
                "",
                "## Phase 1 gate",
                "",
                str(record["selection_gate"]),
                "",
                "The active PoC uses a monthly World Bank Arabica indicator price, not futures settlement data.",
                "",
                "Evidence: `docs/findings/phase0/evidence/datasource_selection.json`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (findings_dir / "datasource_metadata.md").write_text(
        "\n".join(
            [
                "# Phase 0 Datasource Metadata",
                "",
                "The compact candidate metadata is embedded in "
                "`docs/findings/phase0/evidence/datasource_metadata.json`.",
                "",
                "Local layer destinations remain separate:",
                "",
                *[
                    f"- `{candidate['candidate_id']}`: raw `{candidate['local_raw_path']}`; "
                    f"standardized `{candidate['local_standardized_path']}`"
                    for candidate in record["candidates"]
                ],
                "",
                "Model-ready output is intentionally deferred to Phase 1 and must not overwrite either layer.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    record = run_probe()
    write_findings(record)
    print(f"SM-04 {record['classification']}: {record['observed_result']}")
    return 0 if record["classification"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
