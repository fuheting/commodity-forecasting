"""Reusable, leakage-safe forecasting and backtesting primitives."""

from .contracts import (
    BASE_OUTPUT_COLUMNS,
    ForecastOnlyAdapter,
    ForecastOutputSchema,
    ForecastResponseError,
    OriginRecord,
    OriginWindow,
    ResponseColumns,
    RollingOriginConfig,
    RollingOriginError,
    RollingOriginResult,
    RollingOriginSchedule,
    ScheduleContractError,
)
from .orchestration import run_rolling_origin_forecasts, validate_rolling_origin_result
from .schedule import add_months, build_rolling_origin_schedule, validate_rolling_origin_schedule
from .serialization import serialize_rolling_origin_csv

__all__ = [
    "BASE_OUTPUT_COLUMNS",
    "ForecastOnlyAdapter",
    "ForecastOutputSchema",
    "ForecastResponseError",
    "OriginRecord",
    "OriginWindow",
    "ResponseColumns",
    "RollingOriginConfig",
    "RollingOriginError",
    "RollingOriginResult",
    "RollingOriginSchedule",
    "ScheduleContractError",
    "add_months",
    "build_rolling_origin_schedule",
    "run_rolling_origin_forecasts",
    "serialize_rolling_origin_csv",
    "validate_rolling_origin_result",
    "validate_rolling_origin_schedule",
]
