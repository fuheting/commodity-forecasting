"""Deterministic, history-only monthly rolling-origin forecast orchestration."""

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
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .contracts import PUBLICATION_POLICY
from .target_pipeline import MODEL_READY_RELATIVE_PATH, TargetRow, parse_target_csv

P1_05_EVIDENCE_SHA256 = "d87ea4c8d3c0cc4fb2e7fd24174cc24b329fdc58242fc018eb4965db4b11fcf3"
P1_05_RUN_ID = "P1-05-20260816T064548Z"
REFERENCE_MODEL_ID = "autogluon/chronos-2-small"
CONTEXT_MONTHS = 60
FORECAST_MONTHS = 3
ORIGIN_COUNT = 3
ADAPTER_PAYLOAD_COLUMNS = ("unique_id", "ds", "y")
QUANTILES = tuple(round(index / 10, 1) for index in range(1, 10))
EXPECTED_ORIGINS = (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1))
EXPECTED_CUTOFFS = (date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1))
FORECASTS_RELATIVE_PATH = Path(
    "data/model_ready/world_bank_pink_sheet_monthly_arabica/rolling_origin/forecasts.csv"
)
FINDING_RELATIVE_PATH = Path("docs/findings/phase1/rolling_origin.md")
EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/rolling_origin.json")
P1_05_RELATIVE_PATH = Path("docs/findings/phase1/evidence/runtime_compatibility.json")
TARGET_RELATIVE_PATH = MODEL_READY_RELATIVE_PATH
ROADMAP_RELATIVE_PATH = Path("docs/roadmap.md")
ARTIFACT_PATHS = tuple(
    str(path) for path in (FORECASTS_RELATIVE_PATH, FINDING_RELATIVE_PATH, EVIDENCE_RELATIVE_PATH)
)
WRITE_ORDER = ("forecasts.csv", "rolling_origin.md", "rolling_origin.json")
MARKER_STATES = ("invalid_in_progress", "invalid_final", "pass_final")
CLASSIFICATIONS = ("pass", "fail", "blocked", "unsupported")
TOP_LEVEL_KEYS = (
    "schema_version", "task_id", "run_id", "timestamp_utc", "classification",
    "non_pass_diagnostics", "reference_model_id", "p1_05_run_id",
    "p1_05_evidence_sha256", "p1_05_selection", "target_artifact_sha256",
    "publication_policy", "publication_protocol", "schedule", "request_strategy",
    "execution_receipt", "origin_records", "checks", "errors", "artifact_paths",
)
PROTOCOL_KEYS = (
    "marker_path", "marker_state", "prior_marker_sha256", "csv_sha256",
    "markdown_sha256", "write_order", "commit_marker_valid",
    "replacements_fsynchronized",
)
CHECK_NAMES = (
    "p1_05_binding_valid",
    "schedule_valid",
    "window_leakage_free",
    "forecast_calls_serial",
    "csv_schema_valid",
    "publication_protocol_valid",
    "probabilistic_outputs_supported",
    "roadmap_eligible",
)

OUTPUT_COLUMNS = (
    "origin",
    "cutoff",
    "historic_context_start",
    "historic_context_end",
    "forecast_month",
    "forecast_horizon_step",
    "actual",
    "point_forecast",
    "interval_80_lower",
    "interval_80_upper",
    "quantile_0_1",
    "quantile_0_2",
    "quantile_0_3",
    "quantile_0_4",
    "quantile_0_5",
    "quantile_0_6",
    "quantile_0_7",
    "quantile_0_8",
    "quantile_0_9",
    "reference_model_id",
    "p1_05_evidence_sha256",
    "publication_label",
    "publication_proxy",
    "vintage_limitation",
)


class RollingOriginError(RuntimeError):
    """Raised when the deterministic rolling-origin contract is violated."""


class P105BindingError(RollingOriginError):
    """Raised when the frozen P1-05 evidence binding does not match."""


class ScheduleContractError(RollingOriginError):
    """Raised when monthly target rows cannot form the approved schedule."""


class ForecastResponseError(RollingOriginError):
    """Raised when a public adapter response violates the output contract."""


class LiveDependencyError(RollingOriginError):
    """Raised when the pinned live adapter cannot load its runtime dependencies."""


AdapterRow = dict[str, str]


@runtime_checkable
class ForecastOnlyAdapter(Protocol):
    """Public, trap-friendly boundary used by the deterministic core."""

    def forecast(
        self,
        payload: Sequence[Mapping[str, str]],
        *,
        h: int,
        level: Sequence[int] | None = None,
        quantiles: Sequence[float] | None = None,
    ) -> object:
        """Return forecasts without fitting, training, or updating model state."""


@dataclass(frozen=True)
class OriginWindow:
    origin: date
    cutoff: date
    historic_context_start: date
    historic_context_end: date
    forecast_start: date
    forecast_end: date
    context_rows: tuple[TargetRow, ...]
    forecast_months: tuple[date, ...]

    def as_span_record(self) -> dict[str, object]:
        return {
            "origin": self.origin.isoformat(),
            "cutoff": self.cutoff.isoformat(),
            "historic_context_start": self.historic_context_start.isoformat(),
            "historic_context_end": self.historic_context_end.isoformat(),
            "forecast_start": self.forecast_start.isoformat(),
            "forecast_end": self.forecast_end.isoformat(),
            "row_count": len(self.context_rows),
            "forecast_row_count": len(self.forecast_months),
        }


@dataclass(frozen=True)
class RollingOriginSchedule:
    target_end: date
    windows: tuple[OriginWindow, ...]

    @property
    def origins(self) -> tuple[date, ...]:
        return tuple(window.origin for window in self.windows)

    @property
    def cutoffs(self) -> tuple[date, ...]:
        return tuple(window.cutoff for window in self.windows)

    def as_record(self) -> dict[str, object]:
        return {
            "origin_count": ORIGIN_COUNT,
            "step_months": 1,
            "historic_context_months": CONTEXT_MONTHS,
            "forecast_months": FORECAST_MONTHS,
            "origin_months": [value.isoformat() for value in self.origins],
            "cutoff_months": [value.isoformat() for value in self.cutoffs],
            "historic_context_spans": [
                {
                    "origin": window.origin.isoformat(),
                    "start": window.historic_context_start.isoformat(),
                    "end": window.historic_context_end.isoformat(),
                    "month_count": CONTEXT_MONTHS,
                }
                for window in self.windows
            ],
            "forecast_spans": [
                {
                    "origin": window.origin.isoformat(),
                    "start": window.forecast_start.isoformat(),
                    "end": window.forecast_end.isoformat(),
                    "month_count": FORECAST_MONTHS,
                }
                for window in self.windows
            ],
        }


@dataclass(frozen=True)
class ForecastRow:
    values: tuple[object, ...]

    def as_dict(self) -> dict[str, object]:
        return dict(zip(OUTPUT_COLUMNS, self.values, strict=True))


@dataclass(frozen=True)
class OriginRecord:
    window: OriginWindow
    input_digest: str
    rows: tuple[ForecastRow, ...]


@dataclass(frozen=True)
class RollingOriginResult:
    schedule: RollingOriginSchedule
    origins: tuple[OriginRecord, ...]

    @property
    def rows(self) -> tuple[ForecastRow, ...]:
        return tuple(row for origin in self.origins for row in origin.rows)


@dataclass(frozen=True)
class ForecastCallReceipt:
    origin: str
    request_kind: str
    input_digest: str
    output_sha256: str
    output_rows: int
    status: str = "success"

    def as_record(self) -> dict[str, object]:
        return {
            "origin": self.origin,
            "request_kind": self.request_kind,
            "input_digest": self.input_digest,
            "output_sha256": self.output_sha256,
            "output_rows": self.output_rows,
            "status": self.status,
        }


@dataclass(frozen=True)
class LiveExecutionReceipt:
    runner_kind: str
    execution_mode: str
    adapter_class: str
    model_id: str
    model_alias: str
    package_versions: tuple[tuple[str, str], ...]
    network_policy: str
    cache_policy: str
    call_receipts: tuple[ForecastCallReceipt, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "runner_kind": self.runner_kind,
            "execution_mode": self.execution_mode,
            "adapter_class": self.adapter_class,
            "model_id": self.model_id,
            "model_alias": self.model_alias,
            "package_versions": dict(self.package_versions),
            "network_policy": self.network_policy,
            "cache_policy": self.cache_policy,
            "call_receipts": [receipt.as_record() for receipt in self.call_receipts],
        }


@dataclass(frozen=True)
class P105Binding:
    evidence_sha256: str
    selection: Mapping[str, object]


