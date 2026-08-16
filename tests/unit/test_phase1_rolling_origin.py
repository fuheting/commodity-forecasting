from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

import pytest

from commodity_forecasting.phase1 import rolling_origin
from commodity_forecasting.phase1.target_pipeline import MODEL_READY_RELATIVE_PATH, parse_target_csv

REPO_ROOT = Path(__file__).resolve().parents[2]
P1_05_PATH = REPO_ROOT / "docs/findings/phase1/evidence/runtime_compatibility.json"


class TrapAdapter:
    def __init__(self, *, mutation: str | None = None) -> None:
        self.calls: list[tuple[tuple[dict[str, str], ...], dict[str, object]]] = []
        self.mutation = mutation

    def forecast(
        self,
        payload: Sequence[Mapping[str, str]],
        *,
        h: int,
        level: Sequence[int] | None = None,
        quantiles: Sequence[float] | None = None,
    ) -> list[dict[str, object]]:
        copied = tuple(dict(row) for row in payload)
        self.calls.append((copied, {"h": h, "level": level, "quantiles": quantiles}))
        start = rolling_origin.add_months(_as_date(copied[-1]["ds"]), 1)
        rows: list[dict[str, object]] = []
        for index in range(h):
            point = 10.0 + index
            row: dict[str, object] = {
                "unique_id": copied[0]["unique_id"],
                "ds": rolling_origin.add_months(start, index).isoformat(),
                "P105": point,
            }
            if level is not None:
                row.update({"P105-lo-80": point - 2.0, "P105-hi-80": point + 2.0})
            if quantiles is not None:
                row.update({f"P105-q-{int(q * 100)}": point - 5.0 + q * 10.0 for q in quantiles})
            rows.append(row)
        if self.mutation and len(self.calls) == 9:
            if self.mutation == "timestamp":
                rows[-1]["ds"] = "2026-08-01"
            elif self.mutation == "nan":
                rows[0]["P105-q-10"] = float("nan")
            elif self.mutation == "crossing":
                rows[0]["P105-q-10"] = 50.0
            elif self.mutation == "identity":
                rows[0]["unique_id"] = "wrong-series"
        return rows

    def fit(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("fit must never be called")

    train = fine_tune = calibrate = update_weights = cross_validation = fit


def _as_date(value: str):
    from datetime import date

    return date.fromisoformat(value)


@pytest.fixture(scope="module")
def target_rows():
    return parse_target_csv(REPO_ROOT / MODEL_READY_RELATIVE_PATH)


def test_p1_05_binding_is_exact_and_hash_bound(tmp_path: Path) -> None:
    binding = rolling_origin.validate_p1_05_binding(P1_05_PATH)
    assert binding.evidence_sha256 == rolling_origin.P1_05_EVIDENCE_SHA256
    assert binding.selection["selected_reference"] == rolling_origin.REFERENCE_MODEL_ID
    assert binding.selection["selected_candidate"] == {
        "variant_id": rolling_origin.REFERENCE_MODEL_ID,
        "contract_completeness": True,
        "probabilistic_output_kind": "both",
    }

    mutated = json.loads(P1_05_PATH.read_text(encoding="utf-8"))
    mutated["selected_reference"] = "different/reference"
    changed_path = tmp_path / "runtime_compatibility.json"
    changed_path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(rolling_origin.P105BindingError, match="SHA-256"):
        rolling_origin.validate_p1_05_binding(changed_path)


def test_schedule_is_derived_from_endpoint_and_is_deterministic(target_rows) -> None:
    first = rolling_origin.build_rolling_origin_schedule(target_rows)
    second = rolling_origin.build_rolling_origin_schedule(tuple(target_rows))
    assert first.origins == tuple(_as_date(value) for value in ("2026-03-01", "2026-04-01", "2026-05-01"))
    assert first.cutoffs == tuple(_as_date(value) for value in ("2026-02-01", "2026-03-01", "2026-04-01"))
    assert rolling_origin.schedule_digest(first) == rolling_origin.schedule_digest(second)
    assert [window.historic_context_start.isoformat() for window in first.windows] == [
        "2021-03-01",
        "2021-04-01",
        "2021-05-01",
    ]
    assert [window.forecast_end.isoformat() for window in first.windows] == [
        "2026-05-01",
        "2026-06-01",
        "2026-07-01",
    ]
    assert all(len(window.context_rows) == 60 for window in first.windows)


def test_nine_serial_forecast_only_calls_are_history_only(target_rows) -> None:
    adapter = TrapAdapter()
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, adapter)
    assert len(adapter.calls) == 9
    assert [call[1] for call in adapter.calls[:3]] == [
        {"h": 3, "level": None, "quantiles": None},
        {"h": 3, "level": [80], "quantiles": None},
        {"h": 3, "level": None, "quantiles": list(rolling_origin.QUANTILES)},
    ]
    for origin_index, window in enumerate(result.schedule.windows):
        requests = adapter.calls[origin_index * 3 : origin_index * 3 + 3]
        assert all(tuple(row.keys()) == rolling_origin.ADAPTER_PAYLOAD_COLUMNS for payload, _ in requests for row in payload)
        assert all(len(payload) == 60 for payload, _ in requests)
        assert all(payload[-1]["ds"] == window.cutoff.isoformat() for payload, _ in requests)
        assert all(max(row["ds"] for row in payload) < window.origin.isoformat() for payload, _ in requests)
        digests = [rolling_origin.adapter_payload_digest(payload) for payload, _ in requests]
        assert len(set(digests)) == 1 == len({result.origins[origin_index].input_digest})


