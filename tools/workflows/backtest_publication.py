"""Deterministic, history-only monthly rolling-origin forecast orchestration."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .readiness_contract import PUBLICATION_POLICY
from .target_publication import MODEL_READY_RELATIVE_PATH, TargetRow, parse_target_csv

P1_05_EVIDENCE_SHA256 = "f63281c2ad5f58fe41c77b724fe96e3539713855a7fa4e8a77018c3fe080cea2"
P1_05_RUN_ID = "P1-05-20260824T155057Z"
REFERENCE_MODEL_ID = "autogluon/chronos-2-small"
CONTEXT_MONTHS = 60
FORECAST_MONTHS = 3
ORIGIN_COUNT = 3
QUANTILES = tuple(round(index / 10, 1) for index in range(1, 10))
EXPECTED_ORIGINS = (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1))
EXPECTED_CUTOFFS = (date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1))
FORECASTS_RELATIVE_PATH = Path(
    "data/model_ready/world_bank_pink_sheet_monthly_arabica/rolling_origin/forecasts.csv"
)
FINDING_RELATIVE_PATH = Path("docs/findings/phase1/rolling_origin.md")
EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/rolling_origin.json")
P1_05_RELATIVE_PATH = Path("docs/findings/phase1/evidence/runtime_compatibility.json")
TARGET_RELATIVE_PATH = MODEL_READY_RELATIVE_PATH
ROADMAP_RELATIVE_PATH = Path("docs/roadmap.md")
ARTIFACT_PATHS = tuple(
    str(path) for path in (FORECASTS_RELATIVE_PATH, FINDING_RELATIVE_PATH, EVIDENCE_RELATIVE_PATH)
)
WRITE_ORDER = ("forecasts.csv", "rolling_origin.md", "rolling_origin.json")
MARKER_STATES = ("invalid_in_progress", "invalid_final", "pass_final")
CLASSIFICATIONS = ("pass", "fail", "blocked", "unsupported")
TOP_LEVEL_KEYS = (
    "schema_version", "task_id", "run_id", "timestamp_utc", "classification",
    "non_pass_diagnostics", "reference_model_id", "p1_05_run_id",
    "p1_05_evidence_sha256", "p1_05_selection", "target_artifact_sha256",
    "publication_policy", "publication_protocol", "schedule", "request_strategy",
    "execution_receipt", "origin_records", "checks", "errors", "artifact_paths",
)
PROTOCOL_KEYS = (
    "marker_path", "marker_state", "prior_marker_sha256", "csv_sha256",
    "markdown_sha256", "write_order", "commit_marker_valid",
    "replacements_fsynchronized",
)
CHECK_NAMES = (
    "p1_05_binding_valid",
    "schedule_valid",
    "window_leakage_free",
    "forecast_calls_serial",
    "csv_schema_valid",
    "publication_protocol_valid",
    "probabilistic_outputs_supported",
    "roadmap_eligible",
)

OUTPUT_COLUMNS = (
    "origin",
    "cutoff",
    "historic_context_start",
    "historic_context_end",
    "forecast_month",
    "forecast_horizon_step",
    "actual",
    "point_forecast",
    "interval_80_lower",
    "interval_80_upper",
    "quantile_0_1",
    "quantile_0_2",
    "quantile_0_3",
    "quantile_0_4",
    "quantile_0_5",
    "quantile_0_6",
    "quantile_0_7",
    "quantile_0_8",
    "quantile_0_9",
    "reference_model_id",
    "p1_05_evidence_sha256",
    "publication_label",
    "publication_proxy",
    "vintage_limitation",
)


from commodity_forecasting.forecasting.contracts import (
    ForecastOnlyAdapter,
    ForecastOutputSchema,
    ForecastResponseError,
    ForecastRow as _CoreForecastRow,
    OriginRecord,
    OriginWindow,
    ResponseColumns,
    RollingOriginConfig,
    RollingOriginError,
    RollingOriginResult,
    RollingOriginSchedule,
    ScheduleContractError,
)
from commodity_forecasting.forecasting.orchestration import (
    run_rolling_origin_forecasts as _run_core_forecasts,
    validate_rolling_origin_result as _validate_core_result,
)
from commodity_forecasting.forecasting.responses import (
    ADAPTER_PAYLOAD_COLUMNS,
    adapter_payload as _adapter_payload,
    adapter_payload_digest,
    collect_origin_request_digests,
)
from commodity_forecasting.forecasting.schedule import (
    add_months,
    build_rolling_origin_schedule as _build_core_schedule,
    schedule_digest,
    validate_rolling_origin_schedule as _validate_core_schedule,
)
from commodity_forecasting.forecasting.serialization import (
    serialize_rolling_origin_csv as _serialize_core_csv,
)
from commodity_forecasting.integrations.timecopilot import (
    ForecastCallReceipt,
    LiveDependencyError,
    LiveExecutionReceipt,
    TimeCopilotForecastAdapter,
    TimeCopilotIntegrationConfig,
    load_timecopilot_chronos_adapter,
)


class P105BindingError(RollingOriginError):
    """Raised when the frozen P1-05 evidence binding does not match."""


@dataclass(frozen=True)
class ForecastRow(_CoreForecastRow):
    """Legacy Phase 1 row preserving the accepted artifact column names."""

    columns: tuple[str, ...] = OUTPUT_COLUMNS


POC_ROLLING_ORIGIN_CONFIG = RollingOriginConfig(
    context_months=CONTEXT_MONTHS,
    forecast_months=FORECAST_MONTHS,
    origin_count=ORIGIN_COUNT,
    expected_target_end=date(2026, 7, 1),
    expected_origins=EXPECTED_ORIGINS,
    expected_cutoffs=EXPECTED_CUTOFFS,
)
POC_RESPONSE_COLUMNS = ResponseColumns(
    point="P105",
    interval_lower="P105-lo-80",
    interval_upper="P105-hi-80",
    quantiles=tuple((value, f"P105-q-{int(value * 100)}") for value in QUANTILES),
)
TASK_ID = "P1-06"
EVIDENCE_SCHEMA_VERSION = 1
P1_06_ROADMAP_PATTERN = re.compile(r"(?m)^- \[([ x-])\] \*\*P1-06\b.*$")


def _poc_output_schema(
    reference_model_id: str = REFERENCE_MODEL_ID,
    evidence_sha256: str = P1_05_EVIDENCE_SHA256,
) -> ForecastOutputSchema:
    return ForecastOutputSchema(
        point="point_forecast",
        interval_lower="interval_80_lower",
        interval_upper="interval_80_upper",
        quantiles=tuple(f"quantile_{value:.1f}".replace(".", "_") for value in QUANTILES),
        static_fields=(
            ("reference_model_id", reference_model_id),
            ("p1_05_evidence_sha256", evidence_sha256),
            ("publication_label", PUBLICATION_POLICY.evaluation_label),
            ("publication_proxy", PUBLICATION_POLICY.availability_proxy),
            ("vintage_limitation", PUBLICATION_POLICY.limitation),
        ),
    )


@dataclass(frozen=True)
class P105Binding:
    evidence_sha256: str
    selection: Mapping[str, object]


def build_rolling_origin_schedule(rows: Sequence[TargetRow]) -> RollingOriginSchedule:
    """Build the explicitly configured 60x3x3 Phase 1 schedule."""

    try:
        return _build_core_schedule(rows, POC_ROLLING_ORIGIN_CONFIG)
    except ScheduleContractError as exc:
        if "configured schedule" in str(exc) or "configured endpoint" in str(exc):
            raise ScheduleContractError(
                "derived origins or cutoffs differ from the approved schedule"
            ) from exc
        raise


def validate_rolling_origin_schedule(schedule: RollingOriginSchedule) -> None:
    _validate_core_schedule(schedule)


def validate_p1_05_binding(path: Path) -> P105Binding:
    """Validate the exact P1-05 evidence bytes and frozen pass predicate."""

    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != P1_05_EVIDENCE_SHA256:
        raise P105BindingError("P1-05 evidence SHA-256 does not match the frozen binding")
    try:
        evidence = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise P105BindingError("P1-05 evidence is not valid JSON") from exc
    expected = {
        "schema_version": 1,
        "task_id": "P1-05",
        "run_id": P1_05_RUN_ID,
        "matrix_completeness": "complete",
        "task_outcome": "pass",
        "selector_executed": True,
        "selected_reference": REFERENCE_MODEL_ID,
    }
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise P105BindingError("P1-05 pass predicate does not match the frozen binding")
    candidates = [
        candidate
        for candidate in evidence.get("candidate_records", [])
        if isinstance(candidate, Mapping) and candidate.get("variant_id") == REFERENCE_MODEL_ID
    ]
    if len(candidates) != 1:
        raise P105BindingError("P1-05 selected candidate must resolve by one exact variant_id")
    candidate = candidates[0]
    selected_candidate = {
        "variant_id": candidate.get("variant_id"),
        "contract_completeness": candidate.get("contract_completeness"),
        "probabilistic_output_kind": candidate.get("probabilistic_output_kind"),
    }
    if selected_candidate != {
        "variant_id": REFERENCE_MODEL_ID,
        "contract_completeness": True,
        "probabilistic_output_kind": "both",
    }:
        raise P105BindingError("P1-05 selected candidate does not satisfy the pass predicate")
    return P105Binding(digest, {**expected, "selected_candidate": selected_candidate})


def request_strategy_record() -> dict[str, object]:
    payload_columns = list(ADAPTER_PAYLOAD_COLUMNS)
    return {
        "point": {"kind": "point", "forecast_horizons": [1, 2, 3], "payload_columns": payload_columns},
        "point_forecast_source": "point_request",
        "interval_80": {"kind": "interval", "levels": [80], "payload_columns": payload_columns},
        "quantiles_01_09": {
            "kind": "quantile",
            "quantiles": list(QUANTILES),
            "payload_columns": payload_columns,
        },
        "combined_probabilistic_request_used": False,
        "serial_forecast_calls": 9,
        "adapter_payload_columns": payload_columns,
    }


def _expected_call_receipts(
    origins: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, str, str], ...]:
    expected: list[tuple[str, str, str]] = []
    for origin in origins:
        origin_value = origin.get("origin")
        digest = origin.get("input_digest")
        if not isinstance(origin_value, str) or not isinstance(digest, str):
            raise PublicationValidationError("execution receipt requires complete origin digests")
        expected.extend(
            (origin_value, request_kind, digest)
            for request_kind in ("point", "interval_80", "quantiles_01_09")
        )
    return tuple(expected)


def _validate_execution_receipt(
    receipt: object,
    origins: Sequence[Mapping[str, object]],
) -> None:
    if not isinstance(receipt, Mapping) or set(receipt) != {
        "runner_kind", "execution_mode", "adapter_class", "model_id", "model_alias",
        "package_versions", "network_policy", "cache_policy", "call_receipts",
    }:
        raise PublicationValidationError("live execution receipt keys differ from the closed schema")
    expected_identity = {
        "runner_kind": "timecopilot_live",
        "execution_mode": "zero_shot_forecast_only",
        "adapter_class": "timecopilot.models.foundation.chronos.Chronos",
        "model_id": REFERENCE_MODEL_ID,
        "model_alias": "P105",
    }
    if any(receipt.get(key) != value for key, value in expected_identity.items()):
        raise PublicationValidationError("live execution receipt identity is invalid")
    versions = receipt.get("package_versions")
    if not isinstance(versions, Mapping) or set(versions) != {
        "timecopilot", "timecopilot-chronos-forecasting"
    } or any(not isinstance(value, str) or not value for value in versions.values()):
        raise PublicationValidationError("live execution package versions are invalid")
    if receipt.get("network_policy") not in {
        "offline_cache_only", "connected_http_proxy", "connected_runtime_default"
    }:
        raise PublicationValidationError("live execution network policy is invalid")
    if receipt.get("cache_policy") not in {
        "explicit_hf_hub_cache", "default_huggingface_cache"
    }:
        raise PublicationValidationError("live execution cache policy is invalid")
    calls = receipt.get("call_receipts")
    expected_calls = _expected_call_receipts(origins)
    if not isinstance(calls, list) or len(calls) != len(expected_calls):
        raise PublicationValidationError("live execution must contain exactly nine call receipts")
    call_keys = {
        "origin", "request_kind", "input_digest", "output_sha256", "output_rows", "status"
    }
    for call, expected in zip(calls, expected_calls, strict=True):
        if not isinstance(call, Mapping) or set(call) != call_keys:
            raise PublicationValidationError("live call receipt keys differ from the closed schema")
        if (call.get("origin"), call.get("request_kind"), call.get("input_digest")) != expected:
            raise PublicationValidationError("live call receipt sequence or input binding is invalid")
        output_sha256 = call.get("output_sha256")
        if not isinstance(output_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", output_sha256):
            raise PublicationValidationError("live call output digest is invalid")
        if call.get("output_rows") != FORECAST_MONTHS or call.get("status") != "success":
            raise PublicationValidationError("live call receipt does not record a successful 3-row output")


def run_rolling_origin_forecasts(
    rows: Sequence[TargetRow],
    adapter: ForecastOnlyAdapter,
    *,
    reference_model_id: str = REFERENCE_MODEL_ID,
    p1_05_evidence_sha256: str = P1_05_EVIDENCE_SHA256,
) -> RollingOriginResult:
    if reference_model_id != REFERENCE_MODEL_ID or p1_05_evidence_sha256 != P1_05_EVIDENCE_SHA256:
        raise P105BindingError("rolling-origin execution requires the frozen P1-05 binding")
    core_result = _run_core_forecasts(
        rows,
        adapter,
        config=POC_ROLLING_ORIGIN_CONFIG,
        response_columns=POC_RESPONSE_COLUMNS,
        output_schema=_poc_output_schema(reference_model_id, p1_05_evidence_sha256),
    )
    return RollingOriginResult(
        core_result.schedule,
        tuple(
            OriginRecord(
                origin.window,
                origin.input_digest,
                tuple(ForecastRow(row.values) for row in origin.rows),
            )
            for origin in core_result.origins
        ),
    )


def validate_rolling_origin_result(result: RollingOriginResult) -> None:
    _validate_core_result(result, output_schema=_poc_output_schema())


def normalize_origin_record(origin: OriginRecord) -> dict[str, object]:
    window = origin.window
    digests = collect_origin_request_digests(window)
    if origin.input_digest != digests["input_digest"]:
        raise ForecastResponseError("origin input digest differs from its validated context")
    return {
        **window.as_span_record(),
        "point_forecast_kind": "point_request",
        "probabilistic_output_kind": "both",
        "actuals_present": True,
        "zero_shot_assertions": {
            "history_only": True,
            "no_fit": True,
            "no_train": True,
            "no_fine_tune": True,
            "no_calibrate": True,
            "no_update_weights": True,
            "no_cross_validation": True,
            "public_orchestration_only": True,
        },
        **digests,
        "output_columns": list(OUTPUT_COLUMNS),
        "output_shape": {"rows": FORECAST_MONTHS, "columns": len(OUTPUT_COLUMNS)},
    }


def serialize_rolling_origin_csv(result: RollingOriginResult) -> bytes:
    validate_rolling_origin_result(result)
    return _serialize_core_csv(result, columns=OUTPUT_COLUMNS)
class PublicationError(RollingOriginError):
    """Raised when the commit-marker publication contract is violated."""


class PublicationValidationError(PublicationError):
    """Raised when a published payload or marker is stale or malformed."""


def _utc_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise PublicationValidationError(f"artifact is unreadable: {path}") from exc


def _repo_path(repo_root: Path, relative: Path) -> Path:
    return repo_root.resolve() / relative


def _prior_marker_hash(repo_root: Path) -> str | None:
    path = _repo_path(repo_root, EVIDENCE_RELATIVE_PATH)
    return _sha256_path(path) if path.is_file() else None


def _default_checks(value: bool = False) -> dict[str, bool]:
    return {name: value for name in CHECK_NAMES}


def _target_digest(repo_root: Path) -> str | None:
    path = _repo_path(repo_root, TARGET_RELATIVE_PATH)
    return _sha256_path(path) if path.is_file() else None


def _p1_05_selection(repo_root: Path) -> dict[str, object] | None:
    path = _repo_path(repo_root, P1_05_RELATIVE_PATH)
    if not path.is_file():
        return None
    try:
        return dict(validate_p1_05_binding(path).selection)
    except (OSError, P105BindingError):
        return None


def _publication_protocol(
    *,
    marker_state: str,
    prior_marker_sha256: str | None,
    csv_sha256: str | None = None,
    markdown_sha256: str | None = None,
    commit_marker_valid: bool = False,
) -> dict[str, object]:
    if marker_state not in MARKER_STATES:
        raise PublicationError(f"unknown publication marker state: {marker_state}")
    return {
        "marker_path": str(EVIDENCE_RELATIVE_PATH),
        "marker_state": marker_state,
        "prior_marker_sha256": prior_marker_sha256,
        "csv_sha256": csv_sha256,
        "markdown_sha256": markdown_sha256,
        "write_order": list(WRITE_ORDER),
        "commit_marker_valid": commit_marker_valid,
        "replacements_fsynchronized": commit_marker_valid,
    }


def _diagnostic(
    *,
    classification: str,
    scope: str,
    stage: str,
    reason: str,
    origin: str | None = None,
    request_kind: str | None = None,
    exception_class: str | None = None,
) -> dict[str, object]:
    if classification not in CLASSIFICATIONS or classification == "pass":
        raise PublicationError("diagnostics must carry a non-pass classification")
    if stage not in {"schedule", "request", "response", "join", "publication", "binding", "roadmap"}:
        raise PublicationError(f"invalid diagnostic stage: {stage}")
    if request_kind is not None and request_kind not in {"point", "interval_80", "quantiles_01_09"}:
        raise PublicationError(f"invalid diagnostic request kind: {request_kind}")
    return {
        "classification": classification,
        "scope": scope,
        "stage": stage,
        "origin": origin,
        "request_kind": request_kind,
        "sanitized_reason": reason,
        "exception_class": exception_class,
        "artifact_paths": list(ARTIFACT_PATHS),
    }


def _base_evidence(
    *,
    repo_root: Path,
    marker_state: str,
    classification: str,
    result: RollingOriginResult | None,
    execution_receipt: LiveExecutionReceipt | None,
    diagnostics: Sequence[Mapping[str, object]],
    errors: Sequence[str],
    prior_marker_sha256: str | None,
    now: datetime | None,
) -> dict[str, object]:
    if marker_state not in MARKER_STATES:
        raise PublicationError(f"unknown publication marker state: {marker_state}")
    if classification not in CLASSIFICATIONS:
        raise PublicationError(f"unknown classification: {classification}")
    if marker_state == "pass_final" and (classification != "pass" or result is None):
        raise PublicationError("pass_final requires a complete passing result")
    if marker_state == "pass_final" and execution_receipt is None:
        raise PublicationError("pass_final requires a live TimeCopilot execution receipt")
    if marker_state != "pass_final" and execution_receipt is not None:
        raise PublicationError("invalid evidence cannot carry a live execution receipt")
    if marker_state == "invalid_in_progress" and classification != "blocked":
        raise PublicationError("invalid_in_progress must be blocked")
    if marker_state == "invalid_final" and classification == "pass":
        raise PublicationError("invalid_final cannot have pass classification")
    p1_selection = _p1_05_selection(repo_root)
    binding_valid = p1_selection is not None
    target_digest = _target_digest(repo_root) if result is not None else None
    if marker_state == "pass_final" and not binding_valid:
        raise PublicationError("pass_final requires the frozen P1-05 binding")
    if marker_state == "pass_final" and target_digest is None:
        raise PublicationError("pass_final requires a bound model-ready target artifact")
    schedule = result.schedule.as_record() if result is not None else None
    origin_records = [normalize_origin_record(origin) for origin in result.origins] if result is not None else []
    execution_record = execution_receipt.as_record() if execution_receipt is not None else None
    if execution_record is not None:
        _validate_execution_receipt(execution_record, origin_records)
    checks = _default_checks(False)
    if result is not None and marker_state == "pass_final":
        checks.update(
            {
                "p1_05_binding_valid": binding_valid,
                "schedule_valid": True,
                "window_leakage_free": all(
                    all(row.ds <= origin.window.cutoff for row in origin.window.context_rows)
                    and all(row.ds < origin.window.origin for row in origin.window.context_rows)
                    for origin in result.origins
                ),
                "forecast_calls_serial": True,
                "csv_schema_valid": True,
                "publication_protocol_valid": True,
                "probabilistic_outputs_supported": True,
                "roadmap_eligible": True,
            }
        )
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": f"P1-06-{_utc_timestamp(now).replace('-', '').replace(':', '').replace('T', '')}",
        "timestamp_utc": _utc_timestamp(now),
        "classification": classification,
        "non_pass_diagnostics": [dict(item) for item in diagnostics],
        "reference_model_id": REFERENCE_MODEL_ID if binding_valid else None,
        "p1_05_run_id": P1_05_RUN_ID if binding_valid else None,
        "p1_05_evidence_sha256": P1_05_EVIDENCE_SHA256 if binding_valid else None,
        "p1_05_selection": p1_selection,
        "target_artifact_sha256": target_digest,
        "publication_policy": PUBLICATION_POLICY.as_dict() if result is not None else None,
        "publication_protocol": _publication_protocol(
            marker_state=marker_state,
            prior_marker_sha256=prior_marker_sha256,
        ),
        "schedule": schedule,
        "request_strategy": request_strategy_record() if result is not None else None,
        "execution_receipt": execution_record,
        "origin_records": origin_records,
        "checks": checks,
        "errors": [str(error) for error in errors],
        "artifact_paths": list(ARTIFACT_PATHS),
    }


def render_rolling_origin_markdown(evidence: Mapping[str, object]) -> str:
    """Render the finding from canonical evidence without self-referential hashes."""

    schedule_value = evidence.get("schedule")
    schedule: Mapping[str, object] = schedule_value if isinstance(schedule_value, Mapping) else {}
    protocol_value = evidence.get("publication_protocol")
    protocol: Mapping[str, object] = protocol_value if isinstance(protocol_value, Mapping) else {}
    receipt_value = evidence.get("execution_receipt")
    receipt: Mapping[str, object] = receipt_value if isinstance(receipt_value, Mapping) else {}
    versions_value = receipt.get("package_versions")
    versions: Mapping[str, object] = versions_value if isinstance(versions_value, Mapping) else {}
    diagnostics_value = evidence.get("non_pass_diagnostics")
    diagnostics: Sequence[object] = diagnostics_value if isinstance(diagnostics_value, list) else []
    errors_value = evidence.get("errors")
    errors: Sequence[object] = errors_value if isinstance(errors_value, list) else []
    origin_values = schedule.get("origin_months", [])
    origins = origin_values if isinstance(origin_values, list) else []
    cutoff_values = schedule.get("cutoff_months", [])
    cutoffs = cutoff_values if isinstance(cutoff_values, list) else []
    write_order_values = protocol.get("write_order", WRITE_ORDER)
    write_order = write_order_values if isinstance(write_order_values, list) else list(WRITE_ORDER)
    lines = [
        "# Phase 1 Monthly Rolling-Origin Forecasting",
        "",
        f"- Run ID: `{evidence.get('run_id')}`",
        f"- Classification: `{evidence.get('classification')}`",
        f"- Marker state: `{protocol.get('marker_state')}`",
        f"- Reference model: `{evidence.get('reference_model_id') or 'none'}`",
        f"- Execution runner: `{receipt.get('runner_kind') or 'none'}`",
        f"- Execution mode: `{receipt.get('execution_mode') or 'none'}`",
        f"- TimeCopilot version: `{versions.get('timecopilot') or 'none'}`",
        f"- Chronos adapter package version: `{versions.get('timecopilot-chronos-forecasting') or 'none'}`",
        f"- Network policy: `{receipt.get('network_policy') or 'none'}`",
        f"- Cache policy: `{receipt.get('cache_policy') or 'none'}`",
        f"- P1-05 evidence SHA-256: `{evidence.get('p1_05_evidence_sha256') or 'none'}`",
        f"- Publication label: `{PUBLICATION_POLICY.evaluation_label}`",
        f"- Availability proxy: `{PUBLICATION_POLICY.availability_proxy}`",
        f"- Vintage limitation: {PUBLICATION_POLICY.limitation}",
        "",
        "## Schedule",
        "",
        f"- Origins: `{', '.join(str(item) for item in origins)}`",
        f"- Cutoffs: `{', '.join(str(item) for item in cutoffs)}`",
        f"- Historic context: `{schedule.get('historic_context_months', 'none')}` months",
        f"- Forecast horizon: `{schedule.get('forecast_months', 'none')}` months",
        "",
        "## Zero-shot and publication contract",
        "",
        "- History-only context is passed through public forecast calls; no per-origin fitting, fine-tuning, calibration, or weight updates are performed.",
        "- Point forecasts are authoritative; interval and quantile outputs are independent supported probabilistic requests.",
        "- The revised workbook is labeled pseudo-real-time. Historical release timestamps and vintages are unavailable, so strict prior-month eligibility is a conservative proxy rather than vintage-real-time evidence.",
        f"- Write order: `{', '.join(str(item) for item in write_order)}`.",
    ]
    if diagnostics:
        lines.extend(["", "## Non-pass diagnostics", ""])
        lines.extend(
            f"- `{item.get('stage')}`: {item.get('sanitized_reason')}"
            for item in diagnostics
            if isinstance(item, Mapping)
        )
    if errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in errors)
    lines.extend(["", "Machine-readable evidence: `docs/findings/phase1/evidence/rolling_origin.json`", ""])
    return "\n".join(lines)


def build_rolling_origin_evidence(
    result: RollingOriginResult | None = None,
    *,
    execution_receipt: LiveExecutionReceipt | None = None,
    repo_root: Path | None = None,
    marker_state: str = "pass_final",
    classification: str = "pass",
    diagnostics: Sequence[Mapping[str, object]] = (),
    errors: Sequence[str] = (),
    prior_marker_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Build a closed evidence record for a result or an invalid attempt."""

    root = (repo_root or Path.cwd()).resolve()
    if prior_marker_sha256 is None:
        prior_marker_sha256 = _prior_marker_hash(root)
    evidence = _base_evidence(
        repo_root=root,
        marker_state=marker_state,
        classification=classification,
        result=result,
        execution_receipt=execution_receipt,
        diagnostics=diagnostics,
        errors=errors,
        prior_marker_sha256=prior_marker_sha256,
        now=now,
    )
    if marker_state == "pass_final":
        csv_bytes = serialize_rolling_origin_csv(result)  # type: ignore[arg-type]
        markdown = render_rolling_origin_markdown(evidence).encode("utf-8")
        protocol_value = evidence["publication_protocol"]
        if not isinstance(protocol_value, Mapping):
            raise PublicationError("publication protocol is not a mapping")
        protocol = dict(protocol_value)
        protocol.update(
            {
                "csv_sha256": _sha256_bytes(csv_bytes),
                "markdown_sha256": _sha256_bytes(markdown),
                "commit_marker_valid": True,
                "replacements_fsynchronized": True,
            }
        )
        evidence["publication_protocol"] = protocol
    return evidence


