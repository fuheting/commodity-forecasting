from __future__ import annotations

import copy
import csv
import io
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import pytest

from commodity_forecasting.phase1 import evaluation, rolling_origin


REPO_ROOT = Path(__file__).resolve().parents[2]


def _source_record(origin: str, horizon: int) -> dict[str, object]:
    record: dict[str, object] = {column: "unused" for column in rolling_origin.OUTPUT_COLUMNS}
    record.update(
        {
            "origin": origin,
            "forecast_horizon_step": horizon,
            "actual": 0.0,
            "reference_model_id": rolling_origin.REFERENCE_MODEL_ID,
            "p1_05_evidence_sha256": rolling_origin.P1_05_EVIDENCE_SHA256,
            "publication_label": rolling_origin.PUBLICATION_POLICY.evaluation_label,
            "publication_proxy": rolling_origin.PUBLICATION_POLICY.availability_proxy,
            "vintage_limitation": rolling_origin.PUBLICATION_POLICY.limitation,
        }
    )
    if horizon == 1:
        point, lower, upper, quantile = 1.0, -1.0, 1.0, 1.0
    elif horizon == 2:
        point, lower, upper, quantile = 2.0, 1.0, 3.0, -2.0
    else:
        point, lower, upper, quantile = 3.0, 0.0, 6.0, 0.0
    record.update(
        {
            "point_forecast": point,
            "interval_80_lower": lower,
            "interval_80_upper": upper,
        }
    )
    record.update({column: quantile for column in evaluation.QUANTILE_COLUMNS})
    return record


def _grouping_rows() -> tuple[evaluation.EvaluationRow, ...]:
    records = [
        _source_record(origin, horizon)
        for origin in ("2026-03-01", "2026-04-01", "2026-05-01")
        for horizon in evaluation.HORIZON_STEPS
    ]
    return evaluation.normalize_evaluation_rows(records)


def _publication_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    paths = (
        rolling_origin.EVIDENCE_RELATIVE_PATH,
        rolling_origin.FINDING_RELATIVE_PATH,
        rolling_origin.FORECASTS_RELATIVE_PATH,
        rolling_origin.P1_05_RELATIVE_PATH,
        rolling_origin.TARGET_RELATIVE_PATH,
        rolling_origin.ROADMAP_RELATIVE_PATH,
    )
    for relative in paths:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, destination)
    return root


def _published(root: Path) -> dict[str, object]:
    return evaluation.publish_evaluation_bundle(
        root, now=datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    )


def _read_marker(root: Path) -> dict[str, object]:
    marker = json.loads((root / evaluation.EVIDENCE_RELATIVE_PATH).read_text())
    assert isinstance(marker, dict)
    return marker


def _write_marker(root: Path, marker: Mapping[str, object]) -> None:
    (root / evaluation.EVIDENCE_RELATIVE_PATH).write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _unchecked_roadmap(root: Path) -> bytes:
    path = root / evaluation.ROADMAP_RELATIVE_PATH
    original = path.read_text(encoding="utf-8")
    unchecked = evaluation.P1_07_ROADMAP_PATTERN.sub(
        "- [ ] **P1-07", original, count=1
    )
    path.write_text(unchecked, encoding="utf-8")
    return path.read_bytes()


def test_point_metric_arithmetic_and_rejections() -> None:
    actuals = [1.0, 2.0, 3.0]
    forecasts = [2.0, 2.0, 1.0]
    assert evaluation.mean_absolute_error(actuals, forecasts) == 1.0
    assert math.isclose(
        evaluation.root_mean_squared_error(actuals, forecasts),
        math.sqrt(5.0 / 3.0),
        rel_tol=1e-15,
    )
    assert evaluation.mean_absolute_error([1.0], [1.0]) == 0.0
    assert evaluation.root_mean_squared_error([1.0], [1.0]) == 0.0
    with pytest.raises(evaluation.EvaluationInputError):
        evaluation.mean_absolute_error([], [])
    with pytest.raises(evaluation.EvaluationInputError):
        evaluation.root_mean_squared_error([float("nan")], [1.0])


def test_interval_arithmetic_is_inclusive() -> None:
    coverage, width = evaluation.interval_metrics(
        [1.0, 2.0, 3.0], [1.0, 0.0, 0.0], [2.0, 2.0, 2.0]
    )
    assert math.isclose(coverage, 2.0 / 3.0)
    assert math.isclose(width, 5.0 / 3.0)
    assert evaluation.interval_metrics([1.0], [1.0], [1.0]) == (1.0, 0.0)
    with pytest.raises(evaluation.EvaluationInputError, match="exceeds"):
        evaluation.interval_metrics([1.0], [2.0], [1.0])


