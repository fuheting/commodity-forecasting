"""Leakage, path, catalog, and roadmap guards for Phase 0."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .contracts import CATALOG_REQUIRED_FIELDS, ForecastWindow
from .evidence import EvidenceError, assert_no_secret_material


class LeakageError(ValueError):
    """Raised when a time-series operation would leak future information."""


class CatalogError(ValueError):
    """Raised when catalog metadata violates the Phase 0 schema."""


class RoadmapGateError(ValueError):
    """Raised when roadmap completion lacks evidence."""


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def assert_weekly_alignment(rows: Sequence[Mapping[str, str]], *, column: str = "ds") -> None:
    dates = [parse_date(str(row[column])) for row in rows]
    if dates != sorted(dates):
        raise LeakageError("timestamps must be sorted")
    for previous, current in zip(dates, dates[1:]):
        if current - previous != timedelta(days=7):
            raise LeakageError("fixture timestamps must be exactly weekly")


def walk_forward_windows(
    rows: Sequence[Mapping[str, str]],
    *,
    history: int,
    horizon: int,
    step_size: int | None = None,
) -> list[ForecastWindow]:
    if history <= 0 or horizon <= 0:
        raise LeakageError("history and horizon must be positive")
    step = step_size or horizon
    if step <= 0:
        raise LeakageError("step_size must be positive")
    assert_weekly_alignment(rows)
    dates = [parse_date(str(row["ds"])) for row in rows]
    windows: list[ForecastWindow] = []
    start = 0
    while start + history + horizon <= len(dates):
        train = dates[start : start + history]
        future = dates[start + history : start + history + horizon]
        if max(train) >= min(future):
            raise LeakageError("training data crosses forecast boundary")
        windows.append(
            ForecastWindow(
                cutoff=max(train).isoformat(),
                train_start=min(train).isoformat(),
                train_end=max(train).isoformat(),
                forecast_start=min(future).isoformat(),
                forecast_end=max(future).isoformat(),
            )
        )
        start += step
    return windows


def reject_random_split(method: str) -> None:
    if method.lower().replace("_", "-") in {"random", "random-split", "train-test-split"}:
        raise LeakageError("random splits are prohibited for forecasting evaluation")


def reject_centered_window(*, centered: bool) -> None:
    if centered:
        raise LeakageError("centered rolling windows are prohibited")


def reject_cross_boundary_fill(method: str) -> None:
    normalized = method.lower().replace("_", "-")
    if normalized in {"backfill", "bfill", "future-fill", "cross-boundary-interpolation"}:
        raise LeakageError(f"{method} can leak future observations across the validation boundary")


def assert_covariate_cutoff(
    rows: Sequence[Mapping[str, str]],
    *,
    cutoff: str,
    date_column: str = "ds",
    availability_column: str = "availability_class",
    allow_known_future: bool = False,
) -> None:
    cutoff_date = parse_date(cutoff)
    for row in rows:
        row_date = parse_date(str(row[date_column]))
        availability = str(row.get(availability_column, "observed"))
        if row_date > cutoff_date and not (allow_known_future and availability == "known_at_origin"):
            raise LeakageError("future covariate value is not known at forecast origin")


def assert_safe_artifact_path(path: Path) -> None:
    normalized = path.as_posix()
    if "/data/raw/" in normalized or normalized.startswith("data/raw/"):
        raise EvidenceError("raw provider data must not be committed as a Phase 0 artifact")
    if ".env" in path.parts:
        raise EvidenceError("environment files must not be committed as Phase 0 artifacts")


def assert_safe_artifact_content(path: Path) -> None:
    assert_safe_artifact_path(path)
    if path.is_file():
        assert_no_secret_material(path.read_text(encoding="utf-8", errors="ignore"))


def validate_catalog_row(row: Mapping[str, object]) -> None:
    missing = [field for field in CATALOG_REQUIRED_FIELDS if field not in row]
    if missing:
        raise CatalogError(f"missing catalog fields: {', '.join(missing)}")
    for field in ("history_start", "history_end", "roll_methodology", "programmatic_access"):
        if field in row and row[field] in {"", None}:
            raise CatalogError(f"{field} must be explicit, use 'unknown' when unestablished")


def assert_roadmap_evidence_links(evidence_paths: Iterable[Path]) -> None:
    paths = list(evidence_paths)
    if not paths:
        raise RoadmapGateError("roadmap completion requires at least one evidence link")
    for path in paths:
        if not path.exists():
            raise RoadmapGateError(f"evidence file does not exist: {path}")
        if "docs/findings/phase0/evidence" not in path.as_posix():
            raise RoadmapGateError(f"roadmap evidence must live under docs/findings/phase0/evidence: {path}")