def _validate_evidence_shape(evidence: Mapping[str, object], *, root: Path | None = None) -> None:
    required = set(TOP_LEVEL_KEYS)
    if set(evidence) != required:
        raise PublicationValidationError("rolling-origin evidence keys differ from the closed schema")
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION or evidence.get("task_id") != TASK_ID:
        raise PublicationValidationError("rolling-origin evidence identity is invalid")
    classification = evidence.get("classification")
    if classification not in CLASSIFICATIONS:
        raise PublicationValidationError("rolling-origin classification is invalid")
    protocol = evidence.get("publication_protocol")
    if not isinstance(protocol, Mapping) or set(protocol) != {
        "marker_path", "marker_state", "prior_marker_sha256", "csv_sha256", "markdown_sha256",
        "write_order", "commit_marker_valid", "replacements_fsynchronized",
    }:
        raise PublicationValidationError("publication protocol keys differ from the closed schema")
    marker_state = protocol.get("marker_state")
    if marker_state not in MARKER_STATES or protocol.get("marker_path") != str(EVIDENCE_RELATIVE_PATH):
        raise PublicationValidationError("publication marker envelope is invalid")
    if protocol.get("write_order") != list(WRITE_ORDER):
        raise PublicationValidationError("publication write order is invalid")
    diagnostics = evidence.get("non_pass_diagnostics")
    if not isinstance(diagnostics, list):
        raise PublicationValidationError("non-pass diagnostics must be an array")
    if marker_state == "invalid_in_progress":
        if classification != "blocked" or protocol.get("commit_marker_valid") or protocol.get("replacements_fsynchronized"):
            raise PublicationValidationError("invalid_in_progress state is inconsistent")
        if evidence.get("execution_receipt") is not None:
            raise PublicationValidationError("invalid_in_progress cannot carry an execution receipt")
    elif marker_state == "invalid_final":
        if classification == "pass" or not diagnostics or protocol.get("commit_marker_valid") or protocol.get("replacements_fsynchronized"):
            raise PublicationValidationError("invalid_final state is inconsistent")
        if evidence.get("execution_receipt") is not None:
            raise PublicationValidationError("invalid_final cannot carry an execution receipt")
    elif marker_state == "pass_final":
        if classification != "pass" or diagnostics or evidence.get("errors"):
            raise PublicationValidationError("pass_final state is inconsistent")
        if protocol.get("csv_sha256") is None or protocol.get("markdown_sha256") is None or not protocol.get("commit_marker_valid") or not protocol.get("replacements_fsynchronized"):
            raise PublicationValidationError("pass_final payload hashes or marker validity are missing")
        origins = evidence.get("origin_records")
        checks = evidence.get("checks")
        if not isinstance(origins, list) or len(origins) != ORIGIN_COUNT:
            raise PublicationValidationError("pass_final must contain exactly three origin records")
        if not isinstance(checks, Mapping) or set(checks) != set(CHECK_NAMES) or any(value is not True for value in checks.values()):
            raise PublicationValidationError("pass_final checks are not all true")
        if evidence.get("request_strategy") != request_strategy_record():
            raise PublicationValidationError("pass_final request strategy differs from the closed contract")
        _validate_execution_receipt(evidence.get("execution_receipt"), origins)
        _validate_pass_nested_evidence(evidence, root)