@pytest.mark.parametrize(
    ("quantile", "actual", "forecast", "loss", "coverage"),
    [
        (0.1, 2.0, 1.0, 0.1, 0.0),
        (0.1, 1.0, 3.0, 1.8, 1.0),
        (0.9, 2.0, 1.0, 0.9, 0.0),
        (0.9, 1.0, 3.0, 0.2, 1.0),
        (0.1, 1.0, 1.0, 0.0, 1.0),
    ],
)
def test_pinball_sign_and_quantile_equality(
    quantile: float, actual: float, forecast: float, loss: float, coverage: float
) -> None:
    assert math.isclose(evaluation.pinball_loss(actual, forecast, quantile), loss)
    assert evaluation.empirical_quantile_coverage([actual], [forecast]) == coverage


@pytest.mark.parametrize("quantile", [0.0, 1.0, -0.1, 1.1])
def test_pinball_rejects_invalid_quantile(quantile: float) -> None:
    with pytest.raises(evaluation.EvaluationInputError):
        evaluation.pinball_loss(1.0, 1.0, quantile)


def test_complete_frozen_group_arithmetic_and_order() -> None:
    rows = tuple(reversed(_grouping_rows()))
    results = evaluation.calculate_evaluation_results(rows)
    aggregate = results["aggregate"]
    assert isinstance(aggregate, Mapping)
    assert aggregate["row_count"] == 9
    point = aggregate["point"]
    interval = aggregate["interval"]
    assert isinstance(point, Mapping) and isinstance(interval, Mapping)
    assert point["mae"] == 2.0
    assert math.isclose(float(point["rmse"]), math.sqrt(42.0) / 3.0)
    assert math.isclose(float(interval["empirical_coverage"]), 2.0 / 3.0)
    assert math.isclose(float(interval["mean_width"]), 10.0 / 3.0)
    groups = [aggregate, *results["per_horizon"]]  # type: ignore[misc]
    assert [(group["group_type"], group["group_value"]) for group in groups] == [
        ("aggregate", None), ("horizon", 1), ("horizon", 2), ("horizon", 3)
    ]
    for group_index, group in enumerate(groups):
        point = group["point"]
        interval = group["interval"]
        assert isinstance(point, Mapping) and isinstance(interval, Mapping)
        expected_point = (
            (2.0, math.sqrt(42.0) / 3.0),
            (1.0, 1.0),
            (2.0, 2.0),
            (3.0, 3.0),
        )[group_index]
        expected_interval = (
            (2.0 / 3.0, 10.0 / 3.0),
            (1.0, 2.0),
            (0.0, 2.0),
            (1.0, 6.0),
        )[group_index]
        assert math.isclose(float(point["mae"]), expected_point[0])
        assert math.isclose(float(point["rmse"]), expected_point[1])
        assert math.isclose(
            float(interval["empirical_coverage"]), expected_interval[0]
        )
        assert math.isclose(float(interval["mean_width"]), expected_interval[1])
        assert group["row_count"] == (9, 3, 3, 3)[group_index]
        quantiles = group["quantiles"]
        assert [record["quantile"] for record in quantiles] == list(evaluation.QUANTILES)
        for record in quantiles:
            q = record["quantile"]
            expected_loss = ((1.0 + q) / 3.0, 1.0 - q, 2.0 * q, 0.0)[group_index]
            expected_coverage = (2.0 / 3.0, 1.0, 0.0, 1.0)[group_index]
            assert math.isclose(record["mean_pinball_loss"], expected_loss)
            assert math.isclose(record["empirical_coverage"], expected_coverage)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "horizon", "empty", "nan", "crossing"])
def test_grid_and_value_failures_are_rejected(mutation: str) -> None:
    records = [_source_record(row.origin, row.forecast_horizon_step) for row in _grouping_rows()]
    if mutation == "missing":
        records.pop()
    elif mutation == "duplicate":
        records[-1] = copy.deepcopy(records[0])
    elif mutation == "horizon":
        records[-1]["forecast_horizon_step"] = 4
    elif mutation == "empty":
        records[-1]["actual"] = ""
    elif mutation == "nan":
        records[-1]["actual"] = float("nan")
    else:
        records[-1]["quantile_0_1"] = 100.0
    with pytest.raises(evaluation.EvaluationInputError):
        evaluation.normalize_evaluation_rows(records)


