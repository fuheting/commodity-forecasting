"""Reusable deterministic forecast evaluation."""

from .contract import describe_evaluation_contract
from .errors import EvaluationInputError
from .grouping import calculate_evaluation_results, calculate_group_result
from .metrics import (
    calculate_interval_metrics,
    calculate_point_metrics,
    calculate_quantile_metrics,
    empirical_quantile_coverage,
    interval_metrics,
    mean_absolute_error,
    mean_pinball_loss,
    pinball_loss,
    root_mean_squared_error,
)
from .models import (
    EvaluationConfig,
    EvaluationResults,
    EvaluationRow,
    GroupResult,
    IntervalMetrics,
    PointMetrics,
    QuantileMetrics,
)
from .normalization import normalize_evaluation_rows, parse_evaluation_csv

__all__ = [
    "EvaluationConfig",
    "EvaluationInputError",
    "EvaluationResults",
    "EvaluationRow",
    "GroupResult",
    "IntervalMetrics",
    "PointMetrics",
    "QuantileMetrics",
    "calculate_evaluation_results",
    "calculate_group_result",
    "calculate_interval_metrics",
    "calculate_point_metrics",
    "calculate_quantile_metrics",
    "describe_evaluation_contract",
    "empirical_quantile_coverage",
    "interval_metrics",
    "mean_absolute_error",
    "mean_pinball_loss",
    "normalize_evaluation_rows",
    "parse_evaluation_csv",
    "pinball_loss",
    "root_mean_squared_error",
]
