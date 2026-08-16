from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from commodity_forecasting.phase1 import runtime_compatibility as runtime
from commodity_forecasting.phase1 import selection
from commodity_forecasting.phase1.target_pipeline import TargetRow

REPO_ROOT = Path(__file__).resolve().parents[2]


def _window() -> runtime.RuntimeWindow:
    rows = []
    year, month = 2021, 8
    for index in range(60):
        rows.append(TargetRow("world_bank_pink_sheet_monthly_arabica", date(year, month, 1), str(100 + index)))
        month += 1
        if month == 13:
            year += 1
            month = 1
    frozen = tuple(rows)
    return runtime.RuntimeWindow(
        rows=frozen,
        digest=runtime._window_digest(frozen),
        history_start=runtime.EXPECTED_HISTORY_START,
        history_end=runtime.EXPECTED_HISTORY_END,
        expected_forecast_timestamps=runtime.EXPECTED_FORECAST_TIMESTAMPS,
    )


def _stage(
    variant_id: str,
    name: str,
    window: runtime.RuntimeWindow,
    *,
    outcome: str,
    peak: int = 100,
) -> dict[str, Any]:
    entry = runtime.not_run_stage(variant_id, name, window, "prerequisite did not succeed")
    entry.update(
        {
            "started_at_utc": "2026-08-15T00:00:00Z",
            "ended_at_utc": "2026-08-15T00:00:01Z",
            "duration_seconds": 1.0,
            "outcome": outcome,
            "load_success": outcome == "success",
            "device": "cuda:0:test-gpu",
            "memory": {
                "source": "torch_cuda_max_memory_allocated",
                "unit": "bytes",
                "device_class": "cuda",
                "peak": peak,
            },
            "exception_class": None,
            "error": None if outcome == "success" else "unsupported request",
            "failure_classification": (
                "none"
                if outcome == "success"
                else "adapter_unsupported"
                if outcome == "unsupported"
                else "runtime_failed"
                if outcome == "failed"
                else "not_run_due_to_prior_failure"
            ),
        }
    )
    if not name.startswith("offline_"):
        entry["acquisition_provenance"] = "downloaded" if name == "connected_point" else "cache_hit"
    if outcome == "success":
        columns = ["unique_id", "ds", "P105"]
        if name.endswith("_interval"):
            columns.extend(["P105-lo-80", "P105-hi-80"])
        if name.endswith("_quantiles"):
            columns.extend([f"P105-q-{value}" for value in range(10, 100, 10)])
        entry.update(
            {
                "output_columns": columns,
                "output_shape": [3, len(columns)],
                "output_timestamps": list(runtime.EXPECTED_FORECAST_TIMESTAMPS),
            }
        )
    return entry


def _candidate(
    variant_id: str,
    order: int,
    window: runtime.RuntimeWindow,
    *,
    peak: int = 100,
    passing: bool = True,
) -> dict[str, Any]:
    outcomes = {
        "connected_point": "success" if passing else "failed",
        "connected_interval": "success" if passing else "unsupported",
        "connected_quantiles": "unsupported",
        "offline_point": "success" if passing else "not_run_due_to_prior_failure",
        "offline_interval": "success" if passing else "not_run_due_to_prior_failure",
        "offline_quantiles": "not_run_due_to_prior_failure",
    }
    stages = [_stage(variant_id, name, window, outcome=outcomes[name], peak=peak) for name in runtime.STAGE_NAMES]
    result = runtime.derive_candidate_summary(variant_id, order, stages)
    result["stage_history"] = stages
    return result


