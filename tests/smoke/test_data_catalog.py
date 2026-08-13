from commodity_forecasting.phase0.contracts import CATALOG_REQUIRED_FIELDS
from commodity_forecasting.phase0.evidence import validate_evidence_record
from commodity_forecasting.phase0.smoke_data_catalog import RAW_PAYLOAD_KEYS, run_probe, validate_catalog


def test_sm05_catalog_uses_verified_metadata_and_separate_layers() -> None:
    record, entries = run_probe()
    validate_evidence_record(record)
    validate_catalog(entries)

    assert record["classification"] == "pass"
    assert record["entry_count"] == 13
    assert record["selected_dataset_id"] == "world_bank_pink_sheet_monthly_arabica"
    for entry in entries:
        assert set(CATALOG_REQUIRED_FIELDS).issubset(entry)
        assert not RAW_PAYLOAD_KEYS.intersection(entry)
        assert len({entry["raw_path"], entry["standardized_path"], entry["model_ready_path"]}) == 3
        assert "roll_methodology" in entry
        assert entry["status"] in {
            "selected_static_source",
            "future_work_deferred",
            "supporting_read_proven",
            "supporting_access_unproven",
        }
    assert sum(entry["category"] == "target" for entry in entries) == 1
    assert sum(entry["category"] == "supporting_covariate_candidate" for entry in entries) == 9
