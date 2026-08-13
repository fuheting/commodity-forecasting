from commodity_forecasting.phase0.evidence import validate_evidence_record
from commodity_forecasting.phase0.smoke_roadmap_exit import run_audit


def test_sm07_roadmap_only_closes_evidenced_phase0_work() -> None:
    record = run_audit()
    validate_evidence_record(record)
    assert record["classification"] == "pass"
    assert record["phase0_task_count"] == 8
    assert record["checks"]["all_phase0_tasks_checked"]
    assert record["checks"]["all_required_records_pass"]
    assert record["checks"]["monthly_contract_recorded"]
