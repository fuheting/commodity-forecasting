"""Evidence validation and serialization for Phase 0 smoke tests."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    REQUIRED_EVIDENCE_FIELDS,
    SM01_REQUIRED_FIELDS,
    SM02_REQUIRED_FIELDS,
    SM03_REQUIRED_FIELDS,
    SM04_REQUIRED_FIELDS,
)

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[^,\s}\]]+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
)


class EvidenceError(ValueError):
    """Raised when an evidence record violates the Phase 0 contract."""


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_evidence_record(record: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_EVIDENCE_FIELDS if field not in record]
    if missing:
        raise EvidenceError(f"missing evidence fields: {', '.join(missing)}")

    if record["mode"] not in {"offline-unit", "network-smoke"}:
        raise EvidenceError(f"unsupported evidence mode: {record['mode']}")
    if record["classification"] not in {"pass", "fail", "blocked", "unsupported"}:
        raise EvidenceError(f"unsupported evidence classification: {record['classification']}")
    if not isinstance(record["leakage_controls"], list) or not record["leakage_controls"]:
        raise EvidenceError("leakage_controls must be a non-empty list")
    if not isinstance(record["artifact_paths"], list):
        raise EvidenceError("artifact_paths must be a list")
    if record.get("test_id") == "SM-01":
        missing_sm01 = [field for field in SM01_REQUIRED_FIELDS if field not in record]
        if missing_sm01:
            raise EvidenceError(f"missing SM-01 fields: {', '.join(missing_sm01)}")
        if record["gate_result"] not in {
            "native_path_selected",
            "adapter_gap_proven",
            "model_unsupported",
            "blocked_or_unknown",
        }:
            raise EvidenceError(f"unsupported SM-01 gate_result: {record['gate_result']}")
    if record.get("test_id") == "SM-02":
        missing_sm02 = [field for field in SM02_REQUIRED_FIELDS if field not in record]
        if missing_sm02:
            raise EvidenceError(f"missing SM-02 fields: {', '.join(missing_sm02)}")
        if record["gate_result"] not in {
            "compatible_adapter_selected",
            "adapter_gap_proven",
            "model_unsupported",
            "blocked_or_unknown",
        }:
            raise EvidenceError(f"unsupported SM-02 gate_result: {record['gate_result']}")
        if record["probabilistic_output_kind"] not in {"intervals", "quantiles", "both", "none", "unknown"}:
            raise EvidenceError(
                f"unsupported SM-02 probabilistic_output_kind: {record['probabilistic_output_kind']}"
            )
        if not isinstance(record["output_columns"], list):
            raise EvidenceError("SM-02 output_columns must be a list")
        if not isinstance(record["unsupported_combinations"], list):
            raise EvidenceError("SM-02 unsupported_combinations must be a list")
    if record.get("test_id") == "SM-03":
        missing_sm03 = [field for field in SM03_REQUIRED_FIELDS if field not in record]
        if missing_sm03:
            raise EvidenceError(f"missing SM-03 fields: {', '.join(missing_sm03)}")
        if not isinstance(record["tool_calls"], list) or not record["tool_calls"]:
            raise EvidenceError("SM-03 tool_calls must be a non-empty list")
        if not str(record["forecast_analysis"]).strip():
            raise EvidenceError("SM-03 forecast_analysis must be non-empty")
        if not str(record["user_query_response"]).strip():
            raise EvidenceError("SM-03 user_query_response must be non-empty")
    if record.get("test_id") == "SM-04":
        missing_sm04 = [field for field in SM04_REQUIRED_FIELDS if field not in record]
        if missing_sm04:
            raise EvidenceError(f"missing SM-04 fields: {', '.join(missing_sm04)}")
        candidates = record["candidates"]
        if not isinstance(candidates, list) or len(candidates) < 3:
            raise EvidenceError("SM-04 candidates must contain at least three entries")
        allowed_kinds = {
            "static_monthly_workbook",
            "provider_continuous_front_month",
            "raw_contracts_for_later_construction",
            "unknown",
            "unsupported",
        }
        for candidate in candidates:
            if candidate.get("continuous_series_kind") not in allowed_kinds:
                raise EvidenceError("SM-04 candidate has unsupported continuous_series_kind")
            if "roll_methodology" not in candidate:
                raise EvidenceError("SM-04 candidate must record roll_methodology")

    assert_no_secret_material(record)


def assert_no_secret_material(value: Any) -> None:
    text = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise EvidenceError("evidence contains secret-like material")


def write_evidence(path: Path, record: dict[str, Any]) -> None:
    validate_evidence_record(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