def test_closed_rows_use_point_request_and_join_actuals(target_rows) -> None:
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TrapAdapter())
    serialized = rolling_origin.serialize_rolling_origin_csv(result)
    rows = list(csv.DictReader(io.StringIO(serialized.decode("utf-8"))))
    target = {row.ds.isoformat(): float(row.y) for row in target_rows}
    assert len(rows) == 9
    assert tuple(rows[0]) == rolling_origin.OUTPUT_COLUMNS
    assert [row["forecast_horizon_step"] for row in rows] == ["1", "2", "3"] * 3
    assert all(float(row["point_forecast"]) in {10.0, 11.0, 12.0} for row in rows)
    assert all(float(row["actual"]) == target[row["forecast_month"]] for row in rows)
    records = [rolling_origin.normalize_origin_record(record) for record in result.origins]
    assert all(record["output_shape"] == {"rows": 3, "columns": 24} for record in records)
    assert all(len({record[key] for key in ("input_digest", "point_input_digest", "interval_input_digest", "quantile_input_digest")}) == 1 for record in records)


def test_datetime_response_timestamps_are_normalized_to_month_strings(target_rows) -> None:
    class TimestampAdapter(TrapAdapter):
        def forecast(self, payload, *, h, level=None, quantiles=None):
            rows = super().forecast(payload, h=h, level=level, quantiles=quantiles)
            return [
                {**row, "ds": datetime.fromisoformat(str(row["ds"]))}
                for row in rows
            ]

    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TimestampAdapter())
    assert len(result.rows) == 9


@pytest.mark.parametrize("mutation", ["timestamp", "nan", "crossing", "identity"])
def test_all_responses_validate_before_any_actuals_are_joined(target_rows, mutation: str) -> None:
    adapter = TrapAdapter(mutation=mutation)
    guarded = list(copy.deepcopy(target_rows))
    with pytest.raises(rolling_origin.ForecastResponseError):
        rolling_origin.run_rolling_origin_forecasts(guarded, adapter)
    assert len(adapter.calls) == 9


def test_request_and_binding_mismatches_fail_closed(target_rows) -> None:
    with pytest.raises(rolling_origin.P105BindingError):
        rolling_origin.run_rolling_origin_forecasts(
            target_rows,
            TrapAdapter(),
            reference_model_id="other/model",
        )
    truncated = target_rows[:-1]
    with pytest.raises(rolling_origin.ScheduleContractError, match="approved schedule"):
        rolling_origin.build_rolling_origin_schedule(truncated)


def _publication_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    target = root / rolling_origin.TARGET_RELATIVE_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes((REPO_ROOT / MODEL_READY_RELATIVE_PATH).read_bytes())
    binding = root / rolling_origin.P1_05_RELATIVE_PATH
    binding.parent.mkdir(parents=True)
    binding.write_bytes(P1_05_PATH.read_bytes())
    roadmap = root / rolling_origin.ROADMAP_RELATIVE_PATH
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_bytes((REPO_ROOT / rolling_origin.ROADMAP_RELATIVE_PATH).read_bytes())
    return root


