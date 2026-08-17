"""Deterministic point and probabilistic evaluation of the P1-06 publication."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence, cast

from . import rolling_origin


TASK_ID = "P1-07"
EVIDENCE_SCHEMA_VERSION = 1
QUANTILES = rolling_origin.QUANTILES
HORIZON_STEPS = (1, 2, 3)
SOURCE_ROW_COUNT = 9
ORIGIN_COUNT = 3
INTERVAL_LEVEL = 80
FINDING_RELATIVE_PATH = Path("docs/findings/phase1/evaluation.md")
EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/evaluation.json")
FORECASTS_RELATIVE_PATH = rolling_origin.FORECASTS_RELATIVE_PATH
P1_06_EVIDENCE_RELATIVE_PATH = rolling_origin.EVIDENCE_RELATIVE_PATH
ROADMAP_RELATIVE_PATH = rolling_origin.ROADMAP_RELATIVE_PATH
ARTIFACT_PATHS = (str(FINDING_RELATIVE_PATH), str(EVIDENCE_RELATIVE_PATH))
WRITE_ORDER = ("evaluation.md", "evaluation.json")
MARKER_STATES = ("invalid_in_progress", "invalid_final", "pass_final")
CLASSIFICATIONS = ("pass", "fail", "blocked")
GROUP_ORDER = ("aggregate", "horizon_1", "horizon_2", "horizon_3")
P1_07_ROADMAP_PATTERN = re.compile(r"^- \[([ x])\] \*\*P1-07\b", re.MULTILINE)

TOP_LEVEL_KEYS = (
    "schema_version", "task_id", "run_id", "timestamp_utc", "classification",
    "source_binding", "evaluation_contract", "results", "publication_protocol",
    "checks", "errors", "non_pass_diagnostics", "artifact_paths",
)
SOURCE_BINDING_KEYS = (
    "p1_06_evidence_path", "p1_06_evidence_sha256", "p1_06_forecast_csv_path",
    "p1_06_forecast_csv_sha256", "p1_06_run_id", "p1_06_reference_model_id",
    "p1_06_publication_label", "p1_06_publication_proxy",
    "p1_06_vintage_limitation", "p1_06_marker_state",
)
CONTRACT_KEYS = (
    "source_row_count", "origin_count", "horizon_steps", "interval_level",
    "quantiles", "point_metrics", "interval_metrics", "quantile_metrics",
    "interval_coverage_rule", "quantile_coverage_rule", "group_order",
)
RESULTS_KEYS = ("aggregate", "per_horizon")
GROUP_KEYS = ("group_type", "group_value", "row_count", "point", "interval", "quantiles")
POINT_KEYS = ("mae", "rmse")
INTERVAL_KEYS = ("level", "empirical_coverage", "mean_width")
QUANTILE_RESULT_KEYS = ("quantile", "mean_pinball_loss", "empirical_coverage")
PROTOCOL_KEYS = (
    "marker_path", "marker_state", "prior_marker_sha256",
    "evaluation_markdown_sha256", "write_order", "commit_marker_valid",
)
CHECK_NAMES = (
    "p1_06_consumer_gate_valid", "source_binding_valid", "input_schema_valid",
    "input_grid_valid", "metrics_complete", "grouping_complete", "policy_preserved",
    "markdown_canonical", "publication_valid", "roadmap_update_eligible",
)
DIAGNOSTIC_KEYS = ("classification", "stage", "sanitized_reason", "exception_class")
QUANTILE_COLUMNS = tuple(f"quantile_0_{index}" for index in range(1, 10))
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
UTC_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


class EvaluationError(RuntimeError):
    """Base exception for the fixed P1-07 evaluation contract."""


class EvaluationInputError(EvaluationError):
    """Raised when the accepted source rows violate the evaluation contract."""


class PublicationError(EvaluationError):
    """Raised when the evaluation bundle cannot be published."""


class PublicationValidationError(EvaluationError):
    """Raised when a canonical evaluation bundle is not consumable."""


@dataclass(frozen=True)
class EvaluationRow:
    """Normalized numeric fields required for one origin/horizon evaluation row."""

    origin: str
    forecast_horizon_step: int
    actual: float
    point_forecast: float
    interval_80_lower: float
    interval_80_upper: float
    quantile_forecasts: tuple[float, ...]
    reference_model_id: str
    publication_label: str
    publication_proxy: str
    vintage_limitation: str


def _finite(value: object, field: str) -> float:
    try:
        number = float(cast(str | int | float, value))
    except (TypeError, ValueError) as exc:
        raise EvaluationInputError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise EvaluationInputError(f"{field} must be finite")
    return number


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError(f"{field} must be a non-empty string")
    return value


def normalize_evaluation_rows(rows: Sequence[Mapping[str, object]]) -> tuple[EvaluationRow, ...]:
    """Validate and normalize the exact three-origin by three-horizon grid."""

    if len(rows) != SOURCE_ROW_COUNT:
        raise EvaluationInputError("evaluation input must contain exactly nine rows")
    normalized: list[EvaluationRow] = []
    identities: set[tuple[str, int]] = set()
    for raw in rows:
        if set(raw) != set(rolling_origin.OUTPUT_COLUMNS):
            raise EvaluationInputError("evaluation input columns differ from the P1-06 closed schema")
        if any(value is None or (isinstance(value, str) and not value.strip()) for value in raw.values()):
            raise EvaluationInputError("evaluation input contains an empty required value")
        origin = _nonempty(raw.get("origin"), "origin")
        try:
            datetime.strptime(origin, "%Y-%m-%d")
        except ValueError as exc:
            raise EvaluationInputError("origin must be an ISO date") from exc
        horizon_number = _finite(raw.get("forecast_horizon_step"), "forecast_horizon_step")
        if not horizon_number.is_integer():
            raise EvaluationInputError("forecast_horizon_step must be an integer")
        horizon = int(horizon_number)
        if horizon not in HORIZON_STEPS:
            raise EvaluationInputError("forecast_horizon_step must be 1, 2, or 3")
        identity = (origin, horizon)
        if identity in identities:
            raise EvaluationInputError("duplicate (origin, forecast_horizon_step) identity")
        identities.add(identity)
        actual = _finite(raw.get("actual"), "actual")
        point = _finite(raw.get("point_forecast"), "point_forecast")
        lower = _finite(raw.get("interval_80_lower"), "interval_80_lower")
        upper = _finite(raw.get("interval_80_upper"), "interval_80_upper")
        if lower > upper:
            raise EvaluationInputError("interval lower bound exceeds upper bound")
        forecasts = tuple(_finite(raw.get(column), column) for column in QUANTILE_COLUMNS)
        if tuple(sorted(forecasts)) != forecasts:
            raise EvaluationInputError("quantile forecasts cross")
        normalized.append(
            EvaluationRow(
                origin=origin,
                forecast_horizon_step=horizon,
                actual=actual,
                point_forecast=point,
                interval_80_lower=lower,
                interval_80_upper=upper,
                quantile_forecasts=forecasts,
                reference_model_id=_nonempty(raw.get("reference_model_id"), "reference_model_id"),
                publication_label=_nonempty(raw.get("publication_label"), "publication_label"),
                publication_proxy=_nonempty(raw.get("publication_proxy"), "publication_proxy"),
                vintage_limitation=_nonempty(raw.get("vintage_limitation"), "vintage_limitation"),
            )
        )
    origins = sorted({row.origin for row in normalized})
    if len(origins) != ORIGIN_COUNT:
        raise EvaluationInputError("evaluation input must contain exactly three origins")
    expected_grid = {(origin, horizon) for origin in origins for horizon in HORIZON_STEPS}
    if identities != expected_grid:
        raise EvaluationInputError("evaluation identities do not form the exact three-by-three grid")
    for field in ("reference_model_id", "publication_label", "publication_proxy", "vintage_limitation"):
        if len({getattr(row, field) for row in normalized}) != 1:
            raise EvaluationInputError(f"inconsistent per-row provenance: {field}")
    return tuple(sorted(normalized, key=lambda row: (row.origin, row.forecast_horizon_step)))


def parse_evaluation_csv(payload: str | bytes) -> tuple[EvaluationRow, ...]:
    """Parse the canonical P1-06 CSV without consulting any alternate actual series."""

    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != rolling_origin.OUTPUT_COLUMNS:
        raise EvaluationInputError("evaluation input columns differ from the P1-06 closed schema")
    return normalize_evaluation_rows(list(reader))


def _paired_values(actuals: Sequence[float], forecasts: Sequence[float]) -> tuple[tuple[float, float], ...]:
    if not actuals or len(actuals) != len(forecasts):
        raise EvaluationInputError("metric inputs must be non-empty and equal length")
    return tuple((_finite(actual, "actual"), _finite(forecast, "forecast")) for actual, forecast in zip(actuals, forecasts))


def mean_absolute_error(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    pairs = _paired_values(actuals, forecasts)
    return sum(abs(actual - forecast) for actual, forecast in pairs) / len(pairs)


def root_mean_squared_error(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    pairs = _paired_values(actuals, forecasts)
    return math.sqrt(sum((actual - forecast) ** 2 for actual, forecast in pairs) / len(pairs))


def interval_metrics(
    actuals: Sequence[float], lowers: Sequence[float], uppers: Sequence[float]
) -> tuple[float, float]:
    if not actuals or len(actuals) != len(lowers) or len(actuals) != len(uppers):
        raise EvaluationInputError("interval inputs must be non-empty and equal length")
    covered = 0
    widths = 0.0
    for actual, lower, upper in zip(actuals, lowers, uppers):
        y = _finite(actual, "actual")
        lo = _finite(lower, "interval lower")
        hi = _finite(upper, "interval upper")
        if lo > hi:
            raise EvaluationInputError("interval lower bound exceeds upper bound")
        covered += int(lo <= y <= hi)
        widths += hi - lo
    return covered / len(actuals), widths / len(actuals)


def pinball_loss(actual: float, forecast: float, quantile: float) -> float:
    q = _finite(quantile, "quantile")
    if not 0.0 < q < 1.0:
        raise EvaluationInputError("quantile must be strictly between zero and one")
    residual = _finite(actual, "actual") - _finite(forecast, "quantile forecast")
    return max(q * residual, (q - 1.0) * residual)


def mean_pinball_loss(actuals: Sequence[float], forecasts: Sequence[float], quantile: float) -> float:
    pairs = _paired_values(actuals, forecasts)
    return sum(pinball_loss(actual, forecast, quantile) for actual, forecast in pairs) / len(pairs)


def empirical_quantile_coverage(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    pairs = _paired_values(actuals, forecasts)
    return sum(int(actual <= forecast) for actual, forecast in pairs) / len(pairs)


def calculate_point_metrics(rows: Sequence[EvaluationRow]) -> dict[str, float]:
    if not rows:
        raise EvaluationInputError("point metric group must not be empty")
    actuals = [row.actual for row in rows]
    forecasts = [row.point_forecast for row in rows]
    return {"mae": mean_absolute_error(actuals, forecasts), "rmse": root_mean_squared_error(actuals, forecasts)}


def calculate_interval_metrics(rows: Sequence[EvaluationRow]) -> dict[str, object]:
    if not rows:
        raise EvaluationInputError("interval metric group must not be empty")
    coverage, width = interval_metrics(
        [row.actual for row in rows],
        [row.interval_80_lower for row in rows],
        [row.interval_80_upper for row in rows],
    )
    return {"level": INTERVAL_LEVEL, "empirical_coverage": coverage, "mean_width": width}


def calculate_quantile_metrics(rows: Sequence[EvaluationRow]) -> list[dict[str, float]]:
    if not rows:
        raise EvaluationInputError("quantile metric group must not be empty")
    actuals = [row.actual for row in rows]
    records: list[dict[str, float]] = []
    for index, quantile in enumerate(QUANTILES):
        forecasts = [row.quantile_forecasts[index] for row in rows]
        records.append(
            {
                "quantile": quantile,
                "mean_pinball_loss": mean_pinball_loss(actuals, forecasts, quantile),
                "empirical_coverage": empirical_quantile_coverage(actuals, forecasts),
            }
        )
    return records


def calculate_group_result(
    rows: Sequence[EvaluationRow], *, group_type: str, group_value: int | None
) -> dict[str, object]:
    if group_type not in {"aggregate", "horizon"}:
        raise EvaluationInputError("group_type must be aggregate or horizon")
    expected = SOURCE_ROW_COUNT if group_type == "aggregate" else ORIGIN_COUNT
    if len(rows) != expected:
        raise EvaluationInputError(f"{group_type} group has an invalid row count")
    if (group_type == "aggregate") != (group_value is None):
        raise EvaluationInputError("group value is inconsistent with group type")
    if group_type == "horizon" and group_value not in HORIZON_STEPS:
        raise EvaluationInputError("horizon group value is invalid")
    return {
        "group_type": group_type,
        "group_value": group_value,
        "row_count": len(rows),
        "point": calculate_point_metrics(rows),
        "interval": calculate_interval_metrics(rows),
        "quantiles": calculate_quantile_metrics(rows),
    }


def calculate_evaluation_results(rows: Sequence[EvaluationRow]) -> dict[str, object]:
    """Return aggregate then ordered horizon 1/2/3 results."""

    normalized = normalize_evaluation_rows([_row_as_source_record(row) for row in rows])
    aggregate = calculate_group_result(normalized, group_type="aggregate", group_value=None)
    per_horizon = [
        calculate_group_result(
            [row for row in normalized if row.forecast_horizon_step == horizon],
            group_type="horizon",
            group_value=horizon,
        )
        for horizon in HORIZON_STEPS
    ]
    return {"aggregate": aggregate, "per_horizon": per_horizon}


def _row_as_source_record(row: EvaluationRow) -> dict[str, object]:
    record: dict[str, object] = {column: "unused" for column in rolling_origin.OUTPUT_COLUMNS}
    record.update(
        {
            "origin": row.origin,
            "forecast_horizon_step": row.forecast_horizon_step,
            "actual": row.actual,
            "point_forecast": row.point_forecast,
            "interval_80_lower": row.interval_80_lower,
            "interval_80_upper": row.interval_80_upper,
            "reference_model_id": row.reference_model_id,
            "publication_label": row.publication_label,
            "publication_proxy": row.publication_proxy,
            "vintage_limitation": row.vintage_limitation,
        }
    )
    record.update({column: row.quantile_forecasts[index] for index, column in enumerate(QUANTILE_COLUMNS)})
    return record


def evaluation_contract() -> dict[str, object]:
    return {
        "source_row_count": SOURCE_ROW_COUNT,
        "origin_count": ORIGIN_COUNT,
        "horizon_steps": list(HORIZON_STEPS),
        "interval_level": INTERVAL_LEVEL,
        "quantiles": list(QUANTILES),
        "point_metrics": ["mae", "rmse"],
        "interval_metrics": ["empirical_coverage", "mean_width"],
        "quantile_metrics": ["mean_pinball_loss", "empirical_coverage"],
        "interval_coverage_rule": "lower <= actual <= upper",
        "quantile_coverage_rule": "actual <= quantile_forecast",
        "group_order": list(GROUP_ORDER),
    }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise PublicationValidationError(f"artifact is unreadable: {path}") from exc


def _repo_path(root: Path, relative: Path) -> Path:
    return root.resolve() / relative


def _prior_marker_hash(root: Path) -> str | None:
    path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
    return _sha256_path(path) if path.is_file() else None


def _run_id(now: datetime) -> str:
    return f"P1-07-{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _timestamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_checks(value: bool = False) -> dict[str, bool]:
    return {name: value for name in CHECK_NAMES}


def _diagnostic(classification: str, stage: str, exc: BaseException) -> dict[str, object]:
    reason = f"evaluation {stage} failed: {type(exc).__name__}"
    return {
        "classification": classification,
        "stage": stage,
        "sanitized_reason": reason,
        "exception_class": type(exc).__name__,
    }


def build_source_binding(
    repo_root: Path, source_evidence: Mapping[str, object], rows: Sequence[EvaluationRow]
) -> dict[str, object]:
    """Build the sole authoritative P1-06 provenance block from validated facts."""

    if not rows:
        raise EvaluationInputError("source rows are required for binding")
    protocol = source_evidence.get("publication_protocol")
    if not isinstance(protocol, Mapping) or protocol.get("marker_state") != "pass_final":
        raise EvaluationInputError("P1-06 marker state must be pass_final")
    model_id = source_evidence.get("reference_model_id")
    run_id = source_evidence.get("run_id")
    if rows[0].reference_model_id != model_id:
        raise EvaluationInputError("P1-06 reference model differs from source rows")
    binding: dict[str, object] = {
        "p1_06_evidence_path": str(P1_06_EVIDENCE_RELATIVE_PATH),
        "p1_06_evidence_sha256": _sha256_path(_repo_path(repo_root, P1_06_EVIDENCE_RELATIVE_PATH)),
        "p1_06_forecast_csv_path": str(FORECASTS_RELATIVE_PATH),
        "p1_06_forecast_csv_sha256": _sha256_path(_repo_path(repo_root, FORECASTS_RELATIVE_PATH)),
        "p1_06_run_id": _nonempty(run_id, "P1-06 run ID"),
        "p1_06_reference_model_id": _nonempty(model_id, "P1-06 reference model ID"),
        "p1_06_publication_label": rows[0].publication_label,
        "p1_06_publication_proxy": rows[0].publication_proxy,
        "p1_06_vintage_limitation": rows[0].vintage_limitation,
        "p1_06_marker_state": "pass_final",
    }
    if protocol.get("csv_sha256") != binding["p1_06_forecast_csv_sha256"]:
        raise EvaluationInputError("P1-06 forecast CSV hash differs from its authenticated marker")
    policy = source_evidence.get("publication_policy")
    if not isinstance(policy, Mapping):
        raise EvaluationInputError("P1-06 publication policy is missing")
    expected = {
        "p1_06_publication_label": policy.get("evaluation_label"),
        "p1_06_publication_proxy": policy.get("availability_proxy"),
        "p1_06_vintage_limitation": policy.get("limitation"),
    }
    for key, value in expected.items():
        if binding[key] != value:
            raise EvaluationInputError(f"P1-06 policy drift: {key}")
    return binding


def build_evaluation_evidence(
    *,
    source_binding: Mapping[str, object] | None = None,
    results: Mapping[str, object] | None = None,
    marker_state: str = "pass_final",
    classification: str = "pass",
    diagnostics: Sequence[Mapping[str, object]] = (),
    errors: Sequence[str] = (),
    prior_marker_sha256: str | None = None,
    markdown_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    checks = _default_checks(marker_state == "pass_final")
    evidence: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": _run_id(current),
        "timestamp_utc": _timestamp(current),
        "classification": classification,
        "source_binding": dict(source_binding) if source_binding is not None else None,
        "evaluation_contract": evaluation_contract(),
        "results": dict(results) if results is not None else None,
        "publication_protocol": {
            "marker_path": str(EVIDENCE_RELATIVE_PATH),
            "marker_state": marker_state,
            "prior_marker_sha256": prior_marker_sha256,
            "evaluation_markdown_sha256": markdown_sha256,
            "write_order": list(WRITE_ORDER),
            "commit_marker_valid": marker_state == "pass_final",
        },
        "checks": checks,
        "errors": list(errors),
        "non_pass_diagnostics": [dict(item) for item in diagnostics],
        "artifact_paths": list(ARTIFACT_PATHS),
    }
    validate_evidence_schema(evidence)
    return evidence


def _is_metric_float(value: object) -> bool:
    return type(value) is float and math.isfinite(cast(float, value))


def _exact_keys(value: object, keys: Sequence[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PublicationValidationError(f"{label} keys differ from the closed schema")
    return value


def _valid_hash(value: object, *, nullable: bool = False) -> bool:
    return (nullable and value is None) or (isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None)


def _validate_group(group_value: object, expected_horizon: int | None) -> None:
    group = _exact_keys(group_value, GROUP_KEYS, "group result")
    expected_type = "aggregate" if expected_horizon is None else "horizon"
    expected_count = SOURCE_ROW_COUNT if expected_horizon is None else ORIGIN_COUNT
    if (
        group.get("group_type") != expected_type
        or group.get("group_value") != expected_horizon
        or (expected_horizon is not None and type(group.get("group_value")) is not int)
        or type(group.get("row_count")) is not int
        or group.get("row_count") != expected_count
    ):
        raise PublicationValidationError("group identity or row count is invalid")
    point = _exact_keys(group.get("point"), POINT_KEYS, "point result")
    for key in POINT_KEYS:
        if not _is_metric_float(point.get(key)) or cast(float, point[key]) < 0:
            raise PublicationValidationError(f"point metric is invalid: {key}")
    interval = _exact_keys(group.get("interval"), INTERVAL_KEYS, "interval result")
    if type(interval.get("level")) is not int or interval.get("level") != INTERVAL_LEVEL:
        raise PublicationValidationError("interval level is invalid")
    coverage = interval.get("empirical_coverage")
    width = interval.get("mean_width")
    if (
        not _is_metric_float(coverage)
        or not 0 <= cast(float, coverage) <= 1
        or not _is_metric_float(width)
        or cast(float, width) < 0
    ):
        raise PublicationValidationError("interval metrics are invalid")
    quantiles = group.get("quantiles")
    if not isinstance(quantiles, list) or len(quantiles) != len(QUANTILES):
        raise PublicationValidationError("quantile results are incomplete")
    for expected, raw in zip(QUANTILES, quantiles):
        record = _exact_keys(raw, QUANTILE_RESULT_KEYS, "quantile result")
        if type(record.get("quantile")) is not float or record.get("quantile") != expected:
            raise PublicationValidationError("quantile result order is invalid")
        loss = record.get("mean_pinball_loss")
        qcoverage = record.get("empirical_coverage")
        if (
            not _is_metric_float(loss)
            or cast(float, loss) < 0
            or not _is_metric_float(qcoverage)
            or not 0 <= cast(float, qcoverage) <= 1
        ):
            raise PublicationValidationError("quantile metrics are invalid")


def validate_evidence_schema(evidence: Mapping[str, object]) -> None:
    """Recursively validate the state-conditioned, closed evidence schema."""

    _exact_keys(evidence, TOP_LEVEL_KEYS, "evaluation evidence")
    if type(evidence.get("schema_version")) is not int or evidence.get("schema_version") != 1 or evidence.get("task_id") != TASK_ID:
        raise PublicationValidationError("evaluation evidence identity is invalid")
    if not isinstance(evidence.get("run_id"), str) or not evidence["run_id"]:
        raise PublicationValidationError("evaluation run ID is invalid")
    if not isinstance(evidence.get("timestamp_utc"), str) or UTC_PATTERN.fullmatch(str(evidence["timestamp_utc"])) is None:
        raise PublicationValidationError("evaluation timestamp is invalid")
    try:
        parsed_timestamp = datetime.fromisoformat(str(evidence["timestamp_utc"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationValidationError("evaluation timestamp is invalid") from exc
    if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() != timezone.utc.utcoffset(parsed_timestamp):
        raise PublicationValidationError("evaluation timestamp must be UTC")
    classification = evidence.get("classification")
    if classification not in CLASSIFICATIONS:
        raise PublicationValidationError("evaluation classification is invalid")
    contract = _exact_keys(evidence.get("evaluation_contract"), CONTRACT_KEYS, "evaluation contract")
    if dict(contract) != evaluation_contract():
        raise PublicationValidationError("evaluation contract differs from the frozen contract")
    if any(type(contract.get(key)) is not int for key in ("source_row_count", "origin_count", "interval_level")):
        raise PublicationValidationError("evaluation contract integer fields are invalid")
    if (
        not isinstance(contract.get("horizon_steps"), list)
        or any(type(item) is not int for item in cast(list[object], contract["horizon_steps"]))
        or not isinstance(contract.get("quantiles"), list)
        or any(type(item) is not float for item in cast(list[object], contract["quantiles"]))
    ):
        raise PublicationValidationError("evaluation contract list types are invalid")
    protocol = _exact_keys(evidence.get("publication_protocol"), PROTOCOL_KEYS, "publication protocol")
    state = protocol.get("marker_state")
    if state not in MARKER_STATES or protocol.get("marker_path") != str(EVIDENCE_RELATIVE_PATH):
        raise PublicationValidationError("publication marker envelope is invalid")
    if protocol.get("write_order") != list(WRITE_ORDER) or not _valid_hash(protocol.get("prior_marker_sha256"), nullable=True):
        raise PublicationValidationError("publication protocol order or prior hash is invalid")
    checks = _exact_keys(evidence.get("checks"), CHECK_NAMES, "checks")
    if any(type(value) is not bool for value in checks.values()):
        raise PublicationValidationError("all checks must be booleans")
    errors = evidence.get("errors")
    diagnostics = evidence.get("non_pass_diagnostics")
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        raise PublicationValidationError("errors must be strings")
    if not isinstance(diagnostics, list):
        raise PublicationValidationError("non-pass diagnostics must be an array")
    for raw in diagnostics:
        diagnostic = _exact_keys(raw, DIAGNOSTIC_KEYS, "non-pass diagnostic")
        if diagnostic.get("classification") != classification or not isinstance(diagnostic.get("stage"), str) or not diagnostic.get("stage") or not isinstance(diagnostic.get("sanitized_reason"), str) or not diagnostic.get("sanitized_reason"):
            raise PublicationValidationError("non-pass diagnostic is invalid")
        if diagnostic.get("exception_class") is not None and not isinstance(diagnostic.get("exception_class"), str):
            raise PublicationValidationError("diagnostic exception class is invalid")
    if evidence.get("artifact_paths") != list(ARTIFACT_PATHS):
        raise PublicationValidationError("artifact paths differ from the closed schema")
    binding_value = evidence.get("source_binding")
    if binding_value is not None:
        binding = _exact_keys(binding_value, SOURCE_BINDING_KEYS, "source binding")
        for key, value in binding.items():
            if key.endswith("sha256"):
                if not _valid_hash(value):
                    raise PublicationValidationError(f"source binding hash is invalid: {key}")
            elif not isinstance(value, str) or not value:
                raise PublicationValidationError(f"source binding field is invalid: {key}")
        if binding.get("p1_06_marker_state") != "pass_final":
            raise PublicationValidationError("P1-06 marker state must be pass_final")
        if binding.get("p1_06_evidence_path") != str(P1_06_EVIDENCE_RELATIVE_PATH):
            raise PublicationValidationError("P1-06 evidence path is invalid")
        if binding.get("p1_06_forecast_csv_path") != str(FORECASTS_RELATIVE_PATH):
            raise PublicationValidationError("P1-06 forecast CSV path is invalid")
    results_value = evidence.get("results")
    if results_value is not None:
        results = _exact_keys(results_value, RESULTS_KEYS, "evaluation results")
        _validate_group(results.get("aggregate"), None)
        per_horizon = results.get("per_horizon")
        if not isinstance(per_horizon, list) or len(per_horizon) != 3:
            raise PublicationValidationError("per-horizon results are incomplete")
        for horizon, group in zip(HORIZON_STEPS, per_horizon):
            _validate_group(group, horizon)
    markdown_hash = protocol.get("evaluation_markdown_sha256")
    if state == "pass_final":
        if classification != "pass" or binding_value is None or results_value is None:
            raise PublicationValidationError("pass_final requires complete passing evidence")
        if errors or diagnostics or any(value is not True for value in checks.values()):
            raise PublicationValidationError("pass_final checks and diagnostics are inconsistent")
        if not _valid_hash(markdown_hash) or protocol.get("commit_marker_valid") is not True:
            raise PublicationValidationError("pass_final publication integrity is invalid")
    elif state == "invalid_in_progress":
        if classification != "blocked" or results_value is not None or markdown_hash is not None or protocol.get("commit_marker_valid") is not False or not diagnostics:
            raise PublicationValidationError("invalid_in_progress state is inconsistent")
        if checks.get("publication_valid") or checks.get("roadmap_update_eligible"):
            raise PublicationValidationError("invalid_in_progress cannot be publication-valid")
    else:
        if classification not in {"blocked", "fail"} or results_value is not None or protocol.get("commit_marker_valid") is not False or not diagnostics:
            raise PublicationValidationError("invalid_final state is inconsistent")
        if markdown_hash is not None and not _valid_hash(markdown_hash):
            raise PublicationValidationError("invalid_final Markdown hash is invalid")
        if checks.get("publication_valid") or checks.get("roadmap_update_eligible"):
            raise PublicationValidationError("invalid_final cannot be publication-valid")


def _format_metric(value: object) -> str:
    return format(float(cast(int | float, value)), ".17g")


def render_evaluation_markdown(evidence: Mapping[str, object]) -> str:
    """Render the canonical human-readable evaluation from evidence."""

    results = evidence.get("results")
    binding = evidence.get("source_binding")
    lines = [
        "# Phase 1 Point and Probabilistic Evaluation",
        "",
        f"- Classification: `{evidence.get('classification')}`.",
        "- Numerical forecast quality is reported as evidence; it is not a performance verdict or pass/fail gate.",
    ]
    if isinstance(binding, Mapping):
        lines.extend(
            [
                f"- P1-06 run ID: `{binding.get('p1_06_run_id')}`.",
                f"- Reference model: `{binding.get('p1_06_reference_model_id')}`.",
                f"- P1-06 evidence SHA-256: `{binding.get('p1_06_evidence_sha256')}`.",
                f"- Forecast CSV SHA-256: `{binding.get('p1_06_forecast_csv_sha256')}`.",
                f"- Publication label: `{binding.get('p1_06_publication_label')}`.",
                f"- Publication proxy: `{binding.get('p1_06_publication_proxy')}`.",
                f"- Vintage limitation: {binding.get('p1_06_vintage_limitation')}",
            ]
        )
    if isinstance(results, Mapping):
        groups: list[Mapping[str, object]] = []
        aggregate = results.get("aggregate")
        per_horizon = results.get("per_horizon")
        if isinstance(aggregate, Mapping):
            groups.append(aggregate)
        if isinstance(per_horizon, list):
            groups.extend(item for item in per_horizon if isinstance(item, Mapping))
        for group in groups:
            title = "Aggregate" if group.get("group_type") == "aggregate" else f"Horizon {group.get('group_value')}"
            point = group.get("point")
            interval = group.get("interval")
            quantile_results = group.get("quantiles")
            lines.extend(["", f"## {title}", "", f"Rows: `{group.get('row_count')}`"])
            if isinstance(point, Mapping):
                lines.extend([f"- MAE: `{_format_metric(point.get('mae'))}`", f"- RMSE: `{_format_metric(point.get('rmse'))}`"])
            if isinstance(interval, Mapping):
                lines.extend(
                    [
                        f"- 80% empirical interval coverage: `{_format_metric(interval.get('empirical_coverage'))}`",
                        f"- 80% mean interval width: `{_format_metric(interval.get('mean_width'))}`",
                    ]
                )
            lines.extend(["", "| Quantile | Mean pinball loss | Empirical coverage |", "| --- | ---: | ---: |"])
            if isinstance(quantile_results, list):
                for record in quantile_results:
                    if isinstance(record, Mapping):
                        lines.append(
                            f"| {_format_metric(record.get('quantile'))} | {_format_metric(record.get('mean_pinball_loss'))} | {_format_metric(record.get('empirical_coverage'))} |"
                        )
    lines.extend(["", "Machine-readable evidence: `docs/findings/phase1/evidence/evaluation.json`", ""])
    return "\n".join(lines)


def _stage_bytes(destination: Path, payload: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _replace_json_marker(root: Path, evidence: Mapping[str, object], replace_file: object = os.replace) -> None:
    destination = _repo_path(root, EVIDENCE_RELATIVE_PATH)
    payload = (json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    staged = _stage_bytes(destination, payload)
    try:
        replace_file(staged, destination)  # type: ignore[operator]
    finally:
        staged.unlink(missing_ok=True)


def begin_evaluation_attempt(
    repo_root: Path | None = None, *, now: datetime | None = None, replace_file: object = os.replace
) -> dict[str, object]:
    root = (repo_root or Path.cwd()).resolve()
    diagnostic = {"classification": "blocked", "stage": "initialization", "sanitized_reason": "evaluation attempt is in progress", "exception_class": None}
    evidence = build_evaluation_evidence(
        marker_state="invalid_in_progress",
        classification="blocked",
        diagnostics=(diagnostic,),
        errors=("evaluation attempt is in progress",),
        prior_marker_sha256=_prior_marker_hash(root),
        now=now,
    )
    _replace_json_marker(root, evidence, replace_file)
    return evidence


def _load_validated_source(root: Path) -> tuple[Mapping[str, object], tuple[EvaluationRow, ...], dict[str, object]]:
    source = rolling_origin.validate_rolling_origin_consumer_gate(root)
    csv_path = _repo_path(root, FORECASTS_RELATIVE_PATH)
    rows = parse_evaluation_csv(csv_path.read_bytes())
    binding = build_source_binding(root, source, rows)
    return source, rows, binding


def _invalid_final(
    root: Path,
    exc: BaseException,
    *,
    classification: str,
    stage: str,
    source_binding: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    evidence = build_evaluation_evidence(
        source_binding=source_binding,
        marker_state="invalid_final",
        classification=classification,
        diagnostics=(_diagnostic(classification, stage, exc),),
        errors=(f"evaluation {stage} failed",),
        prior_marker_sha256=_prior_marker_hash(root),
        now=now,
    )
    _replace_json_marker(root, evidence)
    return evidence


def publish_evaluation_bundle(
    repo_root: Path | None = None,
    *,
    now: datetime | None = None,
    replace_file: object = os.replace,
) -> dict[str, object]:
    """Evaluate the validated source and replace Markdown before the pass marker."""

    root = (repo_root or Path.cwd()).resolve()
    begin_evaluation_attempt(root, now=now, replace_file=replace_file)
    binding: dict[str, object] | None = None
    stage = "source"
    try:
        _, rows, binding = _load_validated_source(root)
        stage = "calculation"
        results = calculate_evaluation_results(rows)
        prior = _prior_marker_hash(root)
        draft = build_evaluation_evidence(
            source_binding=binding,
            results=results,
            prior_marker_sha256=prior,
            markdown_sha256="0" * 64,
            now=now,
        )
        markdown_bytes = render_evaluation_markdown(draft).encode("utf-8")
        evidence = build_evaluation_evidence(
            source_binding=binding,
            results=results,
            prior_marker_sha256=prior,
            markdown_sha256=_sha256_bytes(markdown_bytes),
            now=now,
        )
        evidence_bytes = (json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        destinations = (
            (_repo_path(root, FINDING_RELATIVE_PATH), markdown_bytes),
            (_repo_path(root, EVIDENCE_RELATIVE_PATH), evidence_bytes),
        )
        stage = "publication"
        staged: list[tuple[Path, Path]] = []
        try:
            for destination, payload in destinations:
                staged.append((_stage_bytes(destination, payload), destination))
            for temporary, destination in staged:
                replace_file(temporary, destination)  # type: ignore[operator]
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)
        return validate_evaluation_publication(root)
    except BaseException as exc:
        classification = "blocked" if (
            (stage == "source" and isinstance(exc, (OSError, ModuleNotFoundError)))
            or not _repo_path(root, P1_06_EVIDENCE_RELATIVE_PATH).is_file()
            or not _repo_path(root, FORECASTS_RELATIVE_PATH).is_file()
        ) else "fail"
        try:
            _invalid_final(root, exc, classification=classification, stage=stage, source_binding=binding, now=now)
        except BaseException:
            pass
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise PublicationError("evaluation publication failed and marker was invalidated") from exc


def _compare_source_binding(root: Path, stored: Mapping[str, object]) -> tuple[EvaluationRow, ...]:
    _, rows, current = _load_validated_source(root)
    if dict(stored) != current:
        raise PublicationValidationError("stored P1-06 source binding is stale")
    return rows


def validate_evaluation_publication(repo_root: Path | None = None) -> dict[str, object]:
    """Revalidate source, schema, metrics, canonical Markdown, and pass marker."""

    root = (repo_root or Path.cwd()).resolve()
    marker_path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
    try:
        evidence_value = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationValidationError("evaluation evidence marker is unavailable") from exc
    if not isinstance(evidence_value, dict):
        raise PublicationValidationError("evaluation evidence marker must be an object")
    evidence: dict[str, object] = evidence_value
    validate_evidence_schema(evidence)
    protocol = evidence["publication_protocol"]
    assert isinstance(protocol, Mapping)
    if protocol.get("marker_state") != "pass_final":
        raise PublicationValidationError("evaluation payload is not consumable without pass_final")
    binding = evidence["source_binding"]
    assert isinstance(binding, Mapping)
    rows = _compare_source_binding(root, binding)
    expected_results = calculate_evaluation_results(rows)
    if evidence.get("results") != expected_results:
        raise PublicationValidationError("stored metrics differ from canonical recomputation")
    markdown_path = _repo_path(root, FINDING_RELATIVE_PATH)
    try:
        markdown_bytes = markdown_path.read_bytes()
        markdown = markdown_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PublicationValidationError("evaluation Markdown is unavailable") from exc
    if _sha256_bytes(markdown_bytes) != protocol.get("evaluation_markdown_sha256"):
        raise PublicationValidationError("evaluation Markdown hash differs from the pass marker")
    if markdown != render_evaluation_markdown(evidence):
        raise PublicationValidationError("evaluation Markdown differs from canonical evidence")
    return evidence


def update_evaluation_roadmap(repo_root: Path | None = None) -> None:
    root = (repo_root or Path.cwd()).resolve()
    validate_evaluation_publication(root)
    path = _repo_path(root, ROADMAP_RELATIVE_PATH)
    original = path.read_text(encoding="utf-8")
    matches = P1_07_ROADMAP_PATTERN.findall(original)
    if matches not in ([" "], ["x"]):
        raise PublicationError("roadmap must contain exactly one P1-07 checkbox")
    updated = P1_07_ROADMAP_PATTERN.sub("- [x] **P1-07", original, count=1)
    if updated != original:
        staged = _stage_bytes(path, updated.encode("utf-8"))
        try:
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)


def check_evaluation_roadmap(repo_root: Path | None = None) -> bool:
    root = (repo_root or Path.cwd()).resolve()
    validate_evaluation_publication(root)
    matches = P1_07_ROADMAP_PATTERN.findall(_repo_path(root, ROADMAP_RELATIVE_PATH).read_text(encoding="utf-8"))
    return matches == ["x"]


# Narrow aliases matching the task vocabulary used by downstream callers.
evaluate_rows = calculate_evaluation_results
publish_evaluation = publish_evaluation_bundle
validate_evaluation_consumer_gate = validate_evaluation_publication
calculate_mae = mean_absolute_error
calculate_rmse = root_mean_squared_error
calculate_pinball_loss = pinball_loss
calculate_quantile_coverage = empirical_quantile_coverage
compute_point_metrics = calculate_point_metrics
compute_interval_metrics = calculate_interval_metrics
compute_quantile_metrics = calculate_quantile_metrics


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--publish", action="store_true")
    actions.add_argument("--validate-publication", action="store_true")
    actions.add_argument("--update-roadmap", action="store_true")
    actions.add_argument("--check-roadmap", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.repo_root.resolve()
    try:
        if arguments.publish:
            publish_evaluation_bundle(root)
        elif arguments.validate_publication:
            validate_evaluation_publication(root)
        elif arguments.update_roadmap:
            update_evaluation_roadmap(root)
        elif arguments.check_roadmap and not check_evaluation_roadmap(root):
            raise PublicationError("P1-07 roadmap is inconsistent with validated publication")
    except (EvaluationError, rolling_origin.RollingOriginError, OSError) as exc:
        print(f"evaluation: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
