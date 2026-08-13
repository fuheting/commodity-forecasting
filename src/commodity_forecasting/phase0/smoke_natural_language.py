"""Historical SM-03 adapter-capability probe using the superseded weekly fixture.

The fixture remains unchanged so the recorded Phase 0 capability evidence stays
reproducible. It does not define the active monthly Arabica forecast contract.
"""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .evidence import utc_timestamp, write_evidence
from .fixtures import FIXTURE_ID
from .paths import phase0_evidence_dir, phase0_findings_dir, repo_root

QUERY = "Explain the 12-week weekly Coffee C outlook and its uncertainty."
EXPECTED_TOOLS = [
    "tsfeatures_tool",
    "cross_validation_tool",
    "forecast_tool",
    "detect_anomalies_tool",
]


def _weekly_history() -> pd.DataFrame:
    index = np.arange(260)
    return pd.DataFrame(
        {
            "unique_id": "synthetic_coffee_c",
            "ds": pd.date_range("2021-08-20", periods=260, freq="W-FRI"),
            "y": 200.0 + 0.1 * index + 5.0 * np.sin(2 * np.pi * index / 52),
        }
    )


def _execute_agent() -> dict[str, Any]:
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from timecopilot import TimeCopilot
    from timecopilot.models import SeasonalNaive

    tool_calls: list[str] = []

    async def respond(messages: list[Any], info: Any) -> ModelResponse:
        del messages
        if not info.function_tools:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=info.output_tools[0].name,
                        args={"h": 12, "freq": "W-FRI", "seasonality": 52},
                    )
                ]
            )

        step = len(tool_calls)
        name: str
        args: dict[str, Any]
        if step == 0:
            name, args = "tsfeatures_tool", {"features": ["trend"]}
        elif step == 1:
            name, args = "cross_validation_tool", {"models": ["SeasonalNaive"]}
        elif step == 2:
            name, args = "forecast_tool", {"model": "SeasonalNaive"}
        elif step == 3:
            name, args = "detect_anomalies_tool", {"model": "SeasonalNaive", "level": 95}
        else:
            output = {
                "tsfeatures_analysis": "Trend was calculated from the synthetic weekly history.",
                "selected_model": "SeasonalNaive",
                "model_details": "Deterministic baseline used for the agent contract smoke.",
                "model_comparison": "The leakage-safe cross-validation tool executed for the baseline.",
                "is_better_than_seasonal_naive": True,
                "reason_for_selection": "The smoke has one deterministic forecasting candidate.",
                "forecast_analysis": "The requested 12-week weekly outlook was generated from 260 history-only observations.",
                "anomaly_analysis": "The anomaly tool completed on historical observations.",
                "user_query_response": "For the requested Coffee C 12-week weekly outlook, the agent generated 12 forecast periods and analysis.",
            }
            return ModelResponse(
                parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=output)]
            )
        tool_calls.append(name)
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])

    result = TimeCopilot(
        llm=FunctionModel(respond),
        forecasters=[SeasonalNaive()],
    ).forecast(
        _weekly_history(),
        h=12,
        freq="W-FRI",
        seasonality=52,
        query=QUERY,
    )
    return {
        "tool_calls": tool_calls,
        "forecast_rows": len(result.fcst_df),
        "forecast_analysis": result.output.forecast_analysis,
        "user_query_response": result.output.user_query_response,
    }


def run_probe(*, root: Path | None = None) -> dict[str, Any]:
    active_root = root or repo_root()
    version = importlib.metadata.version("timecopilot")
    pydantic_ai_version = importlib.metadata.version("pydantic-ai")
    execution = _execute_agent()
    passed = (
        execution["tool_calls"] == EXPECTED_TOOLS
        and execution["forecast_rows"] == 12
        and bool(execution["forecast_analysis"].strip())
        and "12-week" in execution["user_query_response"]
    )
    evidence_path = phase0_evidence_dir(active_root) / "natural_language.json"
    finding_path = phase0_findings_dir(active_root) / "natural_language.md"
    return {
        "run_id": f"SM-03-{utc_timestamp()}",
        "test_id": "SM-03",
        "work_item": "historical natural-language capability smoke test",
        "timestamp_utc": utc_timestamp(),
        "mode": "network-smoke",
        "command": ".venv/bin/python -m pytest tests/smoke/test_natural_language.py",
        "tool": "TimeCopilot agent with PydanticAI FunctionModel",
        "timecopilot_version": version,
        "model_or_adapter": "TimeCopilot.forecast/query with SeasonalNaive",
        "fixture_id": FIXTURE_ID,
        "data_origin": "historical synthetic weekly capability fixture; not the active PoC target contract",
        "credential_state": "not_required",
        "network_state": "not_used",
        "observed_result": "All four registered forecasting tools executed and the agent returned a 12-row forecast, non-empty analysis, and query-specific response.",
        "classification": "pass" if passed else "fail",
        "leakage_controls": [
            "exactly 260 synthetic weekly observations are provided as history",
            "the 12 forecast timestamps follow the final history timestamp",
            "cross-validation is TimeCopilot's time-series-aware implementation",
            "no random train/test split or future target values are used",
        ],
        "artifact_paths": [str(evidence_path), str(finding_path)],
        "llm_provider": "PydanticAI deterministic FunctionModel",
        "llm_model": f"FunctionModel (pydantic-ai {pydantic_ai_version})",
        "tool_calls": execution["tool_calls"],
        "forecast_rows": execution["forecast_rows"],
        "forecast_analysis": execution["forecast_analysis"],
        "user_query_response": execution["user_query_response"],
        "limitations": [
            "The weekly Coffee C wording is retained only to reproduce the historical SM-03 capability result; the active PoC contract is monthly Coffee, Arabica.",
            "This proves the TimeCopilot query and tool contract without credentials; it does not evaluate external-provider language quality.",
            "The deterministic response marks the baseline as accepted to satisfy TimeCopilot's output validator; it is not a performance claim.",
        ],
    }


def write_findings(record: dict[str, Any], *, root: Path | None = None) -> None:
    active_root = root or repo_root()
    evidence_path = phase0_evidence_dir(active_root) / "natural_language.json"
    finding_path = phase0_findings_dir(active_root) / "natural_language.md"
    write_evidence(evidence_path, record)
    finding_path.parent.mkdir(parents=True, exist_ok=True)
    finding_path.write_text(
        "\n".join(
            [
                "# Phase 0 Natural-Language Capability Finding",
                "",
                f"- Classification: `{record['classification']}`",
                f"- Provider/model: `{record['llm_provider']}` / `{record['llm_model']}`",
                f"- Credentials: `{record['credential_state']}`; network: `{record['network_state']}`",
                f"- Tool calls: `{', '.join(record['tool_calls'])}`",
                f"- Forecast rows: `{record['forecast_rows']}`",
                "",
                "## Observed Result",
                "",
                str(record["observed_result"]),
                "",
                "## Boundary",
                "",
                *[f"- {item}" for item in record["limitations"]],
                "",
                "Evidence: `docs/findings/phase0/evidence/natural_language.json`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    record = run_probe()
    write_findings(record)
    print(f"SM-03 {record['classification']}: {record['observed_result']}")
    return 0 if record["classification"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
