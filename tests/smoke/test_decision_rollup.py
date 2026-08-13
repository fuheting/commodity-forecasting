from commodity_forecasting.phase0.evidence import validate_evidence_record
from commodity_forecasting.phase0.smoke_decision_rollup import SOURCE_FILES, run_probe


def test_sm06_rollup_cross_links_all_decisions_and_preserves_unknowns() -> None:
    record = run_probe()
    validate_evidence_record(record)

    assert record["classification"] == "pass"
    assert set(record["conclusions"]) == set(SOURCE_FILES)
    assert set(record["source_evidence"]) == set(SOURCE_FILES)
    assert record["unknowns"]
    assert record["limitations"]
    assert record["covariate_adapter_status"] == "adapter_gap_proven"
    assert record["primary_datasource"] == "world_bank_pink_sheet_monthly_arabica"
    assert record["fallback_datasource"] == "not_applicable_for_static_monthly_poc"
    assert record["recommended_primary_candidate"] == "world_bank_pink_sheet_monthly_arabica"
    assert record["recommended_fallback_candidate"] == "deferred_api_or_ice_selection"
    assert "monthly Arabica" in record["conclusions"]["catalog"]
