"""Contracts shared by rolling-origin schedule and forecast orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Protocol, Sequence, runtime_checkable


BASE_OUTPUT_COLUMNS = (
    "origin",
    "cutoff",
    "historic_context_start",
    "historic_context_end",
    "forecast_month",
    "forecast_horizon_step",
    "actual",
)


class RollingOriginError(RuntimeError):
    """Raised when a rolling-origin contract is violated."""


class ScheduleContractError(RollingOriginError):
    """Raised when target rows cannot form the requested schedule."""


class ForecastResponseError(RollingOriginError):
    """Raised when an adapter response violates the output contract."""


class TargetRowLike(Protocol):
    @property
    def unique_id(self) -> str: ...

    @property
    def ds(self) -> date: ...

    @property
    def y(self) -> str: ...


@runtime_checkable
class ForecastOnlyAdapter(Protocol):
    def forecast(
        self,
        payload: Sequence[Mapping[str, str]],
        *,
        h: int,
        level: Sequence[int] | None = None,
        quantiles: Sequence[float] | None = None,
    ) -> object:
        """Return forecasts without fitting or updating model state."""


@dataclass(frozen=True)
class RollingOriginConfig:
    context_months: int
    forecast_months: int
    origin_count: int
    step_months: int = 1
    expected_target_end: date | None = None
    expected_origins: tuple[date, ...] | None = None
    expected_cutoffs: tuple[date, ...] | None = None

    def __post_init__(self) -> None:
        if min(self.context_months, self.forecast_months, self.origin_count, self.step_months) < 1:
            raise ValueError("rolling-origin dimensions must be positive")
        if self.expected_origins is not None and len(self.expected_origins) != self.origin_count:
            raise ValueError("expected origins must match origin_count")
        if self.expected_cutoffs is not None and len(self.expected_cutoffs) != self.origin_count:
            raise ValueError("expected cutoffs must match origin_count")


@dataclass(frozen=True)
class ResponseColumns:
    point: str
    interval_lower: str
    interval_upper: str
    quantiles: tuple[tuple[float, str], ...]
    interval_level: int = 80

    def __post_init__(self) -> None:
        values = tuple(value for value, _ in self.quantiles)
        if not values or values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("quantile probabilities must be unique and ordered")
        if any(value <= 0 or value >= 1 for value in values):
            raise ValueError("quantile probabilities must be between zero and one")


@dataclass(frozen=True)
class ForecastOutputSchema:
    """Explicit output names and caller-owned static provenance fields."""

    point: str
    interval_lower: str
    interval_upper: str
    quantiles: tuple[str, ...]
    static_fields: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        configured = (
            self.point,
            self.interval_lower,
            self.interval_upper,
            *self.quantiles,
            *(name for name, _ in self.static_fields),
        )
        if not self.quantiles or any(not name for name in configured):
            raise ValueError("forecast output names must be non-empty")
        if len(set(configured)) != len(configured):
            raise ValueError("forecast output names must be unique")
        if set(configured).intersection(BASE_OUTPUT_COLUMNS):
            raise ValueError("forecast output names must not replace core columns")

    @property
    def columns(self) -> tuple[str, ...]:
        return (
            *BASE_OUTPUT_COLUMNS,
            self.point,
            self.interval_lower,
            self.interval_upper,
            *self.quantiles,
            *(name for name, _ in self.static_fields),
        )


@dataclass(frozen=True)
class OriginWindow:
    origin: date
    cutoff: date
    historic_context_start: date
    historic_context_end: date
    forecast_start: date
    forecast_end: date
    context_rows: tuple[TargetRowLike, ...]
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
    config: RollingOriginConfig

    @property
    def origins(self) -> tuple[date, ...]:
        return tuple(window.origin for window in self.windows)

    @property
    def cutoffs(self) -> tuple[date, ...]:
        return tuple(window.cutoff for window in self.windows)

    def as_record(self) -> dict[str, object]:
        config = self.config
        return {
            "origin_count": config.origin_count,
            "step_months": config.step_months,
            "historic_context_months": config.context_months,
            "forecast_months": config.forecast_months,
            "origin_months": [value.isoformat() for value in self.origins],
            "cutoff_months": [value.isoformat() for value in self.cutoffs],
            "historic_context_spans": [
                {
                    "origin": window.origin.isoformat(),
                    "start": window.historic_context_start.isoformat(),
                    "end": window.historic_context_end.isoformat(),
                    "month_count": config.context_months,
                }
                for window in self.windows
            ],
            "forecast_spans": [
                {
                    "origin": window.origin.isoformat(),
                    "start": window.forecast_start.isoformat(),
                    "end": window.forecast_end.isoformat(),
                    "month_count": config.forecast_months,
                }
                for window in self.windows
            ],
        }


@dataclass(frozen=True)
class ForecastRow:
    values: tuple[object, ...]
    columns: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return dict(zip(self.columns, self.values, strict=True))


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
