"""Aggregate and per-horizon evaluation result construction."""

from __future__ import annotations

from typing import Sequence

from .errors import EvaluationInputError
from .metrics import calculate_interval_metrics, calculate_point_metrics, calculate_quantile_metrics
from .models import EvaluationConfig, EvaluationResults, EvaluationRow, GroupResult
from .normalization import finite_number


def _validate_normalized_rows(
    rows: Sequence[EvaluationRow], *, config: EvaluationConfig
) -> None:
    for row in rows:
        finite_number(row.actual, "actual")
        finite_number(row.point_forecast, "point_forecast")
        lower = finite_number(row.interval_lower, "interval lower")
        upper = finite_number(row.interval_upper, "interval upper")
        if lower > upper:
            raise EvaluationInputError("interval lower bound exceeds upper bound")
        if len(row.quantile_forecasts) != len(config.quantiles):
            raise EvaluationInputError("quantile forecast count differs from configuration")
        forecasts = tuple(
            finite_number(value, "quantile forecast") for value in row.quantile_forecasts
        )
        if tuple(sorted(forecasts)) != forecasts:
            raise EvaluationInputError("quantile forecasts cross")
        if tuple(field for field, _ in row.provenance) != config.provenance_fields:
            raise EvaluationInputError("normalized provenance differs from configuration")
    for field in config.provenance_fields:
        values = {row.provenance_value(field) for row in rows}
        if any(not value.strip() for value in values) or len(values) != 1:
            raise EvaluationInputError(f"inconsistent per-row provenance: {field}")


def calculate_group_result(
    rows: Sequence[EvaluationRow],
    *,
    group_type: str,
    group_value: int | None,
    config: EvaluationConfig,
) -> GroupResult:
    _validate_normalized_rows(rows, config=config)
    if group_type not in {"aggregate", "horizon"}:
        raise EvaluationInputError("group_type must be aggregate or horizon")
    expected = config.source_row_count if group_type == "aggregate" else config.expected_origin_count
    if len(rows) != expected:
        raise EvaluationInputError(f"{group_type} group has an invalid row count")
    if (group_type == "aggregate") != (group_value is None):
        raise EvaluationInputError("group value is inconsistent with group type")
    if group_type == "horizon" and group_value not in config.horizon_steps:
        raise EvaluationInputError("horizon group value is invalid")
    return {
        "group_type": group_type,
        "group_value": group_value,
        "row_count": len(rows),
        "point": calculate_point_metrics(rows),
        "interval": calculate_interval_metrics(rows, config=config),
        "quantiles": calculate_quantile_metrics(rows, config=config),
    }


def calculate_evaluation_results(
    rows: Sequence[EvaluationRow], *, config: EvaluationConfig
) -> EvaluationResults:
    """Return aggregate and ordered per-horizon results for normalized rows."""

    _validate_normalized_rows(rows, config=config)
    if len(rows) != config.source_row_count:
        raise EvaluationInputError("evaluation rows do not match the configured row count")
    identities = {(row.origin, row.forecast_horizon_step) for row in rows}
    origins = {row.origin for row in rows}
    expected = {(origin, horizon) for origin in origins for horizon in config.horizon_steps}
    if len(origins) != config.expected_origin_count or identities != expected:
        raise EvaluationInputError("evaluation identities do not form the configured grid")
    ordered = tuple(sorted(rows, key=lambda row: (row.origin, row.forecast_horizon_step)))
    return {
        "aggregate": calculate_group_result(
            ordered, group_type="aggregate", group_value=None, config=config
        ),
        "per_horizon": [
            calculate_group_result(
                [row for row in ordered if row.forecast_horizon_step == horizon],
                group_type="horizon",
                group_value=horizon,
                config=config,
            )
            for horizon in config.horizon_steps
        ],
    }
