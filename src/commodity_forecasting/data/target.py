"""Dataset-independent monthly target contracts and validation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Sequence


class TargetDataError(RuntimeError):
    """Base error for target preparation failures."""


class TargetSelectionError(TargetDataError):
    """Raised when the configured target cannot be selected exactly once."""


class InvalidTimestampError(TargetDataError):
    """Raised when a timestamp violates the monthly target contract."""


class InvalidTargetValueError(TargetDataError):
    """Raised when a target value is not a canonical finite numeric."""


@dataclass(frozen=True)
class MonthlyTargetContract:
    """Expected identity and calendar extent of a monthly target series."""

    unique_id: str
    period_start: str
    period_end: str
    period_count: int


@dataclass(frozen=True)
class TargetRow:
    unique_id: str
    ds: date
    y: str


@dataclass(frozen=True)
class TargetObservation:
    rows: tuple[TargetRow, ...]
    header_row: int
    target_column_index: int
    period_start: str
    period_end: str
    source_sha256_before: str
    source_sha256_after: str


def serialize_numeric(value: object) -> str:
    """Serialize a finite source numeric without imposing display formatting."""

    if type(value) not in {int, float}:
        raise InvalidTargetValueError("target value must be a finite int or float")
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidTargetValueError("target value must be finite")
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidTargetValueError("target value is not a valid decimal") from exc
    if not decimal_value.is_finite():
        raise InvalidTargetValueError("target value must be finite")
    return format(decimal_value, "f")


def validate_serialized_numeric(value: str) -> None:
    """Require the canonical finite-decimal representation used in target CSVs."""

    if not value:
        raise InvalidTargetValueError("serialized target must be non-empty")
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as exc:
        raise InvalidTargetValueError("serialized target is not numeric") from exc
    if not decimal_value.is_finite() or format(decimal_value, "f") != value:
        raise InvalidTargetValueError("serialized target must be a canonical finite decimal")


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def validate_rows(rows: Sequence[TargetRow], contract: MonthlyTargetContract) -> None:
    """Validate identity, numeric values, and a complete contiguous monthly extent."""

    if len(rows) != contract.period_count:
        raise InvalidTimestampError(
            f"expected {contract.period_count} monthly rows, found {len(rows)}"
        )
    dates = [row.ds for row in rows]
    if len(set(dates)) != len(dates) or dates != sorted(dates):
        raise InvalidTimestampError("monthly timestamps must be unique and strictly ordered")
    for previous, current in zip(dates, dates[1:]):
        if current != _next_month(previous):
            raise InvalidTimestampError("monthly timestamps must be contiguous calendar months")
    if not dates:
        raise InvalidTimestampError("monthly target must contain at least one row")
    if f"{dates[0].year:04d}M{dates[0].month:02d}" != contract.period_start:
        raise InvalidTimestampError(f"first period must be {contract.period_start}")
    if f"{dates[-1].year:04d}M{dates[-1].month:02d}" != contract.period_end:
        raise InvalidTimestampError(f"last period must be {contract.period_end}")
    if any(row.unique_id != contract.unique_id for row in rows):
        raise TargetDataError("every row must use the configured unique_id")
    for row in rows:
        validate_serialized_numeric(row.y)