def _live_receipt(result: rolling_origin.RollingOriginResult) -> rolling_origin.LiveExecutionReceipt:
    receipts = tuple(
        rolling_origin.ForecastCallReceipt(
            origin=origin.window.origin.isoformat(),
            request_kind=request_kind,
            input_digest=origin.input_digest,
            output_sha256=hashlib.sha256(
                f"{origin.window.origin.isoformat()}:{request_kind}".encode("utf-8")
            ).hexdigest(),
            output_rows=3,
        )
        for origin in result.origins
        for request_kind in ("point", "interval_80", "quantiles_01_09")
    )
    return rolling_origin.LiveExecutionReceipt(
        runner_kind="timecopilot_live",
        execution_mode="zero_shot_forecast_only",
        adapter_class="timecopilot.models.foundation.chronos.Chronos",
        model_id=rolling_origin.REFERENCE_MODEL_ID,
        model_alias="P105",
        package_versions=(
            ("timecopilot", "test-version"),
            ("timecopilot-chronos-forecasting", "test-version"),
        ),
        network_policy="offline_cache_only",
        cache_policy="explicit_hf_hub_cache",
        call_receipts=receipts,
    )


def test_canonical_publication_rejects_unattested_results(target_rows, tmp_path: Path) -> None:
    root = _publication_root(tmp_path)
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TrapAdapter())
    with pytest.raises(rolling_origin.PublicationError, match="attestation"):
        rolling_origin.publish_rolling_origin_bundle(result, root)


def test_result_validation_rejects_metadata_drift(target_rows) -> None:
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TrapAdapter())
    first_origin = result.origins[0]
    values = list(first_origin.rows[0].values)
    values[rolling_origin.OUTPUT_COLUMNS.index("historic_context_start")] = "1900-01-01"
    drifted_origin = rolling_origin.OriginRecord(
        first_origin.window,
        first_origin.input_digest,
        (rolling_origin.ForecastRow(tuple(values)), *first_origin.rows[1:]),
    )
    drifted = rolling_origin.RollingOriginResult(
        result.schedule,
        (drifted_origin, *result.origins[1:]),
    )
    with pytest.raises(rolling_origin.ForecastResponseError, match="historic_context_start"):
        rolling_origin.validate_rolling_origin_result(drifted)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("historic_context_start", "1900-01-01"),
        ("publication_label", "vintage_real_time"),
        ("publication_proxy", "same_month"),
        ("vintage_limitation", "none"),
    ],
)
def test_published_csv_validation_rejects_metadata_drift(
    target_rows, tmp_path: Path, column: str, value: str
) -> None:
    root = _publication_root(tmp_path)
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TrapAdapter())
    evidence = rolling_origin.publish_rolling_origin_bundle(
        result,
        root,
        execution_receipt=_live_receipt(result),
    )
    csv_path = root / rolling_origin.FORECASTS_RELATIVE_PATH
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = tuple(reader.fieldnames or ())
    rows[0][column] = value
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(rolling_origin.PublicationValidationError, match="context start|policy field"):
        rolling_origin._validate_published_csv(root, evidence)


def test_live_dependency_failure_is_blocked_at_request_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _publication_root(tmp_path)

    def blocked_adapter():
        raise rolling_origin.LiveDependencyError("missing live adapter")

    monkeypatch.setattr(rolling_origin, "_load_live_adapter", blocked_adapter)
    with pytest.raises(rolling_origin.PublicationError, match="adapter load"):
        rolling_origin.run_live_rolling_origin(root)
    marker = json.loads((root / rolling_origin.EVIDENCE_RELATIVE_PATH).read_text())
    assert marker["classification"] == "blocked"
    assert marker["non_pass_diagnostics"][0]["stage"] == "request"
    assert marker["non_pass_diagnostics"][0]["exception_class"] == "LiveDependencyError"


def test_publication_marker_hashes_consumer_gate_and_idempotent_roadmap(
    target_rows, tmp_path: Path
) -> None:
    root = _publication_root(tmp_path)
    rolling_origin.begin_rolling_origin_attempt(root)
    in_progress = json.loads((root / rolling_origin.EVIDENCE_RELATIVE_PATH).read_text())
    assert in_progress["publication_protocol"]["marker_state"] == "invalid_in_progress"
    assert in_progress["publication_protocol"]["commit_marker_valid"] is False
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TrapAdapter())
    published = rolling_origin.publish_rolling_origin_bundle(
        result,
        root,
        execution_receipt=_live_receipt(result),
    )
    protocol = published["publication_protocol"]
    assert isinstance(protocol, Mapping)
    assert protocol["marker_state"] == "pass_final"
    rolling_origin.validate_rolling_origin_consumer_gate(root)
    rolling_origin.update_rolling_origin_roadmap(root)
    changed = (root / rolling_origin.ROADMAP_RELATIVE_PATH).read_text()
    assert "- [x] **P1-06" in changed
    rolling_origin.update_rolling_origin_roadmap(root)
    assert (root / rolling_origin.ROADMAP_RELATIVE_PATH).read_text() == changed


