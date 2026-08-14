from commodity_forecasting.phase0.evidence import validate_evidence_record
from commodity_forecasting.phase0.smoke_datasources import PINK_SHEET_DATASET_ID, run_probe


def test_sm04_datasource_metadata_probe_selects_static_workbook() -> None:
    record = run_probe()
    validate_evidence_record(record)

    assert record["classification"] == "pass"
    assert record["primary_datasource"] == PINK_SHEET_DATASET_ID
    assert record["fallback_datasource"] == "not_applicable_for_static_monthly_poc"
    assert record["recommended_primary_candidate"] == PINK_SHEET_DATASET_ID
    assert record["recommended_fallback_candidate"] == "deferred_api_or_ice_selection"
    assert record["forecast_contract"] == {
        "target": "Coffee, Arabica",
        "frequency": "monthly",
        "historical_context": "60 months",
        "forecast_horizon": "3 months",
        "unit": "$/kg",
        "covariate_availability": "past_only",
    }
    assert {
        "static_monthly_workbook",
        "provider_continuous_front_month",
        "raw_contracts_for_later_construction",
        "unknown",
    }.issubset({candidate["continuous_series_kind"] for candidate in record["candidates"]})
    assert len(record["candidates"]) == 13
    supporting = [
        candidate for candidate in record["candidates"] if candidate["continuous_series_kind"] == "unsupported"
    ]
    assert len(supporting) == 9
    assert sum(candidate["programmatic_read"].get("outcome") == "success" for candidate in supporting) == 5
    assert all(candidate["programmatic_read"].get("settlement_field_proven") is False for candidate in supporting)
    assert all("roll_methodology" in candidate for candidate in record["candidates"])
    assert all(candidate["local_raw_path"] != candidate["local_standardized_path"] for candidate in record["candidates"])
    assert "raw market payload" in record["data_origin"]
    assert all("programmatic_read" in candidate for candidate in record["candidates"])


def test_sm04_requires_proven_static_workbook_identity() -> None:
    record = run_probe(
        read_observations={
            PINK_SHEET_DATASET_ID: {
                "outcome": "success",
                "row_count": 799,
                "observed_history_start": "1960M01",
                "observed_history_end": "2026M07",
                "series_identity_proven": False,
            }
        }
    )

    assert record["classification"] == "blocked"
    assert record["primary_datasource"] == "not_selected"


def test_sm04_does_not_promote_futures_success_to_active_monthly_selection() -> None:
    record = run_probe(
        read_observations={
            PINK_SHEET_DATASET_ID: {
                "outcome": "success",
                "row_count": 799,
                "observed_history_start": "1960M01",
                "observed_history_end": "2026M07",
                "series_identity_proven": False,
            },
            "barchart_cmdtyview_kc_star_0": {
                "outcome": "success",
                "row_count": 5,
                "observed_history_start": "1980-01-01",
                "observed_history_end": "2026-08-12",
                "settlement_field_proven": False,
                "series_identity_proven": True,
            }
        }
    )

    assert record["classification"] == "blocked"
    assert record["primary_datasource"] == "not_selected"
