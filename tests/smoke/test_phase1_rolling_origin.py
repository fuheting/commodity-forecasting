from __future__ import annotations

import csv
import io
from pathlib import Path
from datetime import date

from commodity_forecasting.phase1 import rolling_origin
from commodity_forecasting.phase1.target_pipeline import MODEL_READY_RELATIVE_PATH, parse_target_csv


class SmokeAdapter:
    def forecast(self, payload, *, h, level=None, quantiles=None):
        start = rolling_origin.add_months(date.fromisoformat(payload[-1]["ds"]), 1)
        rows = []
        for index in range(h):
            point = 20.0 + index
            row = {"unique_id": payload[0]["unique_id"], "ds": rolling_origin.add_months(start, index).isoformat(), "P105": point}
            if level is not None:
                row.update({"P105-lo-80": point - 1, "P105-hi-80": point + 1})
            if quantiles is not None:
                row.update({f"P105-q-{int(value * 100)}": point - 2 + value * 4 for value in quantiles})
            rows.append(row)
        return rows
def test_sm01_closed_serialized_shape() -> None:
    root = Path(__file__).resolve().parents[2]
    rows = parse_target_csv(root / MODEL_READY_RELATIVE_PATH)
    result = rolling_origin.run_rolling_origin_forecasts(rows, SmokeAdapter())
    serialized = rolling_origin.serialize_rolling_origin_csv(result)
    parsed = list(csv.DictReader(io.StringIO(serialized.decode("utf-8"))))
    assert len(parsed) == 9
    assert tuple(parsed[0]) == rolling_origin.OUTPUT_COLUMNS
    assert {item["publication_label"] for item in parsed} == {"revised_workbook_pseudo_real_time"}
    assert all("Historical release timestamps" in item["vintage_limitation"] for item in parsed)


def test_sm01_missing_marker_blocks_consumer(tmp_path: Path) -> None:
    try:
        rolling_origin.validate_rolling_origin_consumer_gate(tmp_path)
    except rolling_origin.PublicationValidationError:
        pass
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("consumer gate must reject an orphan publication")
