"""Schema validation and normalization for forecast evaluation rows."""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime
from typing import Mapping, Sequence, cast

from .errors import EvaluationInputError
from .models import EvaluationConfig, EvaluationRow


def finite_number(value: object, field: str) -> float:
    try:
        number = float(cast(str | int | float, value))
    except (TypeError, ValueError) as exc:
        raise EvaluationInputError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise EvaluationInputError(f"{field} must be finite")
    return number


def nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError(f"{field} must be a non-empty string")
    return value


def normalize_evaluation_rows(
    rows: Sequence[Mapping[str, object]], *, config: EvaluationConfig
) -> tuple[EvaluationRow, ...]:
    """Validate and normalize the complete configured origin/horizon grid."""

    if len(rows) != config.source_row_count:
        raise EvaluationInputError(
            f"evaluation input must contain exactly {config.source_row_count} rows"
        )
    normalized: list[EvaluationRow] = []
    identities: set[tuple[str, int]] = set()
    for raw in rows:
        if set(raw) != set(config.source_columns):
            raise EvaluationInputError("evaluation input columns differ from the configured schema")
        if any(value is None or (isinstance(value, str) and not value.strip()) for value in raw.values()):
            raise EvaluationInputError("evaluation input contains an empty required value")
        origin = nonempty_string(raw.get("origin"), "origin")
        try:
            datetime.strptime(origin, "%Y-%m-%d")
        except ValueError as exc:
            raise EvaluationInputError("origin must be an ISO date") from exc
        horizon_number = finite_number(raw.get("forecast_horizon_step"), "forecast_horizon_step")
        if not horizon_number.is_integer():
            raise EvaluationInputError("forecast_horizon_step must be an integer")
        horizon = int(horizon_number)
        if horizon not in config.horizon_steps:
            raise EvaluationInputError("forecast_horizon_step is not configured")
        identity = (origin, horizon)
        if identity in identities:
            raise EvaluationInputError("duplicate (origin, forecast_horizon_step) identity")
        identities.add(identity)
        lower = finite_number(raw.get(config.interval_lower_column), "interval lower")
        upper = finite_number(raw.get(config.interval_upper_column), "interval upper")
        if lower > upper:
            raise EvaluationInputError("interval lower bound exceeds upper bound")
        forecasts = tuple(
            finite_number(raw.get(column), column) for column in config.quantile_columns
        )
        if tuple(sorted(forecasts)) != forecasts:
            raise EvaluationInputError("quantile forecasts cross")
        normalized.append(
            EvaluationRow(
                origin=origin,
                forecast_horizon_step=horizon,
                actual=finite_number(raw.get("actual"), "actual"),
                point_forecast=finite_number(raw.get("point_forecast"), "point_forecast"),
                interval_lower=lower,
                interval_upper=upper,
                quantile_forecasts=forecasts,
                provenance=tuple(
                    (field, nonempty_string(raw.get(field), field))
                    for field in config.provenance_fields
                ),
            )
        )
    origins = sorted({row.origin for row in normalized})
    if len(origins) != config.expected_origin_count:
        raise EvaluationInputError(
            f"evaluation input must contain exactly {config.expected_origin_count} origins"
        )
    expected_grid = {
        (origin, horizon) for origin in origins for horizon in config.horizon_steps
    }
    if identities != expected_grid:
        raise EvaluationInputError("evaluation identities do not form the configured grid")
    for field in config.provenance_fields:
        if len({row.provenance_value(field) for row in normalized}) != 1:
            raise EvaluationInputError(f"inconsistent per-row provenance: {field}")
    return tuple(sorted(normalized, key=lambda row: (row.origin, row.forecast_horizon_step)))


def parse_evaluation_csv(
    payload: str | bytes, *, config: EvaluationConfig
) -> tuple[EvaluationRow, ...]:
    """Parse evaluation CSV using the configured closed schema."""

    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != config.source_columns:
        raise EvaluationInputError("evaluation input columns differ from the configured schema")
    return normalize_evaluation_rows(list(reader), config=config)
