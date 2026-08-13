"""SM-01 covariate-support smoke probe."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .contracts import CovariateCapability, CovariateGateResult
from .evidence import utc_timestamp, write_evidence
from .fixtures import FIXTURE_ID
from .paths import phase0_evidence_dir, phase0_findings_dir, phase0_fixture_dir, repo_root


def inspect_timecopilot() -> tuple[str, str | None]:
    try:
        return importlib.metadata.version("timecopilot"), None
    except importlib.metadata.PackageNotFoundError as exc:
        return "not_installed", str(exc)


def classify_blocked(version: str, error: str | None) -> tuple[str, CovariateCapability, CovariateGateResult]:
    if version == "not_installed":
        return (
            "TimeCopilot is not installed in the active Python environment; covariate support cannot be executed.",
            "unknown",
            "blocked_or_unknown",
        )
    if error:
        return (error, "unknown", "blocked_or_unknown")
    return ("TimeCopilot imported, but no runnable covariate-capable adapter was configured.", "unknown", "blocked_or_unknown")


def _exercise_native_t0_future_covariates() -> dict[str, Any]:
    import inspect

    import numpy as np
    from t0 import T0Forecaster

    signature = str(inspect.signature(T0Forecaster.predict))
    model = T0Forecaster(
        embed_dim=4,
        num_layers=1,
        num_heads=1,
        mlp_hidden_dim=8,
        patch_size=2,
        group_every_n=1,
        dropout=0.0,
        quantile_levels=(0.1, 0.5, 0.9),
    )
    forecast = model.predict(
        np.array([[1.0, 2.0, 3.0, 4.0]], dtype="float32"),
        horizon=2,
        quantiles=(0.1, 0.5),
        future_covariates=np.ones((1, 1, 6), dtype="float32"),
    )
    return {
        "package": "tfc-t0",
        "import_name": "t0",
        "predict_signature": signature,
        "future_covariates_parameter": "future_covariates" in signature,
        "direct_predict_with_future_covariates": "pass",
        "direct_predict_output_shape": list(forecast.quantiles.shape),
        "direct_predict_quantile_levels": list(forecast.quantile_levels),
    }


def _exercise_timecopilot_t0_adapter_omission() -> dict[str, Any]:
    import inspect

    import pandas as pd
    import torch
    from timecopilot.models.foundation.t0 import T0

    class FakeNativeT0:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def predict(self, *args: Any, **kwargs: Any) -> Any:
            self.calls.append(
                {
                    "positional_arg_count": len(args),
                    "keyword_args": sorted(kwargs),
                    "future_covariates_seen": "future_covariates" in kwargs,
                }
            )

            class FakeForecast:
                quantiles = torch.zeros((1, int(kwargs["horizon"]), len(kwargs["quantiles"])))

            return FakeForecast()

    fake_model = FakeNativeT0()

    @contextmanager
    def fake_get_model() -> Any:
        yield fake_model

    adapter = T0(batch_size=1, alias="t0-alpha")
    adapter._get_model = fake_get_model  # type: ignore[method-assign]
    df = pd.DataFrame(
        {
            "unique_id": ["synthetic_target"] * 5,
            "ds": pd.date_range("2026-01-02", periods=5, freq="W-FRI"),
            "y": [100.0, 101.5, 101.0, 103.0, 104.5],
            "past_signal": [10.0, 10.5, 11.0, 11.5, 12.0],
            "known_future_signal": [1, 0, 1, 0, 1],
        }
    )
    result = adapter.forecast(df=df, h=2, freq="W-FRI", quantiles=[0.1, 0.5])
    forecast_signature = str(inspect.signature(T0.forecast))
    return {
        "adapter": "timecopilot.models.foundation.t0.T0",
        "forecast_signature": forecast_signature,
        "forecast_accepts_covariate_kwargs": any(
            token in forecast_signature for token in ("future_covariates", "past_covariates", "X_df")
        ),
        "input_covariate_columns": ["past_signal", "known_future_signal"],
        "native_predict_calls": fake_model.calls,
        "adapter_omitted_future_covariates": all(
            not call["future_covariates_seen"] for call in fake_model.calls
        ),
        "forecast_output_columns": list(result.columns),
    }


def _run_t0_gap_probe() -> tuple[str, CovariateCapability, CovariateGateResult, str, str, str, dict[str, Any]]:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-phase0")
    native = _exercise_native_t0_future_covariates()
    adapter = _exercise_timecopilot_t0_adapter_omission()

    native_supported = bool(native["future_covariates_parameter"]) and native["direct_predict_with_future_covariates"] == "pass"
    adapter_omits = bool(adapter["adapter_omitted_future_covariates"]) and not adapter["forecast_accepts_covariate_kwargs"]
    if native_supported and adapter_omits:
        observed = (
            "Native tfc-t0 T0Forecaster.predict accepted and executed future_covariates on a tiny local model, "
            "while the TimeCopilot T0.forecast adapter accepted only the univariate forecast contract and a "
            "monkeypatched adapter run with covariate columns passed no future_covariates keyword to native predict."
        )
        return (
            observed,
            "known_future",
            "adapter_gap_proven",
            "pass",
            "known_future_future_covariates_executed",
            "univariate_only_adapter_omits_covariates",
            {"native_t0": native, "timecopilot_adapter": adapter},
        )

    observed = (
        "T0 probe ran, but did not establish both native future-covariate support and TimeCopilot adapter omission."
    )
    return (
        observed,
        "unknown",
        "blocked_or_unknown",
        "blocked",
        "unknown",
        "unknown",
        {"native_t0": native, "timecopilot_adapter": adapter},
    )


def run_probe(*, root: Path | None = None) -> dict[str, Any]:
    active_root = root or repo_root()
    command = ".venv/bin/python -m pytest tests/smoke/test_covariate_support.py"
    version, version_error = inspect_timecopilot()
    model_or_adapter = os.environ.get("PHASE0_TIMECOPILOT_COVARIATE_MODEL", "timecopilot.models.foundation.t0.T0")
    credential_name = os.environ.get("PHASE0_TIMECOPILOT_CREDENTIAL_VAR", "")
    credential_state = "present" if credential_name and os.environ.get(credential_name) else "not_required_or_not_configured"
    network_state = os.environ.get("PHASE0_NETWORK_STATE", "not_required_monkeypatched_local")

    observed_result, capability, gate_result = classify_blocked(version, version_error)
    classification = "blocked"
    adapter_exposure = "unknown"
    model_native_capability = "unknown"
    executable_evidence: dict[str, Any] = {}

    if version != "not_installed":
        try:
            (
                observed_result,
                capability,
                gate_result,
                classification,
                model_native_capability,
                adapter_exposure,
                executable_evidence,
            ) = _run_t0_gap_probe()
        except Exception as exc:  # pragma: no cover - environment dependent
            module = importlib.import_module("timecopilot")
            exported = sorted(name for name in dir(module) if "forecast" in name.lower() or "copilot" in name.lower())
            observed_result = (
                f"TimeCopilot imported but the T0 covariate gap probe failed with {type(exc).__name__}: {exc}. "
                f"Visible forecast-related exports: {exported[:8]}"
            )

    record: dict[str, Any] = {
        "run_id": f"SM-01-{utc_timestamp()}",
        "test_id": "SM-01",
        "work_item": "covariate-support smoke test",
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
            "past-only covariates are sliced at the forecast origin",
            "known-future covariates are marked known_at_origin",
            "no random train/test split",
        ],
        "artifact_paths": [
            str(phase0_fixture_dir(active_root) / "weekly_target.csv"),
            str(phase0_fixture_dir(active_root) / "covariates.csv"),
            str(phase0_evidence_dir(active_root) / "covariate_support.json"),
            str(phase0_findings_dir(active_root) / "covariate_support.md"),
        ],
        "model_native_capability": model_native_capability,
        "adapter_exposure": adapter_exposure,
        "covariate_path_classification": capability,
        "gate_result": gate_result,
    }
    if executable_evidence:
        record["executable_evidence"] = executable_evidence
    return record


def write_covariate_findings(record: dict[str, Any], *, root: Path | None = None) -> None:
    active_root = root or repo_root()
    evidence_path = phase0_evidence_dir(active_root) / "covariate_support.json"
    finding_path = phase0_findings_dir(active_root) / "covariate_support.md"
    write_evidence(evidence_path, record)
    finding_path.parent.mkdir(parents=True, exist_ok=True)
    finding_path.write_text(
        "\n".join(
            [
                "# Phase 0 Covariate Support Finding",
                "",
                f"- Test ID: `{record['test_id']}`",
                f"- Classification: `{record['classification']}`",
                f"- Gate result: `{record['gate_result']}`",
                f"- TimeCopilot version: `{record['timecopilot_version']}`",
                f"- Model or adapter: `{record['model_or_adapter']}`",
                f"- Model-native capability: `{record['model_native_capability']}`",
                f"- Adapter exposure: `{record['adapter_exposure']}`",
                f"- Covariate path classification: `{record['covariate_path_classification']}`",
                "",
                "## Observed Result",
                "",
                str(record["observed_result"]),
                "",
                "## Boundary",
                "",
                "No unsupported model was modified and no custom covariate adapter was added. "
                "The finding is limited to the installed T0 native API and the current TimeCopilot T0 "
                "adapter behavior exercised by the smoke test.",
                "",
                f"Evidence: `docs/findings/phase0/evidence/{evidence_path.name}`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    record = run_probe()
    write_covariate_findings(record)
    print(f"SM-01 {record['classification']}: {record['observed_result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
