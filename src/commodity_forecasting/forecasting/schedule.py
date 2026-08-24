"""Leakage-safe monthly rolling-origin schedule construction."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from typing import Sequence

from .contracts import (
    OriginWindow,
    RollingOriginConfig,
    RollingOriginSchedule,
    ScheduleContractError,
    TargetRowLike,
)


def add_months(value: date, offset: int) -> date:
    if value.day != 1:
        raise ScheduleContractError("monthly timestamps must be month-start dates")
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def validate_target_rows(rows: Sequence[TargetRowLike]) -> tuple[TargetRowLike, ...]:
    normalized = tuple(rows)
    if not normalized:
        raise ScheduleContractError("monthly target must not be empty")
    if len({row.unique_id for row in normalized}) != 1:
        raise ScheduleContractError("monthly target must contain exactly one unique_id")
    dates = tuple(row.ds for row in normalized)
    if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
        raise ScheduleContractError("monthly target timestamps must be unique and ordered")
    if any(current != add_months(previous, 1) for previous, current in zip(dates, dates[1:])):
        raise ScheduleContractError("monthly target timestamps must be contiguous")
    for row in normalized:
        try:
            numeric = float(row.y)
        except (TypeError, ValueError) as exc:
            raise ScheduleContractError("monthly target values must be numeric") from exc
        if not math.isfinite(numeric):
            raise ScheduleContractError("monthly target values must be finite")
    return normalized


def build_rolling_origin_schedule(
    rows: Sequence[TargetRowLike], config: RollingOriginConfig
) -> RollingOriginSchedule:
    target_rows = validate_target_rows(rows)
    by_date = {row.ds: row for row in target_rows}
    target_end = target_rows[-1].ds
    latest_origin = add_months(target_end, -(config.forecast_months - 1))
    origins = tuple(
        add_months(latest_origin, -config.step_months * offset)
        for offset in reversed(range(config.origin_count))
    )
    windows: list[OriginWindow] = []
    for origin in origins:
        cutoff = add_months(origin, -1)
        context_start = add_months(cutoff, -(config.context_months - 1))
        context_dates = tuple(add_months(context_start, offset) for offset in range(config.context_months))
        forecast_dates = tuple(add_months(origin, offset) for offset in range(config.forecast_months))
        try:
            context = tuple(by_date[value] for value in context_dates)
            for value in forecast_dates:
                by_date[value]
        except KeyError as exc:
            raise ScheduleContractError(f"target is missing required month {exc.args[0]}") from exc
        windows.append(
            OriginWindow(origin, cutoff, context_start, cutoff, forecast_dates[0], forecast_dates[-1], context, forecast_dates)
        )
    schedule = RollingOriginSchedule(target_end, tuple(windows), config)
    validate_rolling_origin_schedule(schedule)
    return schedule


def validate_rolling_origin_schedule(schedule: RollingOriginSchedule) -> None:
    config = schedule.config
    if len(schedule.windows) != config.origin_count:
        raise ScheduleContractError("schedule origin count differs from configuration")
    if config.expected_origins is not None and schedule.origins != config.expected_origins:
        raise ScheduleContractError("derived origins differ from the configured schedule")
    if config.expected_cutoffs is not None and schedule.cutoffs != config.expected_cutoffs:
        raise ScheduleContractError("derived cutoffs differ from the configured schedule")
    if config.expected_target_end is not None and schedule.target_end != config.expected_target_end:
        raise ScheduleContractError("target endpoint differs from the configured endpoint")
    for window in schedule.windows:
        if len(window.context_rows) != config.context_months:
            raise ScheduleContractError("historic context row count differs from configuration")
        if len(window.forecast_months) != config.forecast_months:
            raise ScheduleContractError("forecast row count differs from configuration")
        if window.context_rows[0].ds != window.historic_context_start or window.context_rows[-1].ds != window.cutoff:
            raise ScheduleContractError("historic context bounds do not match its rows")
        if any(row.ds >= window.origin for row in window.context_rows):
            raise ScheduleContractError("historic context contains post-cutoff data")
        expected = tuple(add_months(window.origin, offset) for offset in range(config.forecast_months))
        if window.forecast_months != expected or window.forecast_end != expected[-1]:
            raise ScheduleContractError("forecast span is not contiguous")
        if window.forecast_end > schedule.target_end:
            raise ScheduleContractError("forecast span exceeds the final actual month")


def schedule_digest(schedule: RollingOriginSchedule) -> str:
    validate_rolling_origin_schedule(schedule)
    payload = json.dumps(schedule.as_record(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
