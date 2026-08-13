import os

from commodity_forecasting.phase0.evidence import validate_evidence_record
from commodity_forecasting.phase0.smoke_natural_language import (
    EXPECTED_TOOLS,
    run_probe,
    write_findings,
)


def test_sm03_natural_language_agent_executes_tools_and_answers_query() -> None:
    record = run_probe()
    validate_evidence_record(record)
    if os.environ.get("PHASE0_WRITE_EVIDENCE") == "1":
        write_findings(record)

    assert record["classification"] == "pass"
    assert record["tool_calls"] == EXPECTED_TOOLS
    assert record["forecast_rows"] == 12
    assert record["forecast_analysis"].strip()
    assert "12-week" in record["user_query_response"]