def _validate_pass_nested_evidence(
    evidence: Mapping[str, object], root: Path | None
) -> None:
    """Validate nested pass fields instead of trusting marker-owned claims."""

    schedule = evidence.get("schedule")
    if not isinstance(schedule, Mapping):
        raise PublicationValidationError("pass_final schedule is missing")
    expected_schedule: dict[str, object] = {
        "origin_count": ORIGIN_COUNT,
        "step_months": 1,
        "historic_context_months": CONTEXT_MONTHS,
        "forecast_months": FORECAST_MONTHS,
        "origin_months": [value.isoformat() for value in EXPECTED_ORIGINS],
        "cutoff_months": [value.isoformat() for value in EXPECTED_CUTOFFS],
    }
    expected_digests: tuple[str, ...] | None = None
    if root is not None:
        target_path = _repo_path(root, TARGET_RELATIVE_PATH)
        if target_path.is_file():
            derived_schedule = build_rolling_origin_schedule(parse_target_csv(target_path))
            expected_schedule = derived_schedule.as_record()
            expected_digests = tuple(
                collect_origin_request_digests(window)["input_digest"]
                for window in derived_schedule.windows
            )
    for key, value in expected_schedule.items():
        if schedule.get(key) != value:
            raise PublicationValidationError(f"pass_final schedule field is invalid: {key}")
    origins = evidence.get("origin_records")
    if not isinstance(origins, list) or len(origins) != ORIGIN_COUNT:
        raise PublicationValidationError("pass_final origin records are incomplete")
    expected_zero_shot = {
        "history_only": True,
        "no_fit": True,
        "no_train": True,
        "no_fine_tune": True,
        "no_calibrate": True,
        "no_update_weights": True,
        "no_cross_validation": True,
        "public_orchestration_only": True,
    }
    expected_record_keys = {
        "origin", "cutoff", "historic_context_start", "historic_context_end",
        "forecast_start", "forecast_end", "row_count", "forecast_row_count",
        "point_forecast_kind", "probabilistic_output_kind", "actuals_present",
        "zero_shot_assertions", "input_digest", "point_input_digest",
        "interval_input_digest", "quantile_input_digest", "output_columns", "output_shape",
    }
    for index, record in enumerate(origins):
        if not isinstance(record, Mapping) or set(record) != expected_record_keys:
            raise PublicationValidationError("pass_final origin record keys differ from the closed schema")
        origin = EXPECTED_ORIGINS[index]
        cutoff = EXPECTED_CUTOFFS[index]
        expected_start = add_months(cutoff, -(CONTEXT_MONTHS - 1))
        expected_forecast = tuple(add_months(origin, step) for step in range(FORECAST_MONTHS))
        expected_fields = {
            "origin": origin.isoformat(),
            "cutoff": cutoff.isoformat(),
            "historic_context_start": expected_start.isoformat(),
            "historic_context_end": cutoff.isoformat(),
            "forecast_start": expected_forecast[0].isoformat(),
            "forecast_end": expected_forecast[-1].isoformat(),
            "row_count": CONTEXT_MONTHS,
            "forecast_row_count": FORECAST_MONTHS,
            "point_forecast_kind": "point_request",
            "probabilistic_output_kind": "both",
            "actuals_present": True,
            "zero_shot_assertions": expected_zero_shot,
            "output_columns": list(OUTPUT_COLUMNS),
            "output_shape": {"rows": FORECAST_MONTHS, "columns": len(OUTPUT_COLUMNS)},
        }
        for key, value in expected_fields.items():
            if record.get(key) != value:
                raise PublicationValidationError(f"pass_final origin field is invalid: {key}")
        digests = [record.get(key) for key in ("input_digest", "point_input_digest", "interval_input_digest", "quantile_input_digest")]
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in digests) or len(set(digests)) != 1:
            raise PublicationValidationError("pass_final origin input digests are invalid")
        if expected_digests is not None and digests[0] != expected_digests[index]:
            raise PublicationValidationError("pass_final origin input digest does not match the bound context")