def _complete_record(window: runtime.RuntimeWindow, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return runtime.build_record(
        candidates,
        window,
        approval_decision_id="P1-04-test",
        approval_sha256="a" * 64,
        generated_at_utc="2026-08-15T00:00:00Z",
    )


def test_sm00_project_venv_and_exact_60x3_window() -> None:
    runtime.assert_project_venv(REPO_ROOT)
    window = runtime.load_runtime_window(REPO_ROOT)
    assert window.row_count == 60
    assert window.history_start == "2021-08-01"
    assert window.history_end == "2026-07-01"
    assert window.expected_forecast_timestamps == ("2026-08-01", "2026-09-01", "2026-10-01")


def test_sm01_approval_gate_rejects_reorder_subset_and_alias() -> None:
    assert selection.require_runtime_approval(REPO_ROOT, runtime.APPROVED_VARIANT_IDS) == runtime.APPROVED_VARIANT_IDS
    with pytest.raises(selection.CandidateNotApprovedError):
        selection.require_runtime_approval(REPO_ROOT, tuple(reversed(runtime.APPROVED_VARIANT_IDS)))
    with pytest.raises(selection.CandidateNotApprovedError):
        selection.require_runtime_approval(REPO_ROOT, runtime.APPROVED_VARIANT_IDS[:-1])
    rewritten = list(runtime.APPROVED_VARIANT_IDS)
    rewritten[-1] = "google/timesfm-2.5-200m-pytorch"
    with pytest.raises(selection.CandidateNotApprovedError):
        selection.require_runtime_approval(REPO_ROOT, rewritten)


def test_sm02_stage_history_is_total_ordered_and_summary_derived() -> None:
    window = _window()
    candidate = _candidate(runtime.APPROVED_VARIANT_IDS[0], 0, window)
    runtime.validate_candidate(candidate, window)

    missing = dict(candidate)
    missing["stage_history"] = candidate["stage_history"][:-1]
    with pytest.raises(runtime.RuntimeEvidenceError, match="six ordered"):
        runtime.validate_candidate(missing, window)

    changed = json.loads(json.dumps(candidate))
    changed["stage_history"][1]["window"]["digest"] = "0" * 64
    with pytest.raises(runtime.RuntimeEvidenceError, match="window"):
        runtime.validate_candidate(changed, window)

    mismatch = dict(candidate)
    mismatch["point_output"] = False
    with pytest.raises(runtime.RuntimeEvidenceError, match="summary"):
        runtime.validate_candidate(mismatch, window)


def test_sm03_independent_probabilistic_requests_are_frozen() -> None:
    assert runtime._request_for_stage("connected_interval") == {"level": [80]}
    assert runtime._request_for_stage("connected_quantiles") == {
        "quantiles": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    }
    assert not set(runtime._request_for_stage("connected_interval")) & set(
        runtime._request_for_stage("connected_quantiles")
    )


def test_sm04_candidate_failure_does_not_make_complete_matrix_partial() -> None:
    window = _window()
    candidates = [
        _candidate(variant_id, order, window, passing=order == 2, peak=100 + order)
        for order, variant_id in enumerate(runtime.APPROVED_VARIANT_IDS)
    ]
    record = _complete_record(window, candidates)
    assert record["matrix_completeness"] == "complete"
    assert record["task_outcome"] == "pass"
    assert record["selected_reference"] == runtime.APPROVED_VARIANT_IDS[2]
    assert [item["classification"] for item in record["candidate_records"]] == [
        "fail", "fail", "pass", "fail", "fail"
    ]


def test_sm05_cache_provenance_is_observed_not_inferred(tmp_path: Path) -> None:
    assert runtime.derive_acquisition_provenance({}, {"weights": 10}) == "downloaded"
    assert runtime.derive_acquisition_provenance({"weights": 10}, {"weights": 10}) == "cache_hit"
    assert runtime.derive_acquisition_provenance({}, {}) == "unknown"
    cuda_home = tmp_path / "cuda"
    environment = runtime._child_environment(
        Path("/tmp/p1-05-cache"), offline=True, cuda_home=cuda_home
    )
    assert environment["PYTHONPATH"] == str(REPO_ROOT / "src")
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["TRANSFORMERS_OFFLINE"] == "1"
    assert "CUDA_VISIBLE_DEVICES" not in environment
    assert environment["CUDA_HOME"] == str(cuda_home)
    assert environment["P1_05_DEVICE_POLICY"] == "gpu_required"
    assert environment["P1_05_NETWORK_POLICY"] == "offline_flags_no_proxy"
    assert not any(
        name in environment
        for name in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")
    )

    connected = runtime._child_environment(
        Path("/tmp/p1-05-cache"), offline=False, cuda_home=cuda_home
    )
    assert "ALL_PROXY" not in connected and "all_proxy" not in connected
    assert connected["P1_05_NETWORK_POLICY"] == "http_proxy_without_socks_fallback"


def test_sm06_selection_uses_common_peak_then_p1_04_order() -> None:
    window = _window()
    peaks = [500, 300, 400, 700, 600]
    candidates = [
        _candidate(variant_id, order, window, peak=peaks[order])
        for order, variant_id in enumerate(runtime.APPROVED_VARIANT_IDS)
    ]
    record = _complete_record(window, candidates)
    assert record["selected_reference"] == runtime.APPROVED_VARIANT_IDS[1]
    assert record["selection_basis"] == "smallest_verified_common_peak_then_p1_04_order"

    candidates[1]["memory_observation"] = None
    selected, basis, ranked = runtime.select_reference(candidates)
    assert selected == runtime.APPROVED_VARIANT_IDS[0]
    assert basis == "p1_04_order_no_common_footprint"
    assert ranked[0]["selection_key"] == [0, 0]


def test_sm07_point_only_candidate_is_not_contract_complete() -> None:
    window = _window()
    variant = runtime.APPROVED_VARIANT_IDS[0]
    stages = [
        _stage(
            variant,
            name,
            window,
            outcome="success" if name in {"connected_point", "offline_point"} else "unsupported",
        )
        for name in runtime.STAGE_NAMES
    ]
    candidate = runtime.derive_candidate_summary(variant, 0, stages)
    assert candidate["point_output"] is True
    assert candidate["probabilistic_output_kind"] == "none"
    assert candidate["contract_completeness"] is False


def test_sm08_publication_is_markdown_first_json_last_and_sanitized(tmp_path: Path) -> None:
    window = _window()
    candidates = [
        _candidate(variant_id, order, window, passing=order == 0)
        for order, variant_id in enumerate(runtime.APPROVED_VARIANT_IDS)
    ]
    candidates[1]["stage_history"][0]["error"] = (
        "headers={'Authorization': 'Bearer top-secret'} "
        "payload={\"api_key\": \"another-secret\"}"
    )
    candidates[1].update(runtime.derive_candidate_summary(candidates[1]["variant_id"], 1, candidates[1]["stage_history"]))
    record = _complete_record(window, candidates)
    replacements: list[str] = []

    def replace(source: Path, destination: Path) -> None:
        replacements.append(destination.relative_to(tmp_path).as_posix())
        os.replace(source, destination)

    runtime.publish_record(tmp_path, record, replace_file=replace)
    assert replacements == [runtime.FINDING_RELATIVE_PATH.as_posix(), runtime.EVIDENCE_RELATIVE_PATH.as_posix()]
    assert "top-secret" not in (tmp_path / runtime.EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8")
    assert "another-secret" not in (tmp_path / runtime.EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8")
    sanitized = runtime.sanitize_error(
        "Authorization: Bearer header-secret "
        "https://user:url-secret@example.test?a=1&token=query-secret "
        "{'api_key': 'dict-secret'}"
    )
    assert sanitized is not None
    for secret in ("header-secret", "url-secret", "query-secret", "dict-secret"):
        assert secret not in sanitized


def test_sm08a_output_contract_rejects_wrong_identity_nonfinite_and_missing_quantiles() -> None:
    import pandas as pd

    window = _window()
    base = pd.DataFrame(
        {
            "unique_id": [window.rows[0].unique_id] * 3,
            "ds": pd.to_datetime(runtime.EXPECTED_FORECAST_TIMESTAMPS),
            "P105": [1.0, 2.0, 3.0],
            **{f"P105-q-{value}": [1.0, 2.0, 3.0] for value in range(10, 100, 10)},
        }
    )
    runtime._validate_output(base, "connected_quantiles", window)

    wrong_identity = base.copy()
    wrong_identity["unique_id"] = "wrong-series"
    with pytest.raises(runtime.OutputContractError, match="unique_id"):
        runtime._validate_output(wrong_identity, "connected_quantiles", window)

    nonfinite = base.copy()
    nonfinite.loc[1, "P105"] = float("nan")
    with pytest.raises(runtime.OutputContractError, match="finite"):
        runtime._validate_output(nonfinite, "connected_quantiles", window)

    missing_quantile = base.drop(columns=["P105-q-40"])
    with pytest.raises(runtime.OutputContractError, match="omitted"):
        runtime._validate_output(missing_quantile, "connected_quantiles", window)


def test_sm08b_gpu_preflight_failure_publishes_partial_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    approval_path = tmp_path / selection.EVIDENCE_RELATIVE_PATH
    approval_path.parent.mkdir(parents=True)
    approval_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "assert_project_venv", lambda root: None)
    monkeypatch.setattr(
        selection,
        "validate_published_state",
        lambda root: {"decision_id": "P1-04-test"},
    )
    monkeypatch.setattr(
        selection,
        "require_runtime_approval",
        lambda root, variants: runtime.APPROVED_VARIANT_IDS,
    )
    monkeypatch.setattr(runtime, "load_runtime_window", lambda root: _window())
    monkeypatch.setattr(
        runtime,
        "configure_cuda_environment",
        lambda: (_ for _ in ()).throw(runtime.RuntimePreflightError("CUDA blocked")),
    )
    published: list[dict[str, Any]] = []

    def publish(root: Path, record: dict[str, Any]) -> dict[str, Any]:
        validated = runtime.validate_record(record, window=_window())
        published.append(validated)
        return validated

    monkeypatch.setattr(runtime, "publish_record", publish)
    record = runtime.run_live_matrix(tmp_path)
    assert record["matrix_completeness"] == "partial"
    assert record["task_outcome"] == "blocked"
    assert record["selected_reference"] is None
    assert record["errors"] == ["RuntimePreflightError: CUDA blocked"]
    assert published == [record]


def test_sm09_roadmap_gate_requires_complete_pass_and_reference() -> None:
    window = _window()
    candidates = [
        _candidate(variant_id, order, window, passing=False)
        for order, variant_id in enumerate(runtime.APPROVED_VARIANT_IDS)
    ]
    record = _complete_record(window, candidates)
    assert record["task_outcome"] == "fail"
    assert runtime.roadmap_ready(record) is False


def test_exact_transformers_identity_is_forwarded_and_classified_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def reject(variant_id: str) -> Any:
        seen.append(variant_id)
        raise ValueError("TimesFM only supports pytorch models")

    monkeypatch.setattr(runtime, "_adapter_for_variant", reject)
    monkeypatch.setattr(runtime, "require_gpu_runtime", lambda: {})
    result = runtime.run_worker_attempt(
        REPO_ROOT,
        "google/timesfm-2.5-200m-transformers",
        "connected_point",
    )
    assert seen == ["google/timesfm-2.5-200m-transformers"]
    assert result["outcome"] == "unsupported"
    assert result["exception_class"] == "ValueError"


@pytest.mark.skipif(os.environ.get("P1_05_RUN_LIVE") != "1", reason="set P1_05_RUN_LIVE=1 for live matrix")
def test_live_runtime_matrix() -> None:
    record = runtime.run_live_matrix(REPO_ROOT)
    assert record["matrix_completeness"] == "complete"
    assert record["task_outcome"] == "pass"
    assert record["selector_executed"] is True
    assert record["selected_reference"] in runtime.APPROVED_VARIANT_IDS
    assert runtime.validate_published_state(REPO_ROOT) == record
