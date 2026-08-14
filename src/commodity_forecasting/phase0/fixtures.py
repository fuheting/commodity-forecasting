"""Historical deterministic fixtures for Phase 0 capability smoke tests.

These weekly fixtures preserve reproducibility of completed adapter tests. They
do not define the active monthly Arabica dataset or forecast contract.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

FIXTURE_ID = "phase0_synthetic_weekly_v1"


def weekly_target_rows() -> list[dict[str, str]]:
    """Return a compact weekly target fixture that is not Coffee C data."""

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


def covariate_rows() -> list[dict[str, str]]:
    """Return past-only and known-future synthetic covariates."""

    return [
        {
            "unique_id": "synthetic_target",
            "ds": "2026-01-02",
            "past_signal": "10.0",
            "known_future_signal": "1",
            "availability_class": "observed",
        },
        {
            "unique_id": "synthetic_target",
            "ds": "2026-01-09",
            "past_signal": "10.5",
            "known_future_signal": "0",
            "availability_class": "observed",
        },
        {
            "unique_id": "synthetic_target",
            "ds": "2026-01-16",
            "past_signal": "11.0",
            "known_future_signal": "1",
            "availability_class": "observed",
        },
        {
            "unique_id": "synthetic_target",
            "ds": "2026-01-23",
            "past_signal": "11.5",
            "known_future_signal": "0",
            "availability_class": "observed",
        },
        {
            "unique_id": "synthetic_target",
            "ds": "2026-01-30",
            "past_signal": "12.0",
            "known_future_signal": "1",
            "availability_class": "observed",
        },
        {
            "unique_id": "synthetic_target",
            "ds": "2026-02-06",
            "past_signal": "",
            "known_future_signal": "0",
            "availability_class": "known_at_origin",
        },
        {
            "unique_id": "synthetic_target",
            "ds": "2026-02-13",
            "past_signal": "",
            "known_future_signal": "1",
            "availability_class": "known_at_origin",
        },
        {
            "unique_id": "synthetic_target",
            "ds": "2026-02-20",
            "past_signal": "",
            "known_future_signal": "0",
            "availability_class": "known_at_origin",
        },
    ]


def fixture_bytes(rows: list[dict[str, str]]) -> bytes:
    fieldnames = list(rows[0])
    lines = [",".join(fieldnames)]
    for row in rows:
        lines.append(",".join(row[field] for field in fieldnames))
    return ("\n".join(lines) + "\n").encode("utf-8")


def fixture_hash(rows: list[dict[str, str]]) -> str:
    return hashlib.sha256(fixture_bytes(rows)).hexdigest()


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_phase0_fixtures(base_dir: Path) -> dict[str, Path]:
    paths = {
        "weekly_target": base_dir / "weekly_target.csv",
        "covariates": base_dir / "covariates.csv",
        "query": base_dir / "query_fixture.json",
        "datasource_manifest": base_dir / "datasource_manifest.json",
    }
    write_csv(paths["weekly_target"], weekly_target_rows())
    write_csv(paths["covariates"], covariate_rows())
    paths["query"].write_text(
        json.dumps(
            {
                "fixture_id": FIXTURE_ID,
                "query": "Summarize the 3-week synthetic forecast risk.",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["datasource_manifest"].write_text(
        json.dumps(
            {
                "fixture_id": FIXTURE_ID,
                "data_origin": "synthetic",
                "contains_real_coffee_c_data": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return paths