def validate_rolling_origin_publication(repo_root: Path | None = None) -> dict[str, object]:
    """Validate the canonical marker and its payload hashes without mutation."""

    root = (repo_root or Path.cwd()).resolve()
    marker_path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
    try:
        evidence = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationValidationError("rolling-origin evidence marker is unavailable") from exc
    if not isinstance(evidence, dict):
        raise PublicationValidationError("rolling-origin evidence marker must be an object")
    _validate_evidence_shape(evidence, root=root)
    protocol = evidence["publication_protocol"]
    assert isinstance(protocol, Mapping)
    if protocol["marker_state"] != "pass_final":
        raise PublicationValidationError("rolling-origin payload is not consumable without pass_final marker")
    p1_path = _repo_path(root, P1_05_RELATIVE_PATH)
    if not p1_path.is_file() or _sha256_path(p1_path) != evidence.get("p1_05_evidence_sha256"):
        raise PublicationValidationError("published evidence is stale against the frozen P1-05 binding")
    try:
        binding = validate_p1_05_binding(p1_path)
    except P105BindingError as exc:
        raise PublicationValidationError("published evidence has an invalid P1-05 binding") from exc
    if evidence.get("p1_05_selection") != dict(binding.selection):
        raise PublicationValidationError("published P1-05 selection differs from the frozen binding")
    if evidence.get("publication_policy") != PUBLICATION_POLICY.as_dict():
        raise PublicationValidationError("published publication policy differs from P1-01")
    target_path = _repo_path(root, TARGET_RELATIVE_PATH)
    if not target_path.is_file():
        raise PublicationValidationError("published target artifact is missing")
    if evidence.get("target_artifact_sha256") != _sha256_path(target_path):
        raise PublicationValidationError("published evidence is stale against the target artifact")
    csv_path = _repo_path(root, FORECASTS_RELATIVE_PATH)
    markdown_path = _repo_path(root, FINDING_RELATIVE_PATH)
    if _sha256_path(csv_path) != protocol["csv_sha256"] or _sha256_path(markdown_path) != protocol["markdown_sha256"]:
        raise PublicationValidationError("published payload hash does not match the pass marker")
    markdown = markdown_path.read_text(encoding="utf-8")
    if markdown != render_rolling_origin_markdown(evidence):
        raise PublicationValidationError("rolling-origin Markdown differs from canonical evidence")
    _validate_published_csv(root, evidence)
    return evidence