def test_consumer_gate_rejects_payload_without_matching_pass_marker(
    target_rows, tmp_path: Path
) -> None:
    root = _publication_root(tmp_path)
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TrapAdapter())
    rolling_origin.publish_rolling_origin_bundle(
        result,
        root,
        execution_receipt=_live_receipt(result),
    )
    evidence_path = root / rolling_origin.EVIDENCE_RELATIVE_PATH
    evidence = json.loads(evidence_path.read_text())
    evidence["publication_protocol"]["marker_state"] = "invalid_final"
    evidence["publication_protocol"]["commit_marker_valid"] = False
    evidence["publication_protocol"]["csv_sha256"] = None
    evidence["publication_protocol"]["markdown_sha256"] = None
    evidence["classification"] = "fail"
    evidence["non_pass_diagnostics"] = [{
        "classification": "fail",
        "scope": "test",
        "stage": "publication",
        "origin": None,
        "request_kind": None,
        "sanitized_reason": "test invalidation",
        "exception_class": None,
        "artifact_paths": list(rolling_origin.ARTIFACT_PATHS),
    }]
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(rolling_origin.PublicationValidationError, match="invalid_final state"):
        rolling_origin.validate_rolling_origin_consumer_gate(root)


def test_publication_boundary_failure_leaves_invalid_final_marker(
    target_rows, tmp_path: Path
) -> None:
    root = _publication_root(tmp_path)
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TrapAdapter())
    calls = 0

    def fail_on_markdown(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replacement boundary")
        source.replace(destination)

    with pytest.raises(rolling_origin.PublicationError, match="invalidated"):
        rolling_origin.publish_rolling_origin_bundle(
            result,
            root,
            execution_receipt=_live_receipt(result),
            replace_file=fail_on_markdown,
        )
    marker = json.loads((root / rolling_origin.EVIDENCE_RELATIVE_PATH).read_text())
    assert marker["publication_protocol"]["marker_state"] == "invalid_final"
    assert marker["publication_protocol"]["commit_marker_valid"] is False
    assert marker["non_pass_diagnostics"]


def test_consumer_gate_rejects_missing_target_after_publication(
    target_rows, tmp_path: Path
) -> None:
    root = _publication_root(tmp_path)
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TrapAdapter())
    rolling_origin.publish_rolling_origin_bundle(
        result,
        root,
        execution_receipt=_live_receipt(result),
    )
    (root / rolling_origin.TARGET_RELATIVE_PATH).unlink()
    with pytest.raises(rolling_origin.PublicationValidationError, match="target artifact"):
        rolling_origin.validate_rolling_origin_consumer_gate(root)


@pytest.mark.parametrize(
    "mutation", ["schedule", "zero_shot", "request_strategy", "digest", "execution_receipt"]
)
def test_consumer_gate_rejects_nested_pass_evidence_mutation(
    target_rows, tmp_path: Path, mutation: str
) -> None:
    root = _publication_root(tmp_path)
    result = rolling_origin.run_rolling_origin_forecasts(target_rows, TrapAdapter())
    rolling_origin.publish_rolling_origin_bundle(
        result,
        root,
        execution_receipt=_live_receipt(result),
    )
    evidence_path = root / rolling_origin.EVIDENCE_RELATIVE_PATH
    evidence = json.loads(evidence_path.read_text())
    if mutation == "schedule":
        evidence["schedule"]["step_months"] = 2
    elif mutation == "zero_shot":
        evidence["origin_records"][0]["zero_shot_assertions"]["no_fit"] = False
    elif mutation == "request_strategy":
        evidence["request_strategy"]["serial_forecast_calls"] = 8
    elif mutation == "digest":
        for key in ("input_digest", "point_input_digest", "interval_input_digest", "quantile_input_digest"):
            evidence["origin_records"][0][key] = "0" * 64
    else:
        evidence["execution_receipt"]["call_receipts"][0]["output_sha256"] = "0" * 63
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(rolling_origin.PublicationValidationError):
        rolling_origin.validate_rolling_origin_consumer_gate(root)
