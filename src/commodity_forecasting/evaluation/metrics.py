"""Deterministic point, interval, and quantile metrics."""

from __future__ import annotations

import math
from typing import Sequence

from .errors import EvaluationInputError
from .models import EvaluationConfig, EvaluationRow, IntervalMetrics, PointMetrics, QuantileMetrics
from .normalization import finite_number


def _paired_values(actuals: Sequence[float], forecasts: Sequence[float]) -> tuple[tuple[float, float], ...]:
    if not actuals or len(actuals) != len(forecasts):
        raise EvaluationInputError("metric inputs must be non-empty and equal length")
    return tuple(
        (finite_number(actual, "actual"), finite_number(forecast, "forecast"))
        for actual, forecast in zip(actuals, forecasts)
    )


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
        y = finite_number(actual, "actual")
        lo = finite_number(lower, "interval lower")
        hi = finite_number(upper, "interval upper")
        if lo > hi:
            raise EvaluationInputError("interval lower bound exceeds upper bound")
        covered += int(lo <= y <= hi)
        widths += hi - lo
    return covered / len(actuals), widths / len(actuals)


def pinball_loss(actual: float, forecast: float, quantile: float) -> float:
    q = finite_number(quantile, "quantile")
    if not 0.0 < q < 1.0:
        raise EvaluationInputError("quantile must be strictly between zero and one")
    residual = finite_number(actual, "actual") - finite_number(forecast, "quantile forecast")
    return max(q * residual, (q - 1.0) * residual)


def mean_pinball_loss(actuals: Sequence[float], forecasts: Sequence[float], quantile: float) -> float:
    pairs = _paired_values(actuals, forecasts)
    return sum(pinball_loss(actual, forecast, quantile) for actual, forecast in pairs) / len(pairs)


def empirical_quantile_coverage(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    pairs = _paired_values(actuals, forecasts)
    return sum(int(actual <= forecast) for actual, forecast in pairs) / len(pairs)


def calculate_point_metrics(rows: Sequence[EvaluationRow]) -> PointMetrics:
    if not rows:
        raise EvaluationInputError("point metric group must not be empty")
    return {
        "mae": mean_absolute_error([row.actual for row in rows], [row.point_forecast for row in rows]),
        "rmse": root_mean_squared_error([row.actual for row in rows], [row.point_forecast for row in rows]),
    }


def calculate_interval_metrics(rows: Sequence[EvaluationRow], *, config: EvaluationConfig) -> IntervalMetrics:
    if not rows:
        raise EvaluationInputError("interval metric group must not be empty")
    coverage, width = interval_metrics(
        [row.actual for row in rows],
        [row.interval_lower for row in rows],
        [row.interval_upper for row in rows],
    )
    return {"level": config.interval_level, "empirical_coverage": coverage, "mean_width": width}


def calculate_quantile_metrics(rows: Sequence[EvaluationRow], *, config: EvaluationConfig) -> list[QuantileMetrics]:
    if not rows:
        raise EvaluationInputError("quantile metric group must not be empty")
    actuals = [row.actual for row in rows]
    records: list[QuantileMetrics] = []
    for index, quantile in enumerate(config.quantiles):
        forecasts = [row.quantile_forecasts[index] for row in rows]
        records.append(
            {
                "quantile": quantile,
                "mean_pinball_loss": mean_pinball_loss(actuals, forecasts, quantile),
                "empirical_coverage": empirical_quantile_coverage(actuals, forecasts),
            }
        )
    return records
