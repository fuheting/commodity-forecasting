from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from commodity_forecasting.forecasting.contracts import (
    ForecastOutputSchema,
    ResponseColumns,
    RollingOriginConfig,
)
from commodity_forecasting.forecasting.orchestration import run_rolling_origin_forecasts
from commodity_forecasting.forecasting.schedule import build_rolling_origin_schedule
from commodity_forecasting.forecasting.serialization import serialize_rolling_origin_csv


@dataclass(frozen=True)
class TargetRow:
    unique_id: str
    ds: date
    y: str


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


class RecordingAdapter:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def forecast(
        self,
        payload: Sequence[Mapping[str, str]],
        *,
        h: int,
        level: Sequence[int] | None = None,
        quantiles: Sequence[float] | None = None,
    ) -> list[dict[str, object]]:
        self.requests.append(
            {"h": h, "level": level, "quantiles": quantiles, "payload": payload}
        )
        start = _add_months(date.fromisoformat(payload[-1]["ds"]), 1)
        rows: list[dict[str, object]] = []
        for index in range(h):
            point = 100.0 + index
            row: dict[str, object] = {
                "unique_id": payload[0]["unique_id"],
                "ds": _add_months(start, index),
                "model": point,
            }
            if level is not None:
                row.update({"model-low": point - 1, "model-high": point + 1})
            if quantiles is not None:
                row.update(
                    {
                        "model-q-25": point - 0.5,
                        "model-q-75": point + 0.5,
                    }
                )
            rows.append(row)
        return rows


def test_generic_core_uses_explicit_schedule_and_output_configuration() -> None:
    rows = tuple(
        TargetRow("series", _add_months(date(2024, 1, 1), index), str(index + 1))
        for index in range(8)
    )
    config = RollingOriginConfig(context_months=3, forecast_months=2, origin_count=2)
    schedule = build_rolling_origin_schedule(rows, config)
    assert schedule.origins == (date(2024, 6, 1), date(2024, 7, 1))
    assert all(len(window.context_rows) == 3 for window in schedule.windows)

    adapter = RecordingAdapter()
    response_columns = ResponseColumns(
        point="model",
        interval_lower="model-low",
        interval_upper="model-high",
        quantiles=((0.25, "model-q-25"), (0.75, "model-q-75")),
        interval_level=90,
    )
    output_schema = ForecastOutputSchema(
        point="prediction",
        interval_lower="prediction_lower",
        interval_upper="prediction_upper",
        quantiles=("prediction_quantile_25", "prediction_quantile_75"),
        static_fields=(("model", "model/example"),),
    )
    result = run_rolling_origin_forecasts(
        rows,
        adapter,
        config=config,
        response_columns=response_columns,
        output_schema=output_schema,
    )

    interval_requests = [request for request in adapter.requests if request["level"]]
    quantile_requests = [
        request for request in adapter.requests if request["quantiles"]
    ]
    assert [request["level"] for request in interval_requests] == [[90], [90]]
    assert [request["quantiles"] for request in quantile_requests] == [
        [0.25, 0.75],
        [0.25, 0.75],
    ]

    serialized = serialize_rolling_origin_csv(result, columns=output_schema.columns)
    parsed = list(csv.DictReader(io.StringIO(serialized.decode("utf-8"))))
    assert len(parsed) == 4
    assert tuple(parsed[0]) == output_schema.columns
    assert {row["model"] for row in parsed} == {"model/example"}
    assert "evidence_sha256" not in output_schema.columns
