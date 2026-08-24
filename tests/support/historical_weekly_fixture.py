"""Deterministic weekly fixture helpers for historical capability tests."""

from __future__ import annotations

import hashlib


def weekly_target_rows() -> list[dict[str, str]]:
    """Return the historical synthetic weekly target rows."""

    return [
        {"unique_id": "synthetic_target", "ds": "2026-01-02", "y": "100.0"},
        {"unique_id": "synthetic_target", "ds": "2026-01-09", "y": "101.5"},
        {"unique_id": "synthetic_target", "ds": "2026-01-16", "y": "101.0"},
        {"unique_id": "synthetic_target", "ds": "2026-01-23", "y": "103.0"},
        {"unique_id": "synthetic_target", "ds": "2026-01-30", "y": "104.5"},
        {"unique_id": "synthetic_target", "ds": "2026-02-06", "y": "104.0"},
        {"unique_id": "synthetic_target", "ds": "2026-02-13", "y": "105.0"},
        {"unique_id": "synthetic_target", "ds": "2026-02-20", "y": "106.5"},
    ]


def fixture_hash(rows: list[dict[str, str]]) -> str:
    fieldnames = list(rows[0])
    lines = [",".join(fieldnames)]
    lines.extend(",".join(row[field] for field in fieldnames) for row in rows)
    fixture_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    return hashlib.sha256(fixture_bytes).hexdigest()
