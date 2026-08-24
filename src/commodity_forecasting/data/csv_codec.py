"""Canonical CSV codec for monthly target rows."""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from typing import Sequence

from .target import (
    MonthlyTargetContract,
    TargetDataError,
    TargetRow,
    validate_rows,
    validate_serialized_numeric,
)

CSV_FIELDS = ("unique_id", "ds", "y")


class TargetCsvError(TargetDataError):
    """Raised when target CSV bytes violate the canonical codec contract."""


def serialize_target_csv(rows: Sequence[TargetRow]) -> bytes:
    """Return deterministic target-only CSV bytes."""

    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for row in rows:
        writer.writerow((row.unique_id, row.ds.isoformat(), row.y))
    return stream.getvalue().encode("utf-8")


def parse_target_csv_bytes(
    content: bytes,
    contract: MonthlyTargetContract,
) -> tuple[TargetRow, ...]:
    """Parse and validate canonical UTF-8 target CSV bytes."""

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TargetCsvError("target CSV is not valid UTF-8") from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise TargetCsvError("target CSV is empty") from exc
    if header != list(CSV_FIELDS):
        raise TargetCsvError("target CSV has the wrong schema")
    rows: list[TargetRow] = []
    try:
        for values in reader:
            if len(values) != len(CSV_FIELDS):
                raise TargetCsvError("target CSV row has the wrong width")
            unique_id, ds_text, y = values
            ds = date.fromisoformat(ds_text)
            if ds.isoformat() != ds_text or ds.day != 1:
                raise TargetCsvError("published ds must be a first-of-month ISO date")
            validate_serialized_numeric(y)
            rows.append(TargetRow(unique_id, ds, y))
        validate_rows(rows, contract)
    except (ValueError, TargetDataError) as exc:
        if isinstance(exc, TargetCsvError):
            raise
        raise TargetCsvError("target CSV violates the monthly target contract") from exc
    parsed = tuple(rows)
    if serialize_target_csv(parsed) != content:
        raise TargetCsvError("target CSV serialization is not canonical")
    return parsed


def read_target_csv(path: Path, contract: MonthlyTargetContract) -> tuple[TargetRow, ...]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise TargetCsvError(f"target CSV is unreadable: {path}") from exc
    return parse_target_csv_bytes(content, contract)