def test_parse_csv_requires_exact_column_order() -> None:
    records = [_source_record(row.origin, row.forecast_horizon_step) for row in _grouping_rows()]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=tuple(reversed(rolling_origin.OUTPUT_COLUMNS)))
    writer.writeheader()
    writer.writerows(records)
    with pytest.raises(evaluation.EvaluationInputError, match="columns"):
        evaluation.parse_evaluation_csv(stream.getvalue())


def test_closed_schema_rejects_unknown_and_decision_fields() -> None:
    results = evaluation.calculate_evaluation_results(_grouping_rows())
    binding = {key: "value" for key in evaluation.SOURCE_BINDING_KEYS}
    binding["p1_06_evidence_sha256"] = "a" * 64
    binding["p1_06_forecast_csv_sha256"] = "b" * 64
    binding["p1_06_evidence_path"] = str(evaluation.P1_06_EVIDENCE_RELATIVE_PATH)
    binding["p1_06_forecast_csv_path"] = str(evaluation.FORECASTS_RELATIVE_PATH)
    binding["p1_06_marker_state"] = "pass_final"
    evidence = evaluation.build_evaluation_evidence(
        source_binding=binding,
        results=results,
        markdown_sha256="c" * 64,
        now=datetime(2026, 8, 16, tzinfo=timezone.utc),
    )
    mutated = copy.deepcopy(evidence)
    mutated["results"]["aggregate"]["threshold"] = 1.0
    with pytest.raises(evaluation.PublicationValidationError, match="closed schema"):
        evaluation.validate_evidence_schema(mutated)
    mutated = copy.deepcopy(evidence)
    mutated["publication_protocol"]["p1_06_run_id"] = "wrong block"
    with pytest.raises(evaluation.PublicationValidationError, match="closed schema"):
        evaluation.validate_evidence_schema(mutated)


def test_markdown_is_canonical_ordered_and_has_no_quality_verdict() -> None:
    results = evaluation.calculate_evaluation_results(_grouping_rows())
    binding = {key: "value" for key in evaluation.SOURCE_BINDING_KEYS}
    binding["p1_06_evidence_sha256"] = "a" * 64
    binding["p1_06_forecast_csv_sha256"] = "b" * 64
    binding["p1_06_evidence_path"] = str(evaluation.P1_06_EVIDENCE_RELATIVE_PATH)
    binding["p1_06_forecast_csv_path"] = str(evaluation.FORECASTS_RELATIVE_PATH)
    binding["p1_06_marker_state"] = "pass_final"
    evidence = evaluation.build_evaluation_evidence(
        source_binding=binding, results=results, markdown_sha256="c" * 64
    )
    first = evaluation.render_evaluation_markdown(evidence)
    assert first == evaluation.render_evaluation_markdown(evidence)
    assert first.index("## Aggregate") < first.index("## Horizon 1") < first.index("## Horizon 2") < first.index("## Horizon 3")
    assert "not a performance verdict or pass/fail gate" in first


def test_publication_recalculates_and_binds_both_source_hashes(tmp_path: Path) -> None:
    root = _publication_root(tmp_path)
    published = _published(root)
    binding = published["source_binding"]
    assert isinstance(binding, Mapping)
    assert binding["p1_06_evidence_sha256"] == evaluation._sha256_path(root / rolling_origin.EVIDENCE_RELATIVE_PATH)
    assert binding["p1_06_forecast_csv_sha256"] == evaluation._sha256_path(root / rolling_origin.FORECASTS_RELATIVE_PATH)
    assert published["publication_protocol"]["marker_state"] == "pass_final"  # type: ignore[index]
    assert evaluation.validate_evaluation_publication(root) == published


def test_publication_validation_rejects_metric_and_markdown_mutation(tmp_path: Path) -> None:
    root = _publication_root(tmp_path)
    _published(root)
    evidence_path = root / evaluation.EVIDENCE_RELATIVE_PATH
    evidence = json.loads(evidence_path.read_text())
    evidence["results"]["aggregate"]["point"]["mae"] += 1.0
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(evaluation.PublicationValidationError, match="recomputation"):
        evaluation.validate_evaluation_publication(root)


