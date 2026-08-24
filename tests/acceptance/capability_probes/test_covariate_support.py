import pytest

from tools.capability_probes.covariate_support import run_probe
from tools.capability_probes.evidence import validate_evidence_record


pytestmark = pytest.mark.live


def test_sm01_covariate_support_probe_records_truthful_environment_result() -> None:
    record = run_probe()
    validate_evidence_record(record)

    assert record["test_id"] == "SM-01"
    assert record["data_origin"] == "synthetic"
    assert record["gate_result"] in {
        "native_path_selected",
        "adapter_gap_proven",
        "model_unsupported",
        "blocked_or_unknown",
    }
    assert record["classification"] in {"pass", "fail", "blocked", "unsupported"}
