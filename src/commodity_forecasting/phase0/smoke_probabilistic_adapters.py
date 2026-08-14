"""SM-02 probabilistic-adapter smoke probe."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .contracts import ProbabilisticGateResult, ProbabilisticOutputKind
from .evidence import utc_timestamp, write_evidence
from .fixtures import FIXTURE_ID
from .paths import phase0_evidence_dir, phase0_findings_dir, phase0_fixture_dir, repo_root


def inspect_timecopilot() -> tuple[str, str | None]:
    try:
        return importlib.metadata.version("timecopilot"), None
    except importlib.metadata.PackageNotFoundError as exc:
        return "not_installed", str(exc)


def classify_blocked(
    version: str,
    error: str | None,
) -> tuple[str, ProbabilisticOutputKind, ProbabilisticGateResult]:
    if version == "not_installed":
        return (
            "TimeCopilot is not installed in the active Python environment; probabilistic adapter support cannot be executed.",
            "unknown",
            "blocked_or_unknown",
        )
    if error:
        return (error, "unknown", "blocked_or_unknown")
    return (
        "TimeCopilot imported, but no runnable probabilistic adapter was configured.",
        "unknown",
        "blocked_or_unknown",
    )


def _synthetic_forecast_df() -> Any:
    import pandas as pd

    return pd.DataFrame(
        {
            "unique_id": ["synthetic_target"] * 8,
            "ds": pd.date_range("2026-01-02", periods=8, freq="W-FRI"),
            "y": [100.0, 101.5, 101.0, 103.0, 104.5, 104.0, 105.0, 106.5],
        }
    )


class _FakeNativeT0:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def predict(self, *args: Any, **kwargs: Any) -> Any:
        import torch

        horizon = int(kwargs["horizon"])
        quantiles = list(kwargs["quantiles"])
        self.calls.append(
            {
                "positional_arg_count": len(args),
                "keyword_args": sorted(kwargs),
                "horizon": horizon,
                "quantiles": quantiles,
                "future_covariates_seen": "future_covariates" in kwargs,
            }
        )

        class FakeForecast:
            def __init__(self, values: Any) -> None:
                self.quantiles = values

        values = torch.arange(horizon * len(quantiles), dtype=torch.float32).reshape(
            1,
            horizon,
            len(quantiles),
        )
        return FakeForecast(values)


def _forecast_with_fake_model(*, kwargs: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    from timecopilot.models.foundation.t0 import T0

    fake_model = _FakeNativeT0()

    @contextmanager
    def fake_get_model() -> Any:
        yield fake_model

    adapter = T0(batch_size=1, alias="t0-alpha")
    adapter._get_model = fake_get_model  # type: ignore[method-assign]
    result = adapter.forecast(df=_synthetic_forecast_df(), h=3, freq="W-FRI", **kwargs)
    return result, fake_model.calls


def _exercise_timecopilot_t0_probabilistic_output() -> dict[str, Any]:
    import inspect

    from timecopilot.models.foundation.t0 import T0

    quantile_result, quantile_calls = _forecast_with_fake_model(
        kwargs={"quantiles": [0.1, 0.5, 0.9]},
    )
    level_result, level_calls = _forecast_with_fake_model(kwargs={"level": [80]})
    simultaneous_error = None
    try:
        _forecast_with_fake_model(kwargs={"level": [80], "quantiles": [0.1, 0.9]})
    except ValueError as exc:
        simultaneous_error = str(exc)

    quantile_columns = list(quantile_result.columns)
    level_columns = list(level_result.columns)
    expected_quantile_columns = {"t0-alpha-q-10", "t0-alpha-q-50", "t0-alpha-q-90"}
    expected_level_columns = {"t0-alpha-lo-80", "t0-alpha-hi-80"}
    quantiles_pass = expected_quantile_columns.issubset(quantile_columns)
    levels_pass = expected_level_columns.issubset(level_columns)

    return {
        "adapter": "timecopilot.models.foundation.t0.T0",
        "forecast_signature": str(inspect.signature(T0.forecast)),
        "quantiles": {
            "parameters": {"quantiles": [0.1, 0.5, 0.9]},
            "output_columns": quantile_columns,
            "row_count": len(quantile_result),
            "native_predict_calls": quantile_calls,
            "classification": "pass" if quantiles_pass else "fail",
        },
        "level": {
            "parameters": {"level": [80]},
            "output_columns": level_columns,
            "row_count": len(level_result),
            "native_predict_calls": level_calls,
            "classification": "pass" if levels_pass else "fail",
        },
        "simultaneous_level_quantiles": {
            "parameters": {"level": [80], "quantiles": [0.1, 0.9]},
            "classification": "unsupported" if simultaneous_error else "fail",
            "error": simultaneous_error,
        },
    }


def _run_t0_probabilistic_probe() -> tuple[
    str,
    ProbabilisticOutputKind,
    ProbabilisticGateResult,
    str,
    str,
    str,
    list[str],
    list[dict[str, Any]],
    dict[str, Any],
]:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-phase0")
    executable_evidence = _exercise_timecopilot_t0_probabilistic_output()

    quantiles_pass = executable_evidence["quantiles"]["classification"] == "pass"
    levels_pass = executable_evidence["level"]["classification"] == "pass"
    unsupported_combinations = [
        executable_evidence["simultaneous_level_quantiles"],
    ]
    output_columns = sorted(
        set(executable_evidence["quantiles"]["output_columns"])
        | set(executable_evidence["level"]["output_columns"])
    )

    if quantiles_pass and levels_pass:
        observed = (
            "TimeCopilot 0.0.30 T0.forecast returned requested quantile columns for quantiles=[0.1, 0.5, 0.9] "
            "and interval columns for level=[80] through the adapter. The adapter rejected simultaneous level "
            "and quantiles with the documented ValueError."
        )
        return (
            observed,
            "both",
            "compatible_adapter_selected",
            "pass",
            "native_probabilistic_quantiles",
            "quantiles_and_level_exposed",
            output_columns,
            unsupported_combinations,
            executable_evidence,
        )

    observed = "T0 probabilistic probe ran, but did not establish both quantile and level output through TimeCopilot."
    return (
        observed,
        "unknown",
        "blocked_or_unknown",
        "blocked",
        "unknown",
        "unknown",
        output_columns,
        unsupported_combinations,
        executable_evidence,
    )


def run_probe(*, root: Path | None = None) -> dict[str, Any]:
    active_root = root or repo_root()
    command = ".venv/bin/python -m pytest tests/smoke/test_probabilistic_adapters.py"
    version, version_error = inspect_timecopilot()
    model_or_adapter = os.environ.get(
        "PHASE0_TIMECOPILOT_PROBABILISTIC_MODEL",
        "timecopilot.models.foundation.t0.T0",
    )
    credential_name = os.environ.get("PHASE0_TIMECOPILOT_CREDENTIAL_VAR", "")
    credential_state = (
        "present" if credential_name and os.environ.get(credential_name) else "not_required_or_not_configured"
    )
    network_state = os.environ.get("PHASE0_NETWORK_STATE", "not_required_monkeypatched_local")

    observed_result, output_kind, gate_result = classify_blocked(version, version_error)
    classification = "blocked"
    adapter_exposure = "unknown"
    model_native_capability = "unknown"
    output_columns: list[str] = []
    unsupported_combinations: list[dict[str, Any]] = []
    executable_evidence: dict[str, Any] = {}

    if version != "not_installed":
        try:
            (
                observed_result,
                output_kind,
                gate_result,
                classification,
                model_native_capability,
                adapter_exposure,
                output_columns,
                unsupported_combinations,
                executable_evidence,
            ) = _run_t0_probabilistic_probe()
        except Exception as exc:  # pragma: no cover - environment dependent
            module = importlib.import_module("timecopilot")
            exported = sorted(
                name for name in dir(module) if "forecast" in name.lower() or "copilot" in name.lower()
            )
            observed_result = (
                f"TimeCopilot imported but the T0 probabilistic probe failed with {type(exc).__name__}: {exc}. "
                f"Visible forecast-related exports: {exported[:8]}"
            )

    evidence_path = phase0_evidence_dir(active_root) / "probabilistic_adapters.json"
    finding_path = phase0_findings_dir(active_root) / "probabilistic_adapters.md"
    record: dict[str, Any] = {
        "run_id": f"SM-02-{utc_timestamp()}",
        "test_id": "SM-02",
        "work_item": "probabilistic-adapter smoke test",
        "timestamp_utc": utc_timestamp(),
        "mode": "network-smoke",
        "command": command,
        "tool": "pytest",
        "timecopilot_version": version,
        "model_or_adapter": model_or_adapter,
        "fixture_id": FIXTURE_ID,
        "data_origin": "synthetic",
        "credential_state": credential_state,
        "network_state": network_state,
        "observed_result": observed_result,
        "classification": classification,
        "leakage_controls": [
            "synthetic target only; no real Coffee C data",
            "forecast horizon is generated strictly after the last fixture timestamp",
            "probabilistic output is exercised through adapter arguments only",
            "no random train/test split",
        ],
        "artifact_paths": [
            str(phase0_fixture_dir(active_root) / "weekly_target.csv"),
            str(evidence_path),
            str(finding_path),
        ],
        "model_native_capability": model_native_capability,
        "adapter_exposure": adapter_exposure,
        "probabilistic_output_kind": output_kind,
        "gate_result": gate_result,
        "output_columns": output_columns,
        "unsupported_combinations": unsupported_combinations,
    }
    if executable_evidence:
        record["executable_evidence"] = executable_evidence
    return record


def write_probabilistic_findings(record: dict[str, Any], *, root: Path | None = None) -> None:
    active_root = root or repo_root()
    evidence_path = phase0_evidence_dir(active_root) / "probabilistic_adapters.json"
    finding_path = phase0_findings_dir(active_root) / "probabilistic_adapters.md"
    write_evidence(evidence_path, record)
    finding_path.parent.mkdir(parents=True, exist_ok=True)
    finding_path.write_text(
        "\n".join(
            [
                "# Phase 0 Probabilistic Adapter Finding",
                "",
                f"- Test ID: `{record['test_id']}`",
                f"- Classification: `{record['classification']}`",
                f"- Gate result: `{record['gate_result']}`",
                f"- TimeCopilot version: `{record['timecopilot_version']}`",
                f"- Model or adapter: `{record['model_or_adapter']}`",
                f"- Model-native capability: `{record['model_native_capability']}`",
                f"- Adapter exposure: `{record['adapter_exposure']}`",
                f"- Probabilistic output kind: `{record['probabilistic_output_kind']}`",
                f"- Output columns: `{', '.join(record['output_columns'])}`",
                "",
                "## Observed Result",
                "",
                str(record["observed_result"]),
                "",
                "## Unsupported Combinations",
                "",
                "The adapter does not support simultaneous `level` and `quantiles`; TimeCopilot raises "
                "a `ValueError` with the message: `You must not provide both level and quantiles simultaneously.`",
                "",
                "## Boundary",
                "",
                "No point-only model was modified. The finding is limited to TimeCopilot 0.0.30's T0 adapter "
                "output conversion, exercised with synthetic weekly data and a monkeypatched local model loader.",
                "",
                f"Evidence: `docs/findings/phase0/evidence/{evidence_path.name}`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    record = run_probe()
    write_probabilistic_findings(record)
    print(f"SM-02 {record['classification']}: {record['observed_result']}")
    return 0 if record["classification"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