@pytest.mark.parametrize(
    "mutation",
    [
        "point_metric",
        "interval_metric",
        "quantile_metric",
        "group_row_count",
        "group_order",
        "source_binding",
        "policy",
        "check",
        "artifact_path",
        "marker_path",
        "marker_state",
        "prior_marker_sha256",
        "markdown_sha256",
        "write_order",
        "commit_marker_valid",
    ],
)
def test_publication_validation_rejects_contract_mutation_matrix(
    tmp_path: Path, mutation: str
) -> None:
    root = _publication_root(tmp_path)
    _published(root)
    evidence = _read_marker(root)
    if mutation == "point_metric":
        evidence["results"]["per_horizon"][0]["point"]["rmse"] += 0.25
    elif mutation == "interval_metric":
        evidence["results"]["per_horizon"][1]["interval"]["mean_width"] += 0.25
    elif mutation == "quantile_metric":
        evidence["results"]["per_horizon"][2]["quantiles"][4]["mean_pinball_loss"] += 0.25
    elif mutation == "group_row_count":
        evidence["results"]["per_horizon"][0]["row_count"] = 4
    elif mutation == "group_order":
        evidence["results"]["per_horizon"].reverse()
    elif mutation == "source_binding":
        evidence["source_binding"]["p1_06_forecast_csv_sha256"] = "0" * 64
    elif mutation == "policy":
        evidence["source_binding"]["p1_06_publication_label"] = "wrong-policy"
    elif mutation == "check":
        evidence["checks"]["metrics_complete"] = False
    elif mutation == "artifact_path":
        evidence["artifact_paths"][0] = "docs/findings/phase1/wrong.md"
    elif mutation == "marker_path":
        evidence["publication_protocol"]["marker_path"] = "wrong.json"
    elif mutation == "marker_state":
        evidence["publication_protocol"]["marker_state"] = "invalid_final"
    elif mutation == "prior_marker_sha256":
        evidence["publication_protocol"]["prior_marker_sha256"] = "not-a-hash"
    elif mutation == "markdown_sha256":
        evidence["publication_protocol"]["evaluation_markdown_sha256"] = "0" * 64
    elif mutation == "write_order":
        evidence["publication_protocol"]["write_order"].reverse()
    else:
        evidence["publication_protocol"]["commit_marker_valid"] = False
    _write_marker(root, evidence)
    with pytest.raises(evaluation.PublicationValidationError):
        evaluation.validate_evaluation_publication(root)
    _published(root)
    (root / evaluation.FINDING_RELATIVE_PATH).write_text("mutated", encoding="utf-8")
    with pytest.raises(evaluation.PublicationValidationError, match="Markdown hash"):
        evaluation.validate_evaluation_publication(root)


def test_source_drift_invalidates_publication(tmp_path: Path) -> None:
    root = _publication_root(tmp_path)
    _published(root)
    csv_path = root / rolling_origin.FORECASTS_RELATIVE_PATH
    csv_path.write_bytes(csv_path.read_bytes() + b"\n")
    with pytest.raises(rolling_origin.PublicationValidationError):
        evaluation.validate_evaluation_publication(root)


def test_marker_lifecycle_failure_and_blocked_missing_source(tmp_path: Path) -> None:
    root = _publication_root(tmp_path)
    evaluation.begin_evaluation_attempt(root)
    marker = json.loads((root / evaluation.EVIDENCE_RELATIVE_PATH).read_text())
    assert marker["publication_protocol"]["marker_state"] == "invalid_in_progress"
    assert marker["classification"] == "blocked"
    (root / rolling_origin.FORECASTS_RELATIVE_PATH).unlink()
    with pytest.raises(evaluation.PublicationError):
        evaluation.publish_evaluation_bundle(root)
    marker = json.loads((root / evaluation.EVIDENCE_RELATIVE_PATH).read_text())
    assert marker["publication_protocol"]["marker_state"] == "invalid_final"
    assert marker["classification"] == "blocked"
    assert marker["results"] is None