def _validate_published_csv(root: Path, evidence: Mapping[str, object]) -> None:
    path = _repo_path(root, FORECASTS_RELATIVE_PATH)
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != OUTPUT_COLUMNS:
                raise PublicationValidationError("published CSV columns differ from the closed schema")
            rows = list(reader)
    except OSError as exc:
        raise PublicationValidationError("published CSV is unavailable") from exc
    if len(rows) != 9:
        raise PublicationValidationError("published CSV must contain exactly nine rows")
    expected_origins = [value.isoformat() for value in EXPECTED_ORIGINS]
    if [row["origin"] for row in rows[::3]] != expected_origins:
        raise PublicationValidationError("published CSV origin order is invalid")
    target_path = _repo_path(root, TARGET_RELATIVE_PATH)
    if not target_path.is_file():
        raise PublicationValidationError("published target artifact is missing")
    target_rows = parse_target_csv(target_path)
    actuals = {row.ds.isoformat(): float(row.y) for row in target_rows}
    for row in rows:
        if row["forecast_month"] not in actuals or float(row["actual"]) != actuals[row["forecast_month"]]:
            raise PublicationValidationError("published CSV actual does not match the target artifact")
    expected_by_origin = {
        origin.isoformat(): tuple(add_months(origin, index).isoformat() for index in range(FORECAST_MONTHS))
        for origin in EXPECTED_ORIGINS
    }
    for index, row in enumerate(rows):
        origin_index = index // FORECAST_MONTHS
        horizon = index % FORECAST_MONTHS + 1
        origin = expected_origins[origin_index]
        if row["origin"] != origin or row["forecast_horizon_step"] != str(horizon):
            raise PublicationValidationError("published CSV row order or horizon is invalid")
        if row["forecast_month"] != expected_by_origin[origin][horizon - 1]:
            raise PublicationValidationError("published CSV forecast span is invalid")
        if row["reference_model_id"] != REFERENCE_MODEL_ID or row["p1_05_evidence_sha256"] != P1_05_EVIDENCE_SHA256:
            raise PublicationValidationError("published CSV provenance binding is invalid")
        if row["cutoff"] != add_months(date.fromisoformat(origin), -1).isoformat():
            raise PublicationValidationError("published CSV cutoff is invalid")
        if row["historic_context_end"] != row["cutoff"]:
            raise PublicationValidationError("published CSV historic context end is invalid")
        expected_context_start = add_months(date.fromisoformat(row["cutoff"]), -(CONTEXT_MONTHS - 1))
        if row["historic_context_start"] != expected_context_start.isoformat():
            raise PublicationValidationError("published CSV historic context start is invalid")
        expected_policy = {
            "publication_label": PUBLICATION_POLICY.evaluation_label,
            "publication_proxy": PUBLICATION_POLICY.availability_proxy,
            "vintage_limitation": PUBLICATION_POLICY.limitation,
        }
        for column, expected_value in expected_policy.items():
            if row[column] != expected_value:
                raise PublicationValidationError(f"published CSV policy field is invalid: {column}")
        for column in OUTPUT_COLUMNS[6:19]:
            try:
                value = float(row[column])
            except (TypeError, ValueError) as exc:
                raise PublicationValidationError(f"published CSV value is not numeric: {column}") from exc
            if not math.isfinite(value):
                raise PublicationValidationError(f"published CSV value is not finite: {column}")
        lower = float(row["interval_80_lower"])
        upper = float(row["interval_80_upper"])
        if lower > upper:
            raise PublicationValidationError("published CSV interval bounds cross")
        quantiles = [float(row[f"quantile_0_{index}"]) for index in range(1, 10)]
        if quantiles != sorted(quantiles):
            raise PublicationValidationError("published CSV quantiles cross")


