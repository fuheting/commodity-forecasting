"""Machine-readable description of an evaluation configuration."""

from __future__ import annotations

from .models import EvaluationConfig


def describe_evaluation_contract(config: EvaluationConfig) -> dict[str, object]:
    return {
        "source_row_count": config.source_row_count,
        "origin_count": config.expected_origin_count,
        "horizon_steps": list(config.horizon_steps),
        "interval_level": config.interval_level,
        "quantiles": list(config.quantiles),
        "point_metrics": ["mae", "rmse"],
        "interval_metrics": ["empirical_coverage", "mean_width"],
        "quantile_metrics": ["mean_pinball_loss", "empirical_coverage"],
        "interval_coverage_rule": "lower <= actual <= upper",
        "quantile_coverage_rule": "actual <= quantile_forecast",
        "group_order": ["aggregate", *(f"horizon_{step}" for step in config.horizon_steps)],
    }