@pytest.mark.parametrize(
    ("failure_boundary", "failure_call"),
    [("markdown_replacement", 2), ("json_replacement", 3)],
)
def test_replacement_boundary_failure_leaves_non_consumable_invalid_marker(
    tmp_path: Path, failure_boundary: str, failure_call: int
) -> None:
    root = _publication_root(tmp_path)
    calls = 0

    def fail_at_boundary(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise OSError(f"simulated {failure_boundary}")
        source.replace(destination)

    with pytest.raises(evaluation.PublicationError):
        evaluation.publish_evaluation_bundle(root, replace_file=fail_at_boundary)
    marker = _read_marker(root)
    assert marker["publication_protocol"]["marker_state"] == "invalid_final"
    assert marker["publication_protocol"]["commit_marker_valid"] is False
    assert marker["classification"] == "fail"
    with pytest.raises(evaluation.PublicationValidationError):
        evaluation.validate_evaluation_publication(root)


def test_failure_before_payload_staging_leaves_non_consumable_invalid_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _publication_root(tmp_path)
    original_stage = evaluation._stage_bytes
    calls = 0

    def fail_before_payload_staging(destination: Path, payload: bytes) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated failure before payload staging")
        return original_stage(destination, payload)

    monkeypatch.setattr(evaluation, "_stage_bytes", fail_before_payload_staging)
    with pytest.raises(evaluation.PublicationError):
        evaluation.publish_evaluation_bundle(root)
    marker = _read_marker(root)
    assert marker["publication_protocol"]["marker_state"] == "invalid_final"
    assert marker["publication_protocol"]["commit_marker_valid"] is False
    assert marker["classification"] == "fail"
    with pytest.raises(evaluation.PublicationValidationError):
        evaluation.validate_evaluation_publication(root)


@pytest.mark.parametrize("invalid_source", ["malformed_csv", "stale_csv"])
def test_malformed_or_stale_source_is_fail_not_blocked(
    tmp_path: Path, invalid_source: str
) -> None:
    root = _publication_root(tmp_path)
    csv_path = root / rolling_origin.FORECASTS_RELATIVE_PATH
    if invalid_source == "malformed_csv":
        csv_path.write_text("wrong,columns\n1,2\n", encoding="utf-8")
    else:
        csv_path.write_bytes(csv_path.read_bytes() + b"\n")
    with pytest.raises(evaluation.PublicationError):
        evaluation.publish_evaluation_bundle(root)
    marker = _read_marker(root)
    assert marker["classification"] == "fail"
    assert marker["publication_protocol"]["marker_state"] == "invalid_final"
    assert marker["results"] is None
    assert marker["non_pass_diagnostics"]


@pytest.mark.parametrize(
    "missing_path", [rolling_origin.EVIDENCE_RELATIVE_PATH, rolling_origin.FORECASTS_RELATIVE_PATH]
)
def test_missing_source_prerequisite_is_blocked(
    tmp_path: Path, missing_path: Path
) -> None:
    root = _publication_root(tmp_path)
    (root / missing_path).unlink()
    with pytest.raises(evaluation.PublicationError):
        evaluation.publish_evaluation_bundle(root)
    marker = _read_marker(root)
    assert marker["classification"] == "blocked"
    assert marker["results"] is None
    assert marker["non_pass_diagnostics"]


def test_source_gate_runs_before_csv_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _publication_root(tmp_path)
    source = json.loads(
        (root / rolling_origin.EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    events: list[str] = []

    def gate(_: Path) -> Mapping[str, object]:
        events.append("gate")
        return source

    def parse(_: str | bytes) -> tuple[evaluation.EvaluationRow, ...]:
        events.append("parse_csv")
        return _grouping_rows()

    monkeypatch.setattr(rolling_origin, "validate_rolling_origin_consumer_gate", gate)
    monkeypatch.setattr(evaluation, "parse_evaluation_csv", parse)
    evaluation._load_validated_source(root)
    assert events == ["gate", "parse_csv"]


def test_evaluator_uses_embedded_actuals_without_alternate_target_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _publication_root(tmp_path)
    source = json.loads(
        (root / rolling_origin.EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    rows = list(_grouping_rows())
    first = rows[0]
    rows[0] = evaluation.EvaluationRow(
        origin=first.origin,
        forecast_horizon_step=first.forecast_horizon_step,
        actual=99.0,
        point_forecast=first.point_forecast,
        interval_80_lower=first.interval_80_lower,
        interval_80_upper=first.interval_80_upper,
        quantile_forecasts=first.quantile_forecasts,
        reference_model_id=first.reference_model_id,
        publication_label=first.publication_label,
        publication_proxy=first.publication_proxy,
        vintage_limitation=first.vintage_limitation,
    )

    def forbidden_target_loader(*_: object, **__: object) -> object:
        raise AssertionError("evaluation must not load alternate actuals")

    monkeypatch.setattr(
        rolling_origin, "validate_rolling_origin_consumer_gate", lambda _: source
    )
    monkeypatch.setattr(evaluation, "parse_evaluation_csv", lambda _: tuple(rows))
    monkeypatch.setattr(rolling_origin, "parse_target_csv", forbidden_target_loader)
    _, loaded_rows, _ = evaluation._load_validated_source(root)
    results = evaluation.calculate_evaluation_results(loaded_rows)
    assert loaded_rows[0].actual == 99.0
    assert results["aggregate"]["point"]["mae"] != 2.0


@pytest.mark.parametrize(
    ("argument", "operation"),
    [
        ("--publish", "publish_evaluation_bundle"),
        ("--validate-publication", "validate_evaluation_publication"),
        ("--update-roadmap", "update_evaluation_roadmap"),
        ("--check-roadmap", "check_evaluation_roadmap"),
    ],
)
def test_cli_dispatches_each_narrow_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    argument: str,
    operation: str,
) -> None:
    calls: list[Path] = []

    def dispatched(root: Path) -> object:
        calls.append(root)
        return True if operation == "check_evaluation_roadmap" else None

    monkeypatch.setattr(evaluation, operation, dispatched)
    assert evaluation.main(["--repo-root", str(tmp_path), argument]) == 0
    assert calls == [tmp_path.resolve()]


@pytest.mark.parametrize(
    "argument",
    ["--publish", "--validate-publication", "--update-roadmap", "--check-roadmap"],
)
def test_cli_returns_nonzero_when_dispatched_operation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argument: str
) -> None:
    def fail(_: Path) -> None:
        raise evaluation.PublicationError("simulated CLI failure")

    operation = {
        "--publish": "publish_evaluation_bundle",
        "--validate-publication": "validate_evaluation_publication",
        "--update-roadmap": "update_evaluation_roadmap",
        "--check-roadmap": "check_evaluation_roadmap",
    }[argument]
    monkeypatch.setattr(evaluation, operation, fail)
    assert evaluation.main(["--repo-root", str(tmp_path), argument]) == 1


def test_evaluation_contract_has_no_unsupported_classification() -> None:
    assert evaluation.CLASSIFICATIONS == ("pass", "fail", "blocked")
    assert "unsupported" not in json.dumps(
        evaluation.build_evaluation_evidence(
            marker_state="invalid_final",
            classification="fail",
            diagnostics=(
                {
                    "classification": "fail",
                    "stage": "test",
                    "sanitized_reason": "test failure",
                    "exception_class": None,
                },
            ),
            errors=("test failure",),
        )
    )


def test_roadmap_update_is_validation_gated_and_idempotent(tmp_path: Path) -> None:
    root = _publication_root(tmp_path)
    _published(root)
    _unchecked_roadmap(root)
    evaluation.update_evaluation_roadmap(root)
    changed = (root / evaluation.ROADMAP_RELATIVE_PATH).read_text()
    assert "- [x] **P1-07" in changed
    evaluation.update_evaluation_roadmap(root)
    assert (root / evaluation.ROADMAP_RELATIVE_PATH).read_text() == changed
    assert evaluation.check_evaluation_roadmap(root)


@pytest.mark.parametrize("invalid_evidence", ["malformed", "stale"])
def test_invalid_or_stale_evidence_does_not_mutate_roadmap(
    tmp_path: Path, invalid_evidence: str
) -> None:
    root = _publication_root(tmp_path)
    _published(root)
    before = _unchecked_roadmap(root)
    if invalid_evidence == "malformed":
        (root / evaluation.EVIDENCE_RELATIVE_PATH).write_text(
            "{malformed", encoding="utf-8"
        )
    else:
        csv_path = root / rolling_origin.FORECASTS_RELATIVE_PATH
        csv_path.write_bytes(csv_path.read_bytes() + b"\n")
    with pytest.raises(
        (evaluation.PublicationValidationError, rolling_origin.PublicationValidationError)
    ):
        evaluation.update_evaluation_roadmap(root)
    assert (root / evaluation.ROADMAP_RELATIVE_PATH).read_bytes() == before


def test_roadmap_update_preserves_every_unrelated_byte(tmp_path: Path) -> None:
    root = _publication_root(tmp_path)
    _published(root)
    path = root / evaluation.ROADMAP_RELATIVE_PATH
    original = _unchecked_roadmap(root).decode("utf-8")
    sentinel = "\nUnrelated sentinel: preserve spacing, punctuation, and text.\n"
    path.write_text(original + sentinel, encoding="utf-8")
    evaluation.update_evaluation_roadmap(root)
    expected = evaluation.P1_07_ROADMAP_PATTERN.sub(
        "- [x] **P1-07", original + sentinel, count=1
    )
    assert path.read_text(encoding="utf-8") == expected
