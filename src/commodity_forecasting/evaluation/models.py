"""Input and result contracts for forecast evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from .errors import EvaluationInputError


@dataclass(frozen=True)
class EvaluationConfig:
    """Explicit schema and grouping assumptions for one evaluation run."""

    source_columns: tuple[str, ...]
    quantile_columns: tuple[str, ...]
    quantiles: tuple[float, ...]
    horizon_steps: tuple[int, ...]
    expected_origin_count: int
    interval_level: int
    interval_lower_column: str
    interval_upper_column: str
    provenance_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_columns or len(set(self.source_columns)) != len(self.source_columns):
            raise EvaluationInputError("source columns must be non-empty and unique")
        required_columns = {"origin", "forecast_horizon_step", "actual", "point_forecast"}
        if not required_columns.issubset(self.source_columns):
            raise EvaluationInputError("source columns omit required evaluation fields")
        if not self.quantile_columns or len(self.quantile_columns) != len(self.quantiles):
            raise EvaluationInputError("quantile columns and levels must be non-empty and equal length")
        if any(column not in self.source_columns for column in self.quantile_columns):
            raise EvaluationInputError("quantile columns must be present in source columns")
        if tuple(sorted(self.quantiles)) != self.quantiles or any(
            not 0.0 < quantile < 1.0 for quantile in self.quantiles
        ):
            raise EvaluationInputError("quantiles must be strictly increasing between zero and one")
        if not self.horizon_steps or len(set(self.horizon_steps)) != len(self.horizon_steps):
            raise EvaluationInputError("horizon steps must be non-empty and unique")
        if self.expected_origin_count < 1:
            raise EvaluationInputError("expected origin count must be positive")
        if not 0 < self.interval_level < 100:
            raise EvaluationInputError("interval level must be between zero and 100")
        if self.interval_lower_column not in self.source_columns or self.interval_upper_column not in self.source_columns:
            raise EvaluationInputError("interval columns must be present in source columns")
        if any(field not in self.source_columns for field in self.provenance_fields):
            raise EvaluationInputError("provenance fields must be present in source columns")

    @property
    def source_row_count(self) -> int:
        return self.expected_origin_count * len(self.horizon_steps)


@dataclass(frozen=True)
class EvaluationRow:
    """Normalized numeric fields required for one origin/horizon row."""

    origin: str
    forecast_horizon_step: int
    actual: float
    point_forecast: float
    interval_lower: float
    interval_upper: float
    quantile_forecasts: tuple[float, ...]
    provenance: tuple[tuple[str, str], ...] = ()

    def provenance_value(self, field: str) -> str:
        try:
            return dict(self.provenance)[field]
        except KeyError as exc:
            raise EvaluationInputError(f"missing normalized provenance field: {field}") from exc


class PointMetrics(TypedDict):
    mae: float
    rmse: float


class IntervalMetrics(TypedDict):
    level: int
    empirical_coverage: float
    mean_width: float


class QuantileMetrics(TypedDict):
    quantile: float
    mean_pinball_loss: float
    empirical_coverage: float


class GroupResult(TypedDict):
    group_type: str
    group_value: int | None
    row_count: int
    point: PointMetrics
    interval: IntervalMetrics
    quantiles: list[QuantileMetrics]


class EvaluationResults(TypedDict):
    aggregate: GroupResult
    per_horizon: list[GroupResult]
