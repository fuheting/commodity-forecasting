"""Forecast-only rolling-origin orchestration."""

from __future__ import annotations

import math
from typing import Sequence

from .contracts import (
    ForecastOnlyAdapter,
    ForecastOutputSchema,
    ForecastResponseError,
    ForecastRow,
    OriginRecord,
    ResponseColumns,
    RollingOriginConfig,
    RollingOriginError,
    RollingOriginResult,
    ScheduleContractError,
    TargetRowLike,
)
from .responses import adapter_payload, adapter_payload_digest, validate_responses
from .schedule import build_rolling_origin_schedule, validate_rolling_origin_schedule, validate_target_rows


def _numeric(value: object) -> float:
    if type(value) not in {int, float}:
        raise ForecastResponseError("forecast output must be numeric")
    return float(value)  # type: ignore[arg-type]


def run_rolling_origin_forecasts(
    rows: Sequence[TargetRowLike],
    adapter: ForecastOnlyAdapter,
    *,
    config: RollingOriginConfig,
    response_columns: ResponseColumns,
    output_schema: ForecastOutputSchema,
) -> RollingOriginResult:
    forecast = getattr(adapter, "forecast", None)
    if not callable(forecast):
        raise RollingOriginError("adapter must expose a public forecast method")
    target_rows = validate_target_rows(rows)
    if len(response_columns.quantiles) != len(output_schema.quantiles):
        raise RollingOriginError(
            "response quantiles must match the configured output columns"
        )
    schedule = build_rolling_origin_schedule(target_rows, config)
    validated = []
    quantiles = [value for value, _ in response_columns.quantiles]
    for window in schedule.windows:
        payload = adapter_payload(window.context_rows)
        digest = adapter_payload_digest(payload)
        if payload[-1]["ds"] != window.cutoff.isoformat():
            raise ScheduleContractError("maximum adapter input timestamp must equal cutoff")
        point_response = forecast(payload, h=config.forecast_months)
        interval_response = forecast(payload, h=config.forecast_months, level=[response_columns.interval_level])
        quantile_response = forecast(payload, h=config.forecast_months, quantiles=quantiles)
        responses = validate_responses(window, point_response, interval_response, quantile_response, response_columns)
        validated.append((window, digest, responses))

    # Future actuals are intentionally unavailable to the adapter and joined only
    # after every response has passed reconciliation.
    actual_by_month = {row.ds: float(row.y) for row in target_rows}
    origins: list[OriginRecord] = []
    for window, digest, responses in validated:
        output_rows = []
        for index, forecast_month in enumerate(window.forecast_months):
            output_rows.append(ForecastRow((
                window.origin.isoformat(), window.cutoff.isoformat(),
                window.historic_context_start.isoformat(), window.historic_context_end.isoformat(),
                forecast_month.isoformat(), index + 1, actual_by_month[forecast_month],
                responses.point[index], responses.lower[index], responses.upper[index],
                *responses.quantiles[index],
                *(value for _, value in output_schema.static_fields),
            ), output_schema.columns))
        origins.append(OriginRecord(window, digest, tuple(output_rows)))
    result = RollingOriginResult(schedule, tuple(origins))
    validate_rolling_origin_result(result, output_schema=output_schema)
    return result


def validate_rolling_origin_result(
    result: RollingOriginResult, *, output_schema: ForecastOutputSchema
) -> None:
    validate_rolling_origin_schedule(result.schedule)
    config = result.schedule.config
    if len(result.origins) != config.origin_count or len(result.rows) != config.origin_count * config.forecast_months:
        raise ForecastResponseError("rolling-origin result shape differs from configuration")
    for origin in result.origins:
        if len(origin.rows) != config.forecast_months:
            raise ForecastResponseError("origin result row count differs from forecast horizon")
        for expected_step, row in enumerate(origin.rows, start=1):
            record = row.as_dict()
            if tuple(record) != output_schema.columns:
                raise ForecastResponseError("forecast row does not match the output schema")
            expected = {
                "origin": origin.window.origin.isoformat(),
                "cutoff": origin.window.cutoff.isoformat(),
                "historic_context_start": origin.window.historic_context_start.isoformat(),
                "historic_context_end": origin.window.historic_context_end.isoformat(),
                "forecast_month": origin.window.forecast_months[expected_step - 1].isoformat(),
                "forecast_horizon_step": expected_step,
                **dict(output_schema.static_fields),
            }
            for column, value in expected.items():
                if record[column] != value:
                    raise ForecastResponseError(f"forecast row metadata is invalid: {column}")
            numeric_columns = (
                "actual",
                output_schema.point,
                output_schema.interval_lower,
                output_schema.interval_upper,
                *output_schema.quantiles,
            )
            if any(
                not math.isfinite(_numeric(record[column]))
                for column in numeric_columns
            ):
                raise ForecastResponseError("all forecast and actual values must be finite numeric values")
            quantiles = tuple(
                _numeric(record[column]) for column in output_schema.quantiles
            )
            if quantiles != tuple(sorted(quantiles)):
                raise ForecastResponseError("forecast quantiles cross")
            if _numeric(record[output_schema.interval_lower]) > _numeric(
                record[output_schema.interval_upper]
            ):
                raise ForecastResponseError("interval lower bound exceeds upper bound")
