import pytest

from tools.capability_probes.evidence import validate_evidence_record
from tools.capability_probes.probabilistic_adapters import run_probe


pytestmark = pytest.mark.live


def test_sm02_probabilistic_adapter_probe_records_truthful_environment_result() -> None:
    record = run_probe()
    validate_evidence_record(record)

    assert record["test_id"] == "SM-02"
    assert record["data_origin"] == "synthetic"
    assert record["gate_result"] in {
        "compatible_adapter_selected",
        "adapter_gap_proven",
        "model_unsupported",
        "blocked_or_unknown",
    }
    assert record["classification"] in {"pass", "fail", "blocked", "unsupported"}

    if record["classification"] == "pass":
        assert record["probabilistic_output_kind"] in {"intervals", "quantiles", "both"}
        assert any("-q-" in column for column in record["output_columns"])
        assert any("-lo-" in column for column in record["output_columns"])
        assert any("-hi-" in column for column in record["output_columns"])
