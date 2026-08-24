"""Deterministic rolling-origin forecast CSV serialization."""

from __future__ import annotations

import csv
import io

from .contracts import RollingOriginResult


def serialize_rolling_origin_csv(
    result: RollingOriginResult, *, columns: tuple[str, ...]
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(row.as_dict() for row in result.rows)
    return buffer.getvalue().encode("utf-8")
