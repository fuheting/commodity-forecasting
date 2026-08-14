import os

from commodity_forecasting.phase0.evidence import validate_evidence_record
from commodity_forecasting.phase0.smoke_covariates import run_probe, write_covariate_findings


def test_sm01_covariate_support_probe_records_truthful_environment_result() -> None:
    record = run_probe()
    validate_evidence_record(record)

    if os.environ.get("PHASE0_WRITE_EVIDENCE") == "1":
        write_covariate_findings(record)

    assert record["test_id"] == "SM-01"
    assert record["data_origin"] == "synthetic"
    assert record["gate_result"] in {
        "native_path_selected",
        "adapter_gap_proven",
        "model_unsupported",
        "blocked_or_unknown",
    }
    assert record["classification"] in {"pass", "fail", "blocked", "unsupported"}