def validate_rolling_origin_consumer_gate(repo_root: Path | None = None) -> dict[str, object]:
    """P1-07 gate: downstream consumers may load only a validated pass marker."""

    return validate_rolling_origin_publication(repo_root)


def validate_rolling_origin_roadmap_eligibility(repo_root: Path | None = None) -> bool:
    """Return whether a validated P1-06 pass may advance the roadmap."""

    root = (repo_root or Path.cwd()).resolve()
    evidence = validate_rolling_origin_publication(root)
    if evidence["classification"] != "pass":
        return False
    roadmap = _repo_path(root, ROADMAP_RELATIVE_PATH).read_text(encoding="utf-8")
    matches = P1_06_ROADMAP_PATTERN.findall(roadmap)
    return matches in ([" "], ["x"])


def _stage_bytes(destination: Path, content: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def begin_rolling_origin_attempt(
    repo_root: Path | None = None,
    *,
    now: datetime | None = None,
    replace_file: object = os.replace,
) -> dict[str, object]:
    """Invalidate the canonical marker before any model execution."""

    root = (repo_root or Path.cwd()).resolve()
    evidence = build_rolling_origin_evidence(
        None,
        repo_root=root,
        marker_state="invalid_in_progress",
        classification="blocked",
        now=now,
    )
    content = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")
    destination = _repo_path(root, EVIDENCE_RELATIVE_PATH)
    staged = _stage_bytes(destination, content)
    try:
        replace_file(staged, destination)  # type: ignore[operator]
    finally:
        staged.unlink(missing_ok=True)
    return evidence


def publish_rolling_origin_bundle(
    result: RollingOriginResult,
    repo_root: Path | None = None,
    *,
    execution_receipt: LiveExecutionReceipt | None = None,
    now: datetime | None = None,
    replace_file: object = os.replace,
) -> dict[str, object]:
    """Write payloads first and the pass marker last, with fsynced staging."""

    root = (repo_root or Path.cwd()).resolve()
    validate_rolling_origin_result(result)
    if execution_receipt is None:
        raise PublicationError("canonical pass publication requires live execution attestation")
    evidence = build_rolling_origin_evidence(
        result,
        execution_receipt=execution_receipt,
        repo_root=root,
        now=now,
    )
    csv_bytes = serialize_rolling_origin_csv(result)
    markdown_bytes = render_rolling_origin_markdown(evidence).encode("utf-8")
    evidence_bytes = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")
    destinations = (
        (_repo_path(root, FORECASTS_RELATIVE_PATH), csv_bytes),
        (_repo_path(root, FINDING_RELATIVE_PATH), markdown_bytes),
        (_repo_path(root, EVIDENCE_RELATIVE_PATH), evidence_bytes),
    )
    staged: list[tuple[Path, Path]] = []
    try:
        staged = [(_stage_bytes(destination, content), destination) for destination, content in destinations]
        for index, (temporary, destination) in enumerate(staged):
            if index == 2:
                # Re-read the marker object before its final replacement; this
                # prevents a caller from accidentally publishing a stale marker.
                _validate_evidence_shape(evidence)
            replace_file(temporary, destination)  # type: ignore[operator]
    except BaseException as exc:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        diagnostic = _diagnostic(
            classification="fail",
            scope="p1-06-publication",
            stage="publication",
            reason=f"publication boundary failed: {type(exc).__name__}",
            exception_class=type(exc).__name__,
        )
        invalid = build_rolling_origin_evidence(
            None,
            repo_root=root,
            marker_state="invalid_final",
            classification="fail",
            diagnostics=(diagnostic,),
            errors=("publication boundary failed",),
            now=now,
        )
        invalid_bytes = (json.dumps(invalid, indent=2, sort_keys=True) + "\n").encode("utf-8")
        invalid_path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
        invalid_stage = _stage_bytes(invalid_path, invalid_bytes)
        try:
            replace_file(invalid_stage, invalid_path)  # type: ignore[operator]
        finally:
            invalid_stage.unlink(missing_ok=True)
        raise PublicationError("rolling-origin publication failed and marker was invalidated") from exc
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    try:
        return validate_rolling_origin_publication(root)
    except Exception as exc:
        diagnostic = _diagnostic(
            classification="fail",
            scope="p1-06-publication",
            stage="publication",
            reason=f"post-publication validation failed: {type(exc).__name__}",
            exception_class=type(exc).__name__,
        )
        invalid = build_rolling_origin_evidence(
            None,
            repo_root=root,
            marker_state="invalid_final",
            classification="fail",
            diagnostics=(diagnostic,),
            errors=("post-publication validation failed",),
            now=now,
        )
        invalid_path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
        invalid_stage = _stage_bytes(invalid_path, (json.dumps(invalid, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        try:
            replace_file(invalid_stage, invalid_path)  # type: ignore[operator]
        finally:
            invalid_stage.unlink(missing_ok=True)
        raise PublicationError("rolling-origin publication failed post-write validation") from exc


def update_rolling_origin_roadmap(repo_root: Path | None = None) -> None:
    """Idempotently check P1-06 only after the matching pass marker validates."""

    root = (repo_root or Path.cwd()).resolve()
    validate_rolling_origin_publication(root)
    path = _repo_path(root, ROADMAP_RELATIVE_PATH)
    text = path.read_text(encoding="utf-8")
    matches = P1_06_ROADMAP_PATTERN.findall(text)
    if matches not in ([" "], ["x"]):
        raise PublicationError("P1-06 roadmap entry is missing, duplicated, or invalid")
    if matches == ["x"]:
        return
    updated = P1_06_ROADMAP_PATTERN.sub(lambda match: match.group(0).replace("[ ]", "[x]", 1), text)
    staged = _stage_bytes(path, updated.encode("utf-8"))
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


POC_TIMECOPILOT_CONFIG = TimeCopilotIntegrationConfig(
    model_id=REFERENCE_MODEL_ID,
    model_alias="P105",
    adapter_class="timecopilot.models.foundation.chronos.Chronos",
    package_distributions=("timecopilot", "timecopilot-chronos-forecasting"),
    frequency="MS",
    batch_size=1,
    point_request_kind="point",
    interval_request_kind="interval_80",
    quantile_request_kind="quantiles_01_09",
)


def _load_live_adapter() -> TimeCopilotForecastAdapter:
    """Construct the pinned public Chronos adapter for the live CLI path."""

    return load_timecopilot_chronos_adapter(POC_TIMECOPILOT_CONFIG)


def _write_live_failure(
    root: Path,
    exc: BaseException,
    *,
    stage: str,
    classification: str,
) -> None:
    diagnostic = _diagnostic(
        classification=classification,
        scope="p1-06-live",
        stage=stage,
        reason=f"live {stage} failed: {type(exc).__name__}",
        exception_class=type(exc).__name__,
    )
    invalid = build_rolling_origin_evidence(
        None,
        repo_root=root,
        marker_state="invalid_final",
        classification=classification,
        diagnostics=(diagnostic,),
        errors=(f"live {stage} failed",),
    )
    path = _repo_path(root, EVIDENCE_RELATIVE_PATH)
    staged = _stage_bytes(
        path,
        (json.dumps(invalid, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _marker_is_precise_publication_failure(root: Path) -> bool:
    try:
        evidence = json.loads(_repo_path(root, EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    diagnostics = evidence.get("non_pass_diagnostics") if isinstance(evidence, Mapping) else None
    return (
        isinstance(evidence, Mapping)
        and isinstance(evidence.get("publication_protocol"), Mapping)
        and evidence["publication_protocol"].get("marker_state") == "invalid_final"  # type: ignore[index,union-attr]
        and isinstance(diagnostics, list)
        and any(
            isinstance(item, Mapping) and item.get("scope") == "p1-06-publication"
            for item in diagnostics
        )
    )


def run_live_rolling_origin(repo_root: Path | None = None) -> dict[str, object]:
    """Run the pinned model through the public forecast-only boundary."""

    root = (repo_root or Path.cwd()).resolve()
    begin_rolling_origin_attempt(root)
    try:
        validate_p1_05_binding(_repo_path(root, P1_05_RELATIVE_PATH))
    except Exception as exc:
        _write_live_failure(root, exc, stage="binding", classification="fail")
        raise PublicationError("live rolling-origin binding failed") from exc
    try:
        rows = parse_target_csv(_repo_path(root, TARGET_RELATIVE_PATH))
        build_rolling_origin_schedule(rows)
    except Exception as exc:
        _write_live_failure(root, exc, stage="schedule", classification="fail")
        raise PublicationError("live rolling-origin schedule failed") from exc
    try:
        adapter = _load_live_adapter()
    except Exception as exc:
        classification = "blocked" if isinstance(exc, LiveDependencyError) else "fail"
        _write_live_failure(root, exc, stage="request", classification=classification)
        raise PublicationError("live rolling-origin adapter load failed") from exc
    try:
        result = run_rolling_origin_forecasts(rows, adapter)
        execution_receipt = adapter.execution_receipt()
    except Exception as exc:
        classification = "blocked" if isinstance(exc, LiveDependencyError) else "fail"
        stage = "request" if classification == "blocked" else "response"
        _write_live_failure(root, exc, stage=stage, classification=classification)
        raise PublicationError("live rolling-origin forecast failed") from exc
    try:
        return publish_rolling_origin_bundle(
            result,
            root,
            execution_receipt=execution_receipt,
        )
    except PublicationError:
        if not _marker_is_precise_publication_failure(root):
            _write_live_failure(
                root,
                PublicationError("publication failed"),
                stage="publication",
                classification="fail",
            )
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--validate-publication", action="store_true")
    parser.add_argument("--update-roadmap", action="store_true")
    parser.add_argument("--check-roadmap", action="store_true")
    parser.add_argument("--validate-consumer-gate", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.repo_root.resolve()
    try:
        if arguments.live:
            if not arguments.publish:
                raise PublicationError("--live requires --publish")
            run_live_rolling_origin(root)
        elif arguments.validate_publication or arguments.validate_consumer_gate:
            validate_rolling_origin_consumer_gate(root)
        elif arguments.update_roadmap:
            update_rolling_origin_roadmap(root)
        elif arguments.check_roadmap:
            if not validate_rolling_origin_roadmap_eligibility(root):
                raise PublicationError("P1-06 roadmap is not eligible")
        else:
            raise PublicationError("one rolling-origin action is required")
    except (RollingOriginError, OSError) as exc:
        print(f"rolling-origin: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by smoke/CLI tests
    raise SystemExit(main())
