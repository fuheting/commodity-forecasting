"""Adapter request construction and response reconciliation."""

from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping, Sequence

from .contracts import ForecastResponseError, OriginWindow, ResponseColumns, RollingOriginError, TargetRowLike

ADAPTER_PAYLOAD_COLUMNS = ("unique_id", "ds", "y")
AdapterRow = dict[str, str]


@dataclass(frozen=True)
class ValidatedResponses:
    point: tuple[float, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    quantiles: tuple[tuple[float, ...], ...]


def adapter_payload(rows: Sequence[TargetRowLike]) -> tuple[AdapterRow, ...]:
    return tuple({"unique_id": row.unique_id, "ds": row.ds.isoformat(), "y": row.y} for row in rows)


def adapter_payload_digest(payload: Sequence[Mapping[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=ADAPTER_PAYLOAD_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in payload:
        if tuple(row.keys()) != ADAPTER_PAYLOAD_COLUMNS:
            raise RollingOriginError("adapter payload columns must be exactly unique_id, ds, y")
        writer.writerow(row)
    return hashlib.sha256(buffer.getvalue().encode("utf-8")).hexdigest()


def collect_origin_request_digests(window: OriginWindow) -> dict[str, str]:
    digest = adapter_payload_digest(adapter_payload(window.context_rows))
    return {
        "input_digest": digest,
        "point_input_digest": digest,
        "interval_input_digest": digest,
        "quantile_input_digest": digest,
    }


def response_records(response: object) -> tuple[Mapping[str, object], ...]:
    if hasattr(response, "to_dict"):
        response = response.to_dict("records")  # type: ignore[call-arg,union-attr]
    if not isinstance(response, Sequence) or isinstance(response, (str, bytes, bytearray)):
        raise ForecastResponseError("adapter response must be a sequence of row mappings")
    records = tuple(response)
    if any(not isinstance(row, Mapping) for row in records):
        raise ForecastResponseError("every adapter response row must be a mapping")
    return records  # type: ignore[return-value]


def finite_value(row: Mapping[str, object], column: str) -> float:
    raw = row.get(column)
    if type(raw) not in {int, float}:
        raise ForecastResponseError(f"response column {column} must be numeric")
    value = float(raw)  # type: ignore[arg-type]
    if not math.isfinite(value):
        raise ForecastResponseError(f"response column {column} must be finite")
    return value


def reconcile_response(
    response: object, window: OriginWindow, required_columns: Sequence[str]
) -> tuple[Mapping[str, object], ...]:
    records = response_records(response)
    if len(records) != len(window.forecast_months):
        raise ForecastResponseError("adapter response row count must equal the forecast horizon")
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
            finite_value(row, column)
    expected = tuple(value.isoformat() for value in window.forecast_months)
    if tuple(sorted(by_timestamp)) != expected:
        raise ForecastResponseError("adapter response timestamps do not match the forecast span")
    return tuple(by_timestamp[value] for value in expected)


def validate_responses(
    window: OriginWindow,
    point_response: object,
    interval_response: object,
    quantile_response: object,
    columns: ResponseColumns,
) -> ValidatedResponses:
    point_rows = reconcile_response(point_response, window, (columns.point,))
    interval_rows = reconcile_response(interval_response, window, (columns.interval_lower, columns.interval_upper))
    quantile_names = tuple(column for _, column in columns.quantiles)
    quantile_rows = reconcile_response(quantile_response, window, quantile_names)
    points = tuple(finite_value(row, columns.point) for row in point_rows)
    lowers = tuple(finite_value(row, columns.interval_lower) for row in interval_rows)
    uppers = tuple(finite_value(row, columns.interval_upper) for row in interval_rows)
    quantiles = tuple(tuple(finite_value(row, column) for column in quantile_names) for row in quantile_rows)
    if any(lower > upper for lower, upper in zip(lowers, uppers)):
        raise ForecastResponseError("interval lower bound exceeds upper bound")
    if any(values != tuple(sorted(values)) for values in quantiles):
        raise ForecastResponseError("forecast quantiles cross")
    return ValidatedResponses(points, lowers, uppers, quantiles)