@dataclass(frozen=True)
class _ValidatedResponses:
    point: tuple[float, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    quantiles: tuple[tuple[float, ...], ...]


def add_months(value: date, offset: int) -> date:
    """Return a month-start shifted by calendar months."""

    if value.day != 1:
        raise ScheduleContractError("monthly timestamps must be month-start dates")
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def _validate_target_rows(rows: Sequence[TargetRow]) -> tuple[TargetRow, ...]:
    normalized = tuple(rows)
    if not normalized:
        raise ScheduleContractError("monthly target must not be empty")
    unique_ids = {row.unique_id for row in normalized}
    if len(unique_ids) != 1:
        raise ScheduleContractError("monthly target must contain exactly one unique_id")
    dates = tuple(row.ds for row in normalized)
    if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
        raise ScheduleContractError("monthly target timestamps must be unique and ordered")
    if any(current != add_months(previous, 1) for previous, current in zip(dates, dates[1:])):
        raise ScheduleContractError("monthly target timestamps must be contiguous")
    for row in normalized:
        try:
            numeric = float(row.y)
        except (TypeError, ValueError) as exc:
            raise ScheduleContractError("monthly target values must be numeric") from exc
        if not math.isfinite(numeric):
            raise ScheduleContractError("monthly target values must be finite")
    return normalized


def build_rolling_origin_schedule(rows: Sequence[TargetRow]) -> RollingOriginSchedule:
    """Derive the exact three-origin schedule from the target endpoint."""

    target_rows = _validate_target_rows(rows)
    by_date = {row.ds: row for row in target_rows}
    target_end = target_rows[-1].ds
    latest_origin = add_months(target_end, -(FORECAST_MONTHS - 1))
    origins = tuple(add_months(latest_origin, offset) for offset in range(-2, 1))
    windows: list[OriginWindow] = []
    for origin in origins:
        cutoff = add_months(origin, -1)
        context_start = add_months(cutoff, -(CONTEXT_MONTHS - 1))
        context_dates = tuple(add_months(context_start, offset) for offset in range(CONTEXT_MONTHS))
        forecast_dates = tuple(add_months(origin, offset) for offset in range(FORECAST_MONTHS))
        try:
            context = tuple(by_date[value] for value in context_dates)
            for value in forecast_dates:
                by_date[value]
        except KeyError as exc:
            raise ScheduleContractError(f"target is missing required month {exc.args[0]}") from exc
        windows.append(
            OriginWindow(
                origin=origin,
                cutoff=cutoff,
                historic_context_start=context_start,
                historic_context_end=cutoff,
                forecast_start=forecast_dates[0],
                forecast_end=forecast_dates[-1],
                context_rows=context,
                forecast_months=forecast_dates,
            )
        )
    schedule = RollingOriginSchedule(target_end=target_end, windows=tuple(windows))
    validate_rolling_origin_schedule(schedule)
    return schedule


def validate_rolling_origin_schedule(schedule: RollingOriginSchedule) -> None:
    """Fail closed unless a schedule matches the approved P1-06 contract."""

    if len(schedule.windows) != ORIGIN_COUNT:
        raise ScheduleContractError("schedule must contain exactly three origins")
    if schedule.origins != EXPECTED_ORIGINS or schedule.cutoffs != EXPECTED_CUTOFFS:
        raise ScheduleContractError("derived origins or cutoffs differ from the approved schedule")
    if schedule.target_end != date(2026, 7, 1):
        raise ScheduleContractError("target endpoint must be 2026-07-01")
    for window in schedule.windows:
        if len(window.context_rows) != CONTEXT_MONTHS:
            raise ScheduleContractError("each origin must use exactly 60 context rows")
        if len(window.forecast_months) != FORECAST_MONTHS:
            raise ScheduleContractError("each origin must contain exactly three forecast months")
        if window.context_rows[0].ds != window.historic_context_start:
            raise ScheduleContractError("historic context start does not match its rows")
        if window.context_rows[-1].ds != window.cutoff:
            raise ScheduleContractError("historic context must end at cutoff")
        if any(row.ds >= window.origin for row in window.context_rows):
            raise ScheduleContractError("historic context contains post-cutoff data")
        expected_forecast = tuple(add_months(window.origin, offset) for offset in range(3))
        if window.forecast_months != expected_forecast or window.forecast_end != expected_forecast[-1]:
            raise ScheduleContractError("forecast span is not three contiguous calendar months")
        if window.forecast_end > schedule.target_end:
            raise ScheduleContractError("forecast span exceeds the final actual month")


def schedule_digest(schedule: RollingOriginSchedule) -> str:
    """Return a stable SHA-256 for the closed schedule record."""

    validate_rolling_origin_schedule(schedule)
    payload = json.dumps(schedule.as_record(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _adapter_payload(rows: Sequence[TargetRow]) -> tuple[AdapterRow, ...]:
    return tuple(
        {"unique_id": row.unique_id, "ds": row.ds.isoformat(), "y": row.y}
        for row in rows
    )


def adapter_payload_digest(payload: Sequence[Mapping[str, str]]) -> str:
    """Digest a validated adapter payload in canonical CSV form."""

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=ADAPTER_PAYLOAD_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in payload:
        if tuple(row.keys()) != ADAPTER_PAYLOAD_COLUMNS:
            raise RollingOriginError("adapter payload columns must be exactly unique_id, ds, y")
        writer.writerow(row)
    return hashlib.sha256(buffer.getvalue().encode("utf-8")).hexdigest()


def collect_origin_request_digests(window: OriginWindow) -> dict[str, str]:
    """Return the identical digest bound to each independent origin request."""

    digest = adapter_payload_digest(_adapter_payload(window.context_rows))
    return {
        "input_digest": digest,
        "point_input_digest": digest,
        "interval_input_digest": digest,
        "quantile_input_digest": digest,
    }


def validate_p1_05_binding(path: Path) -> P105Binding:
    """Validate the exact P1-05 evidence bytes and frozen pass predicate."""

    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != P1_05_EVIDENCE_SHA256:
        raise P105BindingError("P1-05 evidence SHA-256 does not match the frozen binding")
    try:
        evidence = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise P105BindingError("P1-05 evidence is not valid JSON") from exc
    expected = {
        "schema_version": 1,
        "task_id": "P1-05",
        "run_id": P1_05_RUN_ID,
        "matrix_completeness": "complete",
        "task_outcome": "pass",
        "selector_executed": True,
        "selected_reference": REFERENCE_MODEL_ID,
    }
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise P105BindingError("P1-05 pass predicate does not match the frozen binding")
    candidates = [
        candidate
        for candidate in evidence.get("candidate_records", [])
        if isinstance(candidate, Mapping) and candidate.get("variant_id") == REFERENCE_MODEL_ID
    ]
    if len(candidates) != 1:
        raise P105BindingError("P1-05 selected candidate must resolve by one exact variant_id")
    candidate = candidates[0]
    selected_candidate = {
        "variant_id": candidate.get("variant_id"),
        "contract_completeness": candidate.get("contract_completeness"),
        "probabilistic_output_kind": candidate.get("probabilistic_output_kind"),
    }
    if selected_candidate != {
        "variant_id": REFERENCE_MODEL_ID,
        "contract_completeness": True,
        "probabilistic_output_kind": "both",
    }:
        raise P105BindingError("P1-05 selected candidate does not satisfy the pass predicate")
    selection: dict[str, object] = {**expected, "selected_candidate": selected_candidate}
    return P105Binding(evidence_sha256=digest, selection=selection)


def request_strategy_record() -> dict[str, object]:
    """Return the closed, deterministic nine-call request strategy."""

    payload_columns = list(ADAPTER_PAYLOAD_COLUMNS)
    return {
        "point": {"kind": "point", "forecast_horizons": [1, 2, 3], "payload_columns": payload_columns},
        "point_forecast_source": "point_request",
        "interval_80": {"kind": "interval", "levels": [80], "payload_columns": payload_columns},
        "quantiles_01_09": {
            "kind": "quantile",
            "quantiles": list(QUANTILES),
            "payload_columns": payload_columns,
        },
        "combined_probabilistic_request_used": False,
        "serial_forecast_calls": 9,
        "adapter_payload_columns": payload_columns,
    }


def _expected_call_receipts(
    origins: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, str, str], ...]:
    expected: list[tuple[str, str, str]] = []
    for origin in origins:
        origin_value = origin.get("origin")
        digest = origin.get("input_digest")
        if not isinstance(origin_value, str) or not isinstance(digest, str):
            raise PublicationValidationError("execution receipt requires complete origin digests")
        expected.extend(
            (origin_value, request_kind, digest)
            for request_kind in ("point", "interval_80", "quantiles_01_09")
        )
    return tuple(expected)


def _validate_execution_receipt(
    receipt: object,
    origins: Sequence[Mapping[str, object]],
) -> None:
    if not isinstance(receipt, Mapping) or set(receipt) != {
        "runner_kind", "execution_mode", "adapter_class", "model_id", "model_alias",
        "package_versions", "network_policy", "cache_policy", "call_receipts",
    }:
        raise PublicationValidationError("live execution receipt keys differ from the closed schema")
    expected_identity = {
        "runner_kind": "timecopilot_live",
        "execution_mode": "zero_shot_forecast_only",
        "adapter_class": "timecopilot.models.foundation.chronos.Chronos",
        "model_id": REFERENCE_MODEL_ID,
        "model_alias": "P105",
    }
    if any(receipt.get(key) != value for key, value in expected_identity.items()):
        raise PublicationValidationError("live execution receipt identity is invalid")
    versions = receipt.get("package_versions")
    if not isinstance(versions, Mapping) or set(versions) != {
        "timecopilot", "timecopilot-chronos-forecasting"
    } or any(not isinstance(value, str) or not value for value in versions.values()):
        raise PublicationValidationError("live execution package versions are invalid")
    if receipt.get("network_policy") not in {
        "offline_cache_only", "connected_http_proxy", "connected_runtime_default"
    }:
        raise PublicationValidationError("live execution network policy is invalid")
    if receipt.get("cache_policy") not in {
        "explicit_hf_hub_cache", "default_huggingface_cache"
    }:
        raise PublicationValidationError("live execution cache policy is invalid")
    calls = receipt.get("call_receipts")
    expected_calls = _expected_call_receipts(origins)
    if not isinstance(calls, list) or len(calls) != len(expected_calls):
        raise PublicationValidationError("live execution must contain exactly nine call receipts")
    call_keys = {
        "origin", "request_kind", "input_digest", "output_sha256", "output_rows", "status"
    }
    for call, expected in zip(calls, expected_calls, strict=True):
        if not isinstance(call, Mapping) or set(call) != call_keys:
            raise PublicationValidationError("live call receipt keys differ from the closed schema")
        if (call.get("origin"), call.get("request_kind"), call.get("input_digest")) != expected:
            raise PublicationValidationError("live call receipt sequence or input binding is invalid")
        output_sha256 = call.get("output_sha256")
        if not isinstance(output_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", output_sha256):
            raise PublicationValidationError("live call output digest is invalid")
        if call.get("output_rows") != FORECAST_MONTHS or call.get("status") != "success":
            raise PublicationValidationError("live call receipt does not record a successful 3-row output")


def _response_records(response: object) -> tuple[Mapping[str, object], ...]:
    if hasattr(response, "to_dict"):
        response = response.to_dict("records")  # type: ignore[call-arg,union-attr]
    if not isinstance(response, Sequence) or isinstance(response, (str, bytes, bytearray)):
        raise ForecastResponseError("adapter response must be a sequence of row mappings")
    records = tuple(response)
    if any(not isinstance(row, Mapping) for row in records):
        raise ForecastResponseError("every adapter response row must be a mapping")
    return records  # type: ignore[return-value]


def _finite(row: Mapping[str, object], column: str) -> float:
    raw_value = row.get(column)
    if type(raw_value) not in {int, float}:
        raise ForecastResponseError(f"response column {column} must be numeric")
    value = float(raw_value)  # type: ignore[arg-type]
    if not math.isfinite(value):
        raise ForecastResponseError(f"response column {column} must be finite")
    return value


def _reconcile_response(
    response: object,
    window: OriginWindow,
    required_columns: Sequence[str],
) -> tuple[Mapping[str, object], ...]:
    records = _response_records(response)
    if len(records) != FORECAST_MONTHS:
        raise ForecastResponseError("adapter response must contain exactly three rows")
    expected_id = window.context_rows[0].unique_id
    by_timestamp: dict[str, Mapping[str, object]] = {}
    for row in records:
        if row.get("unique_id") != expected_id:
            raise ForecastResponseError("adapter response unique_id does not match the request")
        timestamp = row.get("ds")
        if isinstance(timestamp, datetime):
            timestamp = timestamp.date().isoformat()
        elif isinstance(timestamp, date):
            timestamp = timestamp.isoformat()
        if not isinstance(timestamp, str) or timestamp in by_timestamp:
            raise ForecastResponseError("adapter response timestamps must be unique month strings")
        by_timestamp[timestamp] = row
        for column in required_columns:
            _finite(row, column)
    expected = tuple(value.isoformat() for value in window.forecast_months)
    if tuple(sorted(by_timestamp)) != expected:
        raise ForecastResponseError("adapter response timestamps do not match the forecast span")
    return tuple(by_timestamp[value] for value in expected)


def _validate_responses(
    window: OriginWindow,
    point_response: object,
    interval_response: object,
    quantile_response: object,
) -> _ValidatedResponses:
    point_rows = _reconcile_response(point_response, window, ("P105",))
    interval_rows = _reconcile_response(interval_response, window, ("P105-lo-80", "P105-hi-80"))
    quantile_columns = tuple(f"P105-q-{index * 10}" for index in range(1, 10))
    quantile_rows = _reconcile_response(quantile_response, window, quantile_columns)
    points = tuple(_finite(row, "P105") for row in point_rows)
    lowers = tuple(_finite(row, "P105-lo-80") for row in interval_rows)
    uppers = tuple(_finite(row, "P105-hi-80") for row in interval_rows)
    quantiles = tuple(
        tuple(_finite(row, column) for column in quantile_columns)
        for row in quantile_rows
    )
    if any(lower > upper for lower, upper in zip(lowers, uppers)):
        raise ForecastResponseError("80% interval lower bound exceeds upper bound")
    if any(values != tuple(sorted(values)) for values in quantiles):
        raise ForecastResponseError("forecast quantiles cross")
    return _ValidatedResponses(points, lowers, uppers, quantiles)


def run_rolling_origin_forecasts(
    rows: Sequence[TargetRow],
    adapter: ForecastOnlyAdapter,
    *,
    reference_model_id: str = REFERENCE_MODEL_ID,
    p1_05_evidence_sha256: str = P1_05_EVIDENCE_SHA256,
) -> RollingOriginResult:
    """Execute nine serial public forecast calls and return closed in-memory rows."""

    if reference_model_id != REFERENCE_MODEL_ID or p1_05_evidence_sha256 != P1_05_EVIDENCE_SHA256:
        raise P105BindingError("rolling-origin execution requires the frozen P1-05 binding")
    forecast = getattr(adapter, "forecast", None)
    if not callable(forecast):
        raise RollingOriginError("adapter must expose a public forecast method")
    target_rows = _validate_target_rows(rows)
    schedule = build_rolling_origin_schedule(target_rows)
    validated: list[tuple[OriginWindow, str, _ValidatedResponses]] = []
    for window in schedule.windows:
        payload = _adapter_payload(window.context_rows)
        digest = adapter_payload_digest(payload)
        if payload[-1]["ds"] != window.cutoff.isoformat():
            raise ScheduleContractError("maximum adapter input timestamp must equal cutoff")
        point_response = forecast(payload, h=FORECAST_MONTHS)
        interval_response = forecast(payload, h=FORECAST_MONTHS, level=[80])
        quantile_response = forecast(payload, h=FORECAST_MONTHS, quantiles=list(QUANTILES))
        responses = _validate_responses(window, point_response, interval_response, quantile_response)
        validated.append((window, digest, responses))

    # Actual values are deliberately looked up only after all nine responses validate.
    actual_by_month = {row.ds: float(row.y) for row in target_rows}
    origin_records: list[OriginRecord] = []
    policy = PUBLICATION_POLICY
    for window, digest, responses in validated:
        output_rows: list[ForecastRow] = []
        for index, forecast_month in enumerate(window.forecast_months):
            values: tuple[object, ...] = (
                window.origin.isoformat(),
                window.cutoff.isoformat(),
                window.historic_context_start.isoformat(),
                window.historic_context_end.isoformat(),
                forecast_month.isoformat(),
                index + 1,
                actual_by_month[forecast_month],
                responses.point[index],
                responses.lower[index],
                responses.upper[index],
                *responses.quantiles[index],
                reference_model_id,
                p1_05_evidence_sha256,
                policy.evaluation_label,
                policy.availability_proxy,
                policy.limitation,
            )
            output_rows.append(ForecastRow(values))
        origin_records.append(OriginRecord(window, digest, tuple(output_rows)))
    result = RollingOriginResult(schedule, tuple(origin_records))
    validate_rolling_origin_result(result)
    return result


def validate_rolling_origin_result(result: RollingOriginResult) -> None:
    """Validate the closed nine-row in-memory result contract."""

    validate_rolling_origin_schedule(result.schedule)
    if len(result.origins) != ORIGIN_COUNT or len(result.rows) != 9:
        raise ForecastResponseError("rolling-origin result must contain three origins and nine rows")
    for origin_record in result.origins:
        if len(origin_record.rows) != 3:
            raise ForecastResponseError("each origin result must contain exactly three rows")
        for expected_step, row in enumerate(origin_record.rows, start=1):
            record = row.as_dict()
            if tuple(record) != OUTPUT_COLUMNS or len(record) != 24:
                raise ForecastResponseError("forecast row does not match the closed 24-column schema")
            if record["forecast_horizon_step"] != expected_step:
                raise ForecastResponseError("forecast horizon steps must be 1, 2, 3")
            expected_metadata = {
                "origin": origin_record.window.origin.isoformat(),
                "cutoff": origin_record.window.cutoff.isoformat(),
                "historic_context_start": origin_record.window.historic_context_start.isoformat(),
                "historic_context_end": origin_record.window.historic_context_end.isoformat(),
                "forecast_month": origin_record.window.forecast_months[expected_step - 1].isoformat(),
                "reference_model_id": REFERENCE_MODEL_ID,
                "p1_05_evidence_sha256": P1_05_EVIDENCE_SHA256,
                "publication_label": PUBLICATION_POLICY.evaluation_label,
                "publication_proxy": PUBLICATION_POLICY.availability_proxy,
                "vintage_limitation": PUBLICATION_POLICY.limitation,
            }
            for column, expected_value in expected_metadata.items():
                if record[column] != expected_value:
                    raise ForecastResponseError(f"forecast row metadata is invalid: {column}")
            numeric_columns = OUTPUT_COLUMNS[6:19]
            if any(not _is_finite_number(record[column]) for column in numeric_columns):
                raise ForecastResponseError("all forecast and actual values must be finite numeric values")
            quantile_values = tuple(_known_float(record[column]) for column in OUTPUT_COLUMNS[10:19])
            if quantile_values != tuple(sorted(quantile_values)):
                raise ForecastResponseError("forecast quantiles cross")
            if _known_float(record["interval_80_lower"]) > _known_float(record["interval_80_upper"]):
                raise ForecastResponseError("80% interval lower bound exceeds upper bound")


def _is_finite_number(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(_known_float(value))


def _known_float(value: object) -> float:
    return float(value)  # type: ignore[arg-type]


def normalize_origin_record(origin: OriginRecord) -> dict[str, object]:
    """Return the closed evidence-facing record for one validated origin."""

    window = origin.window
    digests = collect_origin_request_digests(window)
    if origin.input_digest != digests["input_digest"]:
        raise ForecastResponseError("origin input digest differs from its validated context")
    return {
        **window.as_span_record(),
        "point_forecast_kind": "point_request",
        "probabilistic_output_kind": "both",
        "actuals_present": True,
        "zero_shot_assertions": {
            "history_only": True,
            "no_fit": True,
            "no_train": True,
            "no_fine_tune": True,
            "no_calibrate": True,
            "no_update_weights": True,
            "no_cross_validation": True,
            "public_orchestration_only": True,
        },
        **digests,
        "output_columns": list(OUTPUT_COLUMNS),
        "output_shape": {"rows": 3, "columns": 24},
    }


def serialize_rolling_origin_csv(result: RollingOriginResult) -> bytes:
    """Serialize validated rows using the exact stable CSV column order."""

    validate_rolling_origin_result(result)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(row.as_dict() for row in result.rows)
    return buffer.getvalue().encode("utf-8")


# Publication is deliberately implemented below the deterministic runner so the
# in-memory contract remains usable without touching repository state.  The JSON
# evidence file is the commit marker: payloads are never consumable unless this
# marker is a matching ``pass_final`` record.
TASK_ID = "P1-06"
EVIDENCE_SCHEMA_VERSION = 1
MARKER_STATES = ("invalid_in_progress", "invalid_final", "pass_final")
CLASSIFICATIONS = ("pass", "fail", "blocked", "unsupported")
P1_06_ROADMAP_PATTERN = re.compile(r"(?m)^- \[([ x-])\] \*\*P1-06\b.*$")


class PublicationError(RollingOriginError):
    """Raised when the commit-marker publication contract is violated."""


class PublicationValidationError(PublicationError):
    """Raised when a published payload or marker is stale or malformed."""


def _utc_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise PublicationValidationError(f"artifact is unreadable: {path}") from exc


def _repo_path(repo_root: Path, relative: Path) -> Path:
    return repo_root.resolve() / relative


def _prior_marker_hash(repo_root: Path) -> str | None:
    path = _repo_path(repo_root, EVIDENCE_RELATIVE_PATH)
    return _sha256_path(path) if path.is_file() else None


def _default_checks(value: bool = False) -> dict[str, bool]:
    return {name: value for name in CHECK_NAMES}


def _target_digest(repo_root: Path) -> str | None:
    path = _repo_path(repo_root, TARGET_RELATIVE_PATH)
    return _sha256_path(path) if path.is_file() else None


def _p1_05_selection(repo_root: Path) -> dict[str, object] | None:
    path = _repo_path(repo_root, P1_05_RELATIVE_PATH)
    if not path.is_file():
        return None
    try:
        return dict(validate_p1_05_binding(path).selection)
    except (OSError, P105BindingError):
        return None


def _publication_protocol(
    *,
    marker_state: str,
    prior_marker_sha256: str | None,
    csv_sha256: str | None = None,
    markdown_sha256: str | None = None,
    commit_marker_valid: bool = False,
) -> dict[str, object]:
    if marker_state not in MARKER_STATES:
        raise PublicationError(f"unknown publication marker state: {marker_state}")
    return {
        "marker_path": str(EVIDENCE_RELATIVE_PATH),
        "marker_state": marker_state,
        "prior_marker_sha256": prior_marker_sha256,
        "csv_sha256": csv_sha256,
        "markdown_sha256": markdown_sha256,
        "write_order": list(WRITE_ORDER),
        "commit_marker_valid": commit_marker_valid,
        "replacements_fsynchronized": commit_marker_valid,
    }


def _diagnostic(
    *,
    classification: str,
    scope: str,
    stage: str,
    reason: str,
    origin: str | None = None,
    request_kind: str | None = None,
    exception_class: str | None = None,
) -> dict[str, object]:
    if classification not in CLASSIFICATIONS or classification == "pass":
        raise PublicationError("diagnostics must carry a non-pass classification")
    if stage not in {"schedule", "request", "response", "join", "publication", "binding", "roadmap"}:
        raise PublicationError(f"invalid diagnostic stage: {stage}")
    if request_kind is not None and request_kind not in {"point", "interval_80", "quantiles_01_09"}:
        raise PublicationError(f"invalid diagnostic request kind: {request_kind}")
    return {
        "classification": classification,
        "scope": scope,
        "stage": stage,
        "origin": origin,
        "request_kind": request_kind,
        "sanitized_reason": reason,
        "exception_class": exception_class,
        "artifact_paths": list(ARTIFACT_PATHS),
    }


def _base_evidence(
    *,
    repo_root: Path,
    marker_state: str,
    classification: str,
    result: RollingOriginResult | None,
    execution_receipt: LiveExecutionReceipt | None,
    diagnostics: Sequence[Mapping[str, object]],
    errors: Sequence[str],
    prior_marker_sha256: str | None,
    now: datetime | None,
) -> dict[str, object]:
    if marker_state not in MARKER_STATES:
        raise PublicationError(f"unknown publication marker state: {marker_state}")
    if classification not in CLASSIFICATIONS:
        raise PublicationError(f"unknown classification: {classification}")
    if marker_state == "pass_final" and (classification != "pass" or result is None):
        raise PublicationError("pass_final requires a complete passing result")
    if marker_state == "pass_final" and execution_receipt is None:
        raise PublicationError("pass_final requires a live TimeCopilot execution receipt")
    if marker_state != "pass_final" and execution_receipt is not None:
        raise PublicationError("invalid evidence cannot carry a live execution receipt")
    if marker_state == "invalid_in_progress" and classification != "blocked":
        raise PublicationError("invalid_in_progress must be blocked")
    if marker_state == "invalid_final" and classification == "pass":
        raise PublicationError("invalid_final cannot have pass classification")
    p1_selection = _p1_05_selection(repo_root)
    binding_valid = p1_selection is not None
    target_digest = _target_digest(repo_root) if result is not None else None
    if marker_state == "pass_final" and not binding_valid:
        raise PublicationError("pass_final requires the frozen P1-05 binding")
    if marker_state == "pass_final" and target_digest is None:
        raise PublicationError("pass_final requires a bound model-ready target artifact")
    schedule = result.schedule.as_record() if result is not None else None
    origin_records = [normalize_origin_record(origin) for origin in result.origins] if result is not None else []
    execution_record = execution_receipt.as_record() if execution_receipt is not None else None
    if execution_record is not None:
        _validate_execution_receipt(execution_record, origin_records)
    checks = _default_checks(False)
    if result is not None and marker_state == "pass_final":
        checks.update(
            {
                "p1_05_binding_valid": binding_valid,
                "schedule_valid": True,
                "window_leakage_free": all(
                    all(row.ds <= origin.window.cutoff for row in origin.window.context_rows)
                    and all(row.ds < origin.window.origin for row in origin.window.context_rows)
                    for origin in result.origins
                ),
                "forecast_calls_serial": True,
                "csv_schema_valid": True,
                "publication_protocol_valid": True,
                "probabilistic_outputs_supported": True,
                "roadmap_eligible": True,
            }
        )
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": f"P1-06-{_utc_timestamp(now).replace('-', '').replace(':', '').replace('T', '')}",
        "timestamp_utc": _utc_timestamp(now),
        "classification": classification,
        "non_pass_diagnostics": [dict(item) for item in diagnostics],
        "reference_model_id": REFERENCE_MODEL_ID if binding_valid else None,
        "p1_05_run_id": P1_05_RUN_ID if binding_valid else None,
        "p1_05_evidence_sha256": P1_05_EVIDENCE_SHA256 if binding_valid else None,
        "p1_05_selection": p1_selection,
        "target_artifact_sha256": target_digest,
        "publication_policy": PUBLICATION_POLICY.as_dict() if result is not None else None,
        "publication_protocol": _publication_protocol(
            marker_state=marker_state,
            prior_marker_sha256=prior_marker_sha256,
        ),
        "schedule": schedule,
        "request_strategy": request_strategy_record() if result is not None else None,
        "execution_receipt": execution_record,
        "origin_records": origin_records,
        "checks": checks,
        "errors": [str(error) for error in errors],
        "artifact_paths": list(ARTIFACT_PATHS),
    }


def render_rolling_origin_markdown(evidence: Mapping[str, object]) -> str:
    """Render the finding from canonical evidence without self-referential hashes."""

    schedule_value = evidence.get("schedule")
    schedule: Mapping[str, object] = schedule_value if isinstance(schedule_value, Mapping) else {}
    protocol_value = evidence.get("publication_protocol")
    protocol: Mapping[str, object] = protocol_value if isinstance(protocol_value, Mapping) else {}
    receipt_value = evidence.get("execution_receipt")
    receipt: Mapping[str, object] = receipt_value if isinstance(receipt_value, Mapping) else {}
    versions_value = receipt.get("package_versions")
    versions: Mapping[str, object] = versions_value if isinstance(versions_value, Mapping) else {}
    diagnostics_value = evidence.get("non_pass_diagnostics")
    diagnostics: Sequence[object] = diagnostics_value if isinstance(diagnostics_value, list) else []
    errors_value = evidence.get("errors")
    errors: Sequence[object] = errors_value if isinstance(errors_value, list) else []
    origin_values = schedule.get("origin_months", [])
    origins = origin_values if isinstance(origin_values, list) else []
    cutoff_values = schedule.get("cutoff_months", [])
    cutoffs = cutoff_values if isinstance(cutoff_values, list) else []
    write_order_values = protocol.get("write_order", WRITE_ORDER)
    write_order = write_order_values if isinstance(write_order_values, list) else list(WRITE_ORDER)
    lines = [
        "# Phase 1 Monthly Rolling-Origin Forecasting",
        "",
        f"- Run ID: `{evidence.get('run_id')}`",
        f"- Classification: `{evidence.get('classification')}`",
        f"- Marker state: `{protocol.get('marker_state')}`",
        f"- Reference model: `{evidence.get('reference_model_id') or 'none'}`",
        f"- Execution runner: `{receipt.get('runner_kind') or 'none'}`",
        f"- Execution mode: `{receipt.get('execution_mode') or 'none'}`",
        f"- TimeCopilot version: `{versions.get('timecopilot') or 'none'}`",
        f"- Chronos adapter package version: `{versions.get('timecopilot-chronos-forecasting') or 'none'}`",
        f"- Network policy: `{receipt.get('network_policy') or 'none'}`",
        f"- Cache policy: `{receipt.get('cache_policy') or 'none'}`",
        f"- P1-05 evidence SHA-256: `{evidence.get('p1_05_evidence_sha256') or 'none'}`",
        f"- Publication label: `{PUBLICATION_POLICY.evaluation_label}`",
        f"- Availability proxy: `{PUBLICATION_POLICY.availability_proxy}`",
        f"- Vintage limitation: {PUBLICATION_POLICY.limitation}",
        "",
        "## Schedule",
        "",
        f"- Origins: `{', '.join(str(item) for item in origins)}`",
        f"- Cutoffs: `{', '.join(str(item) for item in cutoffs)}`",
        f"- Historic context: `{schedule.get('historic_context_months', 'none')}` months",
        f"- Forecast horizon: `{schedule.get('forecast_months', 'none')}` months",
        "",
        "## Zero-shot and publication contract",
        "",
        "- History-only context is passed through public forecast calls; no per-origin fitting, fine-tuning, calibration, or weight updates are performed.",
        "- Point forecasts are authoritative; interval and quantile outputs are independent supported probabilistic requests.",
        "- The revised workbook is labeled pseudo-real-time. Historical release timestamps and vintages are unavailable, so strict prior-month eligibility is a conservative proxy rather than vintage-real-time evidence.",
        f"- Write order: `{', '.join(str(item) for item in write_order)}`.",
    ]
    if diagnostics:
        lines.extend(["", "## Non-pass diagnostics", ""])
        lines.extend(
            f"- `{item.get('stage')}`: {item.get('sanitized_reason')}"
            for item in diagnostics
            if isinstance(item, Mapping)
        )
    if errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in errors)
    lines.extend(["", "Machine-readable evidence: `docs/findings/phase1/evidence/rolling_origin.json`", ""])
    return "\n".join(lines)


def build_rolling_origin_evidence(
    result: RollingOriginResult | None = None,
    *,
    execution_receipt: LiveExecutionReceipt | None = None,
    repo_root: Path | None = None,
    marker_state: str = "pass_final",
    classification: str = "pass",
    diagnostics: Sequence[Mapping[str, object]] = (),
    errors: Sequence[str] = (),
    prior_marker_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Build a closed evidence record for a result or an invalid attempt."""

    root = (repo_root or Path.cwd()).resolve()
    if prior_marker_sha256 is None:
        prior_marker_sha256 = _prior_marker_hash(root)
    evidence = _base_evidence(
        repo_root=root,
        marker_state=marker_state,
        classification=classification,
        result=result,
        execution_receipt=execution_receipt,
        diagnostics=diagnostics,
        errors=errors,
        prior_marker_sha256=prior_marker_sha256,
        now=now,
    )
    if marker_state == "pass_final":
        csv_bytes = serialize_rolling_origin_csv(result)  # type: ignore[arg-type]
        markdown = render_rolling_origin_markdown(evidence).encode("utf-8")
        protocol_value = evidence["publication_protocol"]
        if not isinstance(protocol_value, Mapping):
            raise PublicationError("publication protocol is not a mapping")
        protocol = dict(protocol_value)
        protocol.update(
            {
                "csv_sha256": _sha256_bytes(csv_bytes),
                "markdown_sha256": _sha256_bytes(markdown),
                "commit_marker_valid": True,
                "replacements_fsynchronized": True,
            }
        )
        evidence["publication_protocol"] = protocol
    return evidence


def _validate_evidence_shape(evidence: Mapping[str, object], *, root: Path | None = None) -> None:
    required = set(TOP_LEVEL_KEYS)
    if set(evidence) != required:
        raise PublicationValidationError("rolling-origin evidence keys differ from the closed schema")
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION or evidence.get("task_id") != TASK_ID:
        raise PublicationValidationError("rolling-origin evidence identity is invalid")
    classification = evidence.get("classification")
    if classification not in CLASSIFICATIONS:
        raise PublicationValidationError("rolling-origin classification is invalid")
    protocol = evidence.get("publication_protocol")
    if not isinstance(protocol, Mapping) or set(protocol) != {
        "marker_path", "marker_state", "prior_marker_sha256", "csv_sha256", "markdown_sha256",
        "write_order", "commit_marker_valid", "replacements_fsynchronized",
    }:
        raise PublicationValidationError("publication protocol keys differ from the closed schema")
    marker_state = protocol.get("marker_state")
    if marker_state not in MARKER_STATES or protocol.get("marker_path") != str(EVIDENCE_RELATIVE_PATH):
        raise PublicationValidationError("publication marker envelope is invalid")
    if protocol.get("write_order") != list(WRITE_ORDER):
        raise PublicationValidationError("publication write order is invalid")
    diagnostics = evidence.get("non_pass_diagnostics")
    if not isinstance(diagnostics, list):
        raise PublicationValidationError("non-pass diagnostics must be an array")
    if marker_state == "invalid_in_progress":
        if classification != "blocked" or protocol.get("commit_marker_valid") or protocol.get("replacements_fsynchronized"):
            raise PublicationValidationError("invalid_in_progress state is inconsistent")
        if evidence.get("execution_receipt") is not None:
            raise PublicationValidationError("invalid_in_progress cannot carry an execution receipt")
    elif marker_state == "invalid_final":
        if classification == "pass" or not diagnostics or protocol.get("commit_marker_valid") or protocol.get("replacements_fsynchronized"):
            raise PublicationValidationError("invalid_final state is inconsistent")
        if evidence.get("execution_receipt") is not None:
            raise PublicationValidationError("invalid_final cannot carry an execution receipt")
    elif marker_state == "pass_final":
        if classification != "pass" or diagnostics or evidence.get("errors"):
            raise PublicationValidationError("pass_final state is inconsistent")
        if protocol.get("csv_sha256") is None or protocol.get("markdown_sha256") is None or not protocol.get("commit_marker_valid") or not protocol.get("replacements_fsynchronized"):
            raise PublicationValidationError("pass_final payload hashes or marker validity are missing")
        origins = evidence.get("origin_records")
        checks = evidence.get("checks")
        if not isinstance(origins, list) or len(origins) != ORIGIN_COUNT:
            raise PublicationValidationError("pass_final must contain exactly three origin records")
        if not isinstance(checks, Mapping) or set(checks) != set(CHECK_NAMES) or any(value is not True for value in checks.values()):
            raise PublicationValidationError("pass_final checks are not all true")
        if evidence.get("request_strategy") != request_strategy_record():
            raise PublicationValidationError("pass_final request strategy differs from the closed contract")
        _validate_execution_receipt(evidence.get("execution_receipt"), origins)
        _validate_pass_nested_evidence(evidence, root)


def _validate_pass_nested_evidence(
    evidence: Mapping[str, object], root: Path | None
) -> None:
    """Validate nested pass fields instead of trusting marker-owned claims."""

    schedule = evidence.get("schedule")
    if not isinstance(schedule, Mapping):
        raise PublicationValidationError("pass_final schedule is missing")
    expected_schedule: dict[str, object] = {
        "origin_count": ORIGIN_COUNT,
        "step_months": 1,
        "historic_context_months": CONTEXT_MONTHS,
        "forecast_months": FORECAST_MONTHS,
        "origin_months": [value.isoformat() for value in EXPECTED_ORIGINS],
        "cutoff_months": [value.isoformat() for value in EXPECTED_CUTOFFS],
    }
    expected_digests: tuple[str, ...] | None = None
    if root is not None:
        target_path = _repo_path(root, TARGET_RELATIVE_PATH)
        if target_path.is_file():
            derived_schedule = build_rolling_origin_schedule(parse_target_csv(target_path))
            expected_schedule = derived_schedule.as_record()
            expected_digests = tuple(
                collect_origin_request_digests(window)["input_digest"]
                for window in derived_schedule.windows
            )
    for key, value in expected_schedule.items():
        if schedule.get(key) != value:
            raise PublicationValidationError(f"pass_final schedule field is invalid: {key}")
    origins = evidence.get("origin_records")
    if not isinstance(origins, list) or len(origins) != ORIGIN_COUNT:
        raise PublicationValidationError("pass_final origin records are incomplete")
    expected_zero_shot = {
        "history_only": True,
        "no_fit": True,
        "no_train": True,
        "no_fine_tune": True,
        "no_calibrate": True,
        "no_update_weights": True,
        "no_cross_validation": True,
        "public_orchestration_only": True,
    }
    expected_record_keys = {
        "origin", "cutoff", "historic_context_start", "historic_context_end",
        "forecast_start", "forecast_end", "row_count", "forecast_row_count",
        "point_forecast_kind", "probabilistic_output_kind", "actuals_present",
        "zero_shot_assertions", "input_digest", "point_input_digest",
        "interval_input_digest", "quantile_input_digest", "output_columns", "output_shape",
    }
    for index, record in enumerate(origins):
        if not isinstance(record, Mapping) or set(record) != expected_record_keys:
            raise PublicationValidationError("pass_final origin record keys differ from the closed schema")
        origin = EXPECTED_ORIGINS[index]
        cutoff = EXPECTED_CUTOFFS[index]
        expected_start = add_months(cutoff, -(CONTEXT_MONTHS - 1))
        expected_forecast = tuple(add_months(origin, step) for step in range(FORECAST_MONTHS))
        expected_fields = {
            "origin": origin.isoformat(),
            "cutoff": cutoff.isoformat(),
            "historic_context_start": expected_start.isoformat(),
            "historic_context_end": cutoff.isoformat(),
            "forecast_start": expected_forecast[0].isoformat(),
            "forecast_end": expected_forecast[-1].isoformat(),
            "row_count": CONTEXT_MONTHS,
            "forecast_row_count": FORECAST_MONTHS,
            "point_forecast_kind": "point_request",
            "probabilistic_output_kind": "both",
            "actuals_present": True,
            "zero_shot_assertions": expected_zero_shot,
            "output_columns": list(OUTPUT_COLUMNS),
            "output_shape": {"rows": FORECAST_MONTHS, "columns": len(OUTPUT_COLUMNS)},
        }
        for key, value in expected_fields.items():
            if record.get(key) != value:
                raise PublicationValidationError(f"pass_final origin field is invalid: {key}")
        digests = [record.get(key) for key in ("input_digest", "point_input_digest", "interval_input_digest", "quantile_input_digest")]
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in digests) or len(set(digests)) != 1:
            raise PublicationValidationError("pass_final origin input digests are invalid")
        if expected_digests is not None and digests[0] != expected_digests[index]:
            raise PublicationValidationError("pass_final origin input digest does not match the bound context")


def validate_rolling_origin_publication(repo_root: Path | None = None) -> dict[str, object]:
    """Validate the canonical marker and its payload hashes without mutation."""

    root = (repo_root or Path.cwd()).resolve()
    marker_path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
    try:
        evidence = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationValidationError("rolling-origin evidence marker is unavailable") from exc
    if not isinstance(evidence, dict):
        raise PublicationValidationError("rolling-origin evidence marker must be an object")
    _validate_evidence_shape(evidence, root=root)
    protocol = evidence["publication_protocol"]
    assert isinstance(protocol, Mapping)
    if protocol["marker_state"] != "pass_final":
        raise PublicationValidationError("rolling-origin payload is not consumable without pass_final marker")
    p1_path = _repo_path(root, P1_05_RELATIVE_PATH)
    if not p1_path.is_file() or _sha256_path(p1_path) != evidence.get("p1_05_evidence_sha256"):
        raise PublicationValidationError("published evidence is stale against the frozen P1-05 binding")
    try:
        binding = validate_p1_05_binding(p1_path)
    except P105BindingError as exc:
        raise PublicationValidationError("published evidence has an invalid P1-05 binding") from exc
    if evidence.get("p1_05_selection") != dict(binding.selection):
        raise PublicationValidationError("published P1-05 selection differs from the frozen binding")
    if evidence.get("publication_policy") != PUBLICATION_POLICY.as_dict():
        raise PublicationValidationError("published publication policy differs from P1-01")
    target_path = _repo_path(root, TARGET_RELATIVE_PATH)
    if not target_path.is_file():
        raise PublicationValidationError("published target artifact is missing")
    if evidence.get("target_artifact_sha256") != _sha256_path(target_path):
        raise PublicationValidationError("published evidence is stale against the target artifact")
    csv_path = _repo_path(root, FORECASTS_RELATIVE_PATH)
    markdown_path = _repo_path(root, FINDING_RELATIVE_PATH)
    if _sha256_path(csv_path) != protocol["csv_sha256"] or _sha256_path(markdown_path) != protocol["markdown_sha256"]:
        raise PublicationValidationError("published payload hash does not match the pass marker")
    markdown = markdown_path.read_text(encoding="utf-8")
    if markdown != render_rolling_origin_markdown(evidence):
        raise PublicationValidationError("rolling-origin Markdown differs from canonical evidence")
    _validate_published_csv(root, evidence)
    return evidence


def _validate_published_csv(root: Path, evidence: Mapping[str, object]) -> None:
    path = _repo_path(root, FORECASTS_RELATIVE_PATH)
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != OUTPUT_COLUMNS:
                raise PublicationValidationError("published CSV columns differ from the closed schema")
            rows = list(reader)
    except OSError as exc:
        raise PublicationValidationError("published CSV is unavailable") from exc
    if len(rows) != 9:
        raise PublicationValidationError("published CSV must contain exactly nine rows")
    expected_origins = [value.isoformat() for value in EXPECTED_ORIGINS]
    if [row["origin"] for row in rows[::3]] != expected_origins:
        raise PublicationValidationError("published CSV origin order is invalid")
    target_path = _repo_path(root, TARGET_RELATIVE_PATH)
    if not target_path.is_file():
        raise PublicationValidationError("published target artifact is missing")
    target_rows = parse_target_csv(target_path)
    actuals = {row.ds.isoformat(): float(row.y) for row in target_rows}
    for row in rows:
        if row["forecast_month"] not in actuals or float(row["actual"]) != actuals[row["forecast_month"]]:
            raise PublicationValidationError("published CSV actual does not match the target artifact")
    expected_by_origin = {
        origin.isoformat(): tuple(add_months(origin, index).isoformat() for index in range(FORECAST_MONTHS))
        for origin in EXPECTED_ORIGINS
    }
    for index, row in enumerate(rows):
        origin_index = index // FORECAST_MONTHS
        horizon = index % FORECAST_MONTHS + 1
        origin = expected_origins[origin_index]
        if row["origin"] != origin or row["forecast_horizon_step"] != str(horizon):
            raise PublicationValidationError("published CSV row order or horizon is invalid")
        if row["forecast_month"] != expected_by_origin[origin][horizon - 1]:
            raise PublicationValidationError("published CSV forecast span is invalid")
        if row["reference_model_id"] != REFERENCE_MODEL_ID or row["p1_05_evidence_sha256"] != P1_05_EVIDENCE_SHA256:
            raise PublicationValidationError("published CSV provenance binding is invalid")
        if row["cutoff"] != add_months(date.fromisoformat(origin), -1).isoformat():
            raise PublicationValidationError("published CSV cutoff is invalid")
        if row["historic_context_end"] != row["cutoff"]:
            raise PublicationValidationError("published CSV historic context end is invalid")
        expected_context_start = add_months(date.fromisoformat(row["cutoff"]), -(CONTEXT_MONTHS - 1))
        if row["historic_context_start"] != expected_context_start.isoformat():
            raise PublicationValidationError("published CSV historic context start is invalid")
        expected_policy = {
            "publication_label": PUBLICATION_POLICY.evaluation_label,
            "publication_proxy": PUBLICATION_POLICY.availability_proxy,
            "vintage_limitation": PUBLICATION_POLICY.limitation,
        }
        for column, expected_value in expected_policy.items():
            if row[column] != expected_value:
                raise PublicationValidationError(f"published CSV policy field is invalid: {column}")
        for column in OUTPUT_COLUMNS[6:19]:
            try:
                value = float(row[column])
            except (TypeError, ValueError) as exc:
                raise PublicationValidationError(f"published CSV value is not numeric: {column}") from exc
            if not math.isfinite(value):
                raise PublicationValidationError(f"published CSV value is not finite: {column}")
        lower = float(row["interval_80_lower"])
        upper = float(row["interval_80_upper"])
        if lower > upper:
            raise PublicationValidationError("published CSV interval bounds cross")
        quantiles = [float(row[f"quantile_0_{index}"]) for index in range(1, 10)]
        if quantiles != sorted(quantiles):
            raise PublicationValidationError("published CSV quantiles cross")


def validate_rolling_origin_consumer_gate(repo_root: Path | None = None) -> dict[str, object]:
    """P1-07 gate: downstream consumers may load only a validated pass marker."""

    return validate_rolling_origin_publication(repo_root)


def validate_rolling_origin_roadmap_eligibility(repo_root: Path | None = None) -> bool:
    """Return whether a validated P1-06 pass may advance the roadmap."""

    root = (repo_root or Path.cwd()).resolve()
    evidence = validate_rolling_origin_publication(root)
    if evidence["classification"] != "pass":
        return False
    roadmap = _repo_path(root, ROADMAP_RELATIVE_PATH).read_text(encoding="utf-8")
    matches = P1_06_ROADMAP_PATTERN.findall(roadmap)
    return matches in ([" "], ["x"])


def _stage_bytes(destination: Path, content: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def begin_rolling_origin_attempt(
    repo_root: Path | None = None,
    *,
    now: datetime | None = None,
    replace_file: object = os.replace,
) -> dict[str, object]:
    """Invalidate the canonical marker before any model execution."""

    root = (repo_root or Path.cwd()).resolve()
    evidence = build_rolling_origin_evidence(
        None,
        repo_root=root,
        marker_state="invalid_in_progress",
        classification="blocked",
        now=now,
    )
    content = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")
    destination = _repo_path(root, EVIDENCE_RELATIVE_PATH)
    staged = _stage_bytes(destination, content)
    try:
        replace_file(staged, destination)  # type: ignore[operator]
    finally:
        staged.unlink(missing_ok=True)
    return evidence


def publish_rolling_origin_bundle(
    result: RollingOriginResult,
    repo_root: Path | None = None,
    *,
    execution_receipt: LiveExecutionReceipt | None = None,
    now: datetime | None = None,
    replace_file: object = os.replace,
) -> dict[str, object]:
    """Write payloads first and the pass marker last, with fsynced staging."""

    root = (repo_root or Path.cwd()).resolve()
    validate_rolling_origin_result(result)
    if execution_receipt is None:
        raise PublicationError("canonical pass publication requires live execution attestation")
    evidence = build_rolling_origin_evidence(
        result,
        execution_receipt=execution_receipt,
        repo_root=root,
        now=now,
    )
    csv_bytes = serialize_rolling_origin_csv(result)
    markdown_bytes = render_rolling_origin_markdown(evidence).encode("utf-8")
    evidence_bytes = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")
    destinations = (
        (_repo_path(root, FORECASTS_RELATIVE_PATH), csv_bytes),
        (_repo_path(root, FINDING_RELATIVE_PATH), markdown_bytes),
        (_repo_path(root, EVIDENCE_RELATIVE_PATH), evidence_bytes),
    )
    staged: list[tuple[Path, Path]] = []
    try:
        staged = [(_stage_bytes(destination, content), destination) for destination, content in destinations]
        for index, (temporary, destination) in enumerate(staged):
            if index == 2:
                # Re-read the marker object before its final replacement; this
                # prevents a caller from accidentally publishing a stale marker.
                _validate_evidence_shape(evidence)
            replace_file(temporary, destination)  # type: ignore[operator]
    except BaseException as exc:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        diagnostic = _diagnostic(
            classification="fail",
            scope="p1-06-publication",
            stage="publication",
            reason=f"publication boundary failed: {type(exc).__name__}",
            exception_class=type(exc).__name__,
        )
        invalid = build_rolling_origin_evidence(
            None,
            repo_root=root,
            marker_state="invalid_final",
            classification="fail",
            diagnostics=(diagnostic,),
            errors=("publication boundary failed",),
            now=now,
        )
        invalid_bytes = (json.dumps(invalid, indent=2, sort_keys=True) + "\n").encode("utf-8")
        invalid_path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
        invalid_stage = _stage_bytes(invalid_path, invalid_bytes)
        try:
            replace_file(invalid_stage, invalid_path)  # type: ignore[operator]
        finally:
            invalid_stage.unlink(missing_ok=True)
        raise PublicationError("rolling-origin publication failed and marker was invalidated") from exc
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    try:
        return validate_rolling_origin_publication(root)
    except Exception as exc:
        diagnostic = _diagnostic(
            classification="fail",
            scope="p1-06-publication",
            stage="publication",
            reason=f"post-publication validation failed: {type(exc).__name__}",
            exception_class=type(exc).__name__,
        )
        invalid = build_rolling_origin_evidence(
            None,
            repo_root=root,
            marker_state="invalid_final",
            classification="fail",
            diagnostics=(diagnostic,),
            errors=("post-publication validation failed",),
            now=now,
        )
        invalid_path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
        invalid_stage = _stage_bytes(invalid_path, (json.dumps(invalid, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        try:
            replace_file(invalid_stage, invalid_path)  # type: ignore[operator]
        finally:
            invalid_stage.unlink(missing_ok=True)
        raise PublicationError("rolling-origin publication failed post-write validation") from exc


def update_rolling_origin_roadmap(repo_root: Path | None = None) -> None:
    """Idempotently check P1-06 only after the matching pass marker validates."""

    root = (repo_root or Path.cwd()).resolve()
    validate_rolling_origin_publication(root)
    path = _repo_path(root, ROADMAP_RELATIVE_PATH)
    text = path.read_text(encoding="utf-8")
    matches = P1_06_ROADMAP_PATTERN.findall(text)
    if matches not in ([" "], ["x"]):
        raise PublicationError("P1-06 roadmap entry is missing, duplicated, or invalid")
    if matches == ["x"]:
        return
    updated = P1_06_ROADMAP_PATTERN.sub(lambda match: match.group(0).replace("[ ]", "[x]", 1), text)
    staged = _stage_bytes(path, updated.encode("utf-8"))
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _required_package_version(distribution: str) -> str:
    try:
        return package_version(distribution)
    except PackageNotFoundError as exc:  # pragma: no cover - environment-dependent
        raise LiveDependencyError(f"required live distribution is unavailable: {distribution}") from exc


def _live_network_policy() -> str:
    proxy_names = (
        "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"
    )
    proxies_present = any(os.environ.get(name) for name in proxy_names)
    offline = os.environ.get("HF_HUB_OFFLINE") == "1" and os.environ.get("TRANSFORMERS_OFFLINE") == "1"
    if offline and not proxies_present:
        return "offline_cache_only"
    if proxies_present:
        return "connected_http_proxy"
    return "connected_runtime_default"


def _live_cache_policy() -> str:
    return "explicit_hf_hub_cache" if os.environ.get("HF_HUB_CACHE") else "default_huggingface_cache"


def _response_sha256(response: object) -> tuple[str, int]:
    records = _response_records(response)
    payload = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: value.isoformat() if isinstance(value, date) else str(value),
        allow_nan=False,
    )
    return _sha256_bytes(payload.encode("utf-8")), len(records)


class _TimeCopilotForecastAdapter:
    """Adapt TimeCopilot's public dataframe API to the trap-friendly boundary."""

    def __init__(self, model: Any) -> None:
        self._model = model
        self._call_receipts: list[ForecastCallReceipt] = []

    def forecast(
        self,
        payload: Sequence[Mapping[str, str]],
        *,
        h: int,
        level: Sequence[int] | None = None,
        quantiles: Sequence[float] | None = None,
    ) -> object:
        try:
            import pandas as pd
        except Exception as exc:  # pragma: no cover - environment-dependent
            raise LiveDependencyError("pandas is required for the TimeCopilot adapter") from exc
        frame = pd.DataFrame(
            {
                "unique_id": [row["unique_id"] for row in payload],
                "ds": pd.to_datetime([row["ds"] for row in payload]),
                "y": [float(row["y"]) for row in payload],
            }
        )
        request: dict[str, object] = {}
        if level is not None:
            request["level"] = list(level)
        if quantiles is not None:
            request["quantiles"] = list(quantiles)
        result = self._model.forecast(df=frame, h=h, freq="MS", **request)
        if level is not None:
            request_kind = "interval_80"
        elif quantiles is not None:
            request_kind = "quantiles_01_09"
        else:
            request_kind = "point"
        output_sha256, output_rows = _response_sha256(result)
        self._call_receipts.append(
            ForecastCallReceipt(
                origin=add_months(date.fromisoformat(payload[-1]["ds"]), 1).isoformat(),
                request_kind=request_kind,
                input_digest=adapter_payload_digest(payload),
                output_sha256=output_sha256,
                output_rows=output_rows,
            )
        )
        return result

    def execution_receipt(self) -> LiveExecutionReceipt:
        receipt = LiveExecutionReceipt(
            runner_kind="timecopilot_live",
            execution_mode="zero_shot_forecast_only",
            adapter_class="timecopilot.models.foundation.chronos.Chronos",
            model_id=REFERENCE_MODEL_ID,
            model_alias="P105",
            package_versions=(
                ("timecopilot", _required_package_version("timecopilot")),
                (
                    "timecopilot-chronos-forecasting",
                    _required_package_version("timecopilot-chronos-forecasting"),
                ),
            ),
            network_policy=_live_network_policy(),
            cache_policy=_live_cache_policy(),
            call_receipts=tuple(self._call_receipts),
        )
        _validate_execution_receipt(receipt.as_record(), [
            {"origin": call.origin, "input_digest": call.input_digest}
            for call in self._call_receipts[::3]
        ])
        return receipt


def _load_live_adapter() -> _TimeCopilotForecastAdapter:
    """Construct the pinned public Chronos adapter for the live CLI path."""

    try:
        from timecopilot.models.foundation.chronos import Chronos
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise LiveDependencyError(f"reference adapter import failed: {type(exc).__name__}") from exc
    try:
        model = Chronos(repo_id=REFERENCE_MODEL_ID, batch_size=1, alias="P105")
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise LiveDependencyError(f"reference adapter construction failed: {type(exc).__name__}") from exc
    return _TimeCopilotForecastAdapter(model)


def _write_live_failure(
    root: Path,
    exc: BaseException,
    *,
    stage: str,
    classification: str,
) -> None:
    diagnostic = _diagnostic(
        classification=classification,
        scope="p1-06-live",
        stage=stage,
        reason=f"live {stage} failed: {type(exc).__name__}",
        exception_class=type(exc).__name__,
    )
    invalid = build_rolling_origin_evidence(
        None,
        repo_root=root,
        marker_state="invalid_final",
        classification=classification,
        diagnostics=(diagnostic,),
        errors=(f"live {stage} failed",),
    )
    path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
    staged = _stage_bytes(
        path,
        (json.dumps(invalid, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _marker_is_precise_publication_failure(root: Path) -> bool:
    try:
        evidence = json.loads(_repo_path(root, EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    diagnostics = evidence.get("non_pass_diagnostics") if isinstance(evidence, Mapping) else None
    return (
        isinstance(evidence, Mapping)
        and isinstance(evidence.get("publication_protocol"), Mapping)
        and evidence["publication_protocol"].get("marker_state") == "invalid_final"  # type: ignore[index,union-attr]
        and isinstance(diagnostics, list)
        and any(
            isinstance(item, Mapping) and item.get("scope") == "p1-06-publication"
            for item in diagnostics
        )
    )


def run_live_rolling_origin(repo_root: Path | None = None) -> dict[str, object]:
    """Run the pinned model through the public forecast-only boundary."""

    root = (repo_root or Path.cwd()).resolve()
    begin_rolling_origin_attempt(root)
    try:
        validate_p1_05_binding(_repo_path(root, P1_05_RELATIVE_PATH))
    except Exception as exc:
        _write_live_failure(root, exc, stage="binding", classification="fail")
        raise PublicationError("live rolling-origin binding failed") from exc
    try:
        rows = parse_target_csv(_repo_path(root, TARGET_RELATIVE_PATH))
        build_rolling_origin_schedule(rows)
    except Exception as exc:
        _write_live_failure(root, exc, stage="schedule", classification="fail")
        raise PublicationError("live rolling-origin schedule failed") from exc
    try:
        adapter = _load_live_adapter()
    except Exception as exc:
        classification = "blocked" if isinstance(exc, LiveDependencyError) else "fail"
        _write_live_failure(root, exc, stage="request", classification=classification)
        raise PublicationError("live rolling-origin adapter load failed") from exc
    try:
        result = run_rolling_origin_forecasts(rows, adapter)
        execution_receipt = adapter.execution_receipt()
    except Exception as exc:
        classification = "blocked" if isinstance(exc, LiveDependencyError) else "fail"
        stage = "request" if classification == "blocked" else "response"
        _write_live_failure(root, exc, stage=stage, classification=classification)
        raise PublicationError("live rolling-origin forecast failed") from exc
    try:
        return publish_rolling_origin_bundle(
            result,
            root,
            execution_receipt=execution_receipt,
        )
    except PublicationError:
        if not _marker_is_precise_publication_failure(root):
            _write_live_failure(
                root,
                PublicationError("publication failed"),
                stage="publication",
                classification="fail",
            )
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--validate-publication", action="store_true")
    parser.add_argument("--update-roadmap", action="store_true")
    parser.add_argument("--check-roadmap", action="store_true")
    parser.add_argument("--validate-consumer-gate", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.repo_root.resolve()
    try:
        if arguments.live:
            if not arguments.publish:
                raise PublicationError("--live requires --publish")
            run_live_rolling_origin(root)
        elif arguments.validate_publication or arguments.validate_consumer_gate:
            validate_rolling_origin_consumer_gate(root)
        elif arguments.update_roadmap:
            update_rolling_origin_roadmap(root)
        elif arguments.check_roadmap:
            if not validate_rolling_origin_roadmap_eligibility(root):
                raise PublicationError("P1-06 roadmap is not eligible")
        else:
            raise PublicationError("one rolling-origin action is required")
    except (RollingOriginError, OSError) as exc:
        print(f"rolling-origin: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by smoke/CLI tests
    raise SystemExit(main())
