"""Single-call TimeCopilot natural-language exercise for P1-08."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence, cast

from . import evaluation, rolling_origin, runtime_compatibility, target_pipeline
from .target_pipeline import parse_target_csv

TASK_ID = "P1-08"
SCHEMA_VERSION = 1
QUERY = (
    "For Coffee, Arabica, using the 60-month monthly history through April 2026 "
    "and the May-July 2026 forecast horizon, explain the next 3-month outlook, "
    "note the main historical pattern the model sees, and summarize the uncertainty "
    "in plain language."
)
REQUESTED_LLM = "deepseek:deepseek-v4-flash"
ENV_KEY = "DEEPSEEK_API_KEY"
RUNTIME_PREPARED_ENV = "P1_08_RUNTIME_PREPARED"
REFERENCE_MODEL_ID = "autogluon/chronos-2-small"
REQUIRED_TOOL_CALLS = (
    "tsfeatures_tool",
    "cross_validation_tool",
    "forecast_tool",
    "detect_anomalies_tool",
)
DEFAULT_OUTPUT_TOOL_NAME = "final_result"
REQUIRED_QUERY_ANCHORS = frozenset(
    {"coffee", "arabica", "2026", "may", "june", "july"}
)
FINDING_RELATIVE_PATH = Path("docs/findings/phase1/natural_language.md")
EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/natural_language.json")
P1_06_EVIDENCE_RELATIVE_PATH = rolling_origin.EVIDENCE_RELATIVE_PATH
P1_07_EVIDENCE_RELATIVE_PATH = evaluation.EVIDENCE_RELATIVE_PATH
TARGET_RELATIVE_PATH = rolling_origin.TARGET_RELATIVE_PATH
ROADMAP_RELATIVE_PATH = rolling_origin.ROADMAP_RELATIVE_PATH
ARTIFACT_PATHS = (str(FINDING_RELATIVE_PATH), str(EVIDENCE_RELATIVE_PATH))

TOP_LEVEL_KEYS = (
    "schema_version", "task_id", "run_id", "timestamp_utc", "classification",
    "source_binding", "query", "requested_llm", "observed_provider",
    "observed_model", "input_contract", "tool_calls", "structured_output_tool",
    "forecast_analysis", "user_query_response", "checks", "diagnostics",
    "artifact_paths",
)
SOURCE_BINDING_KEYS = (
    "p1_06_evidence_path", "p1_06_run_id", "p1_06_classification",
    "p1_06_marker_state", "p1_06_reference_model_id", "p1_07_evidence_path",
    "p1_07_run_id", "p1_07_classification", "p1_07_source_p1_06_run_id",
    "target_path",
)
INPUT_CONTRACT_KEYS = (
    "reference_model_id", "context_start", "context_end", "context_row_count",
    "cutoff", "forecast_start", "forecast_end", "h", "freq", "seasonality",
)
CHECK_KEYS = (
    "dependency_gate_pass", "env_key_loaded", "input_window_valid",
    "no_future_leakage", "provider_resolved", "model_resolved",
    "provider_model_consistent", "required_tool_calls_exact", "analysis_nonempty",
    "query_response_nonempty", "query_anchors_present", "secret_free",
    "roadmap_eligible",
)
PASS_REQUIRED_CHECK_KEYS = tuple(
    key for key in CHECK_KEYS if key != "required_tool_calls_exact"
)
DIAGNOSTIC_KEYS = (
    "classification", "stage", "exception_class", "error_kind", "sanitized_reason",
)
STAGES = {
    "credential", "dependency_gate", "input", "dataframe_construction",
    "forecaster_construction", "provider_resolution", "request", "response",
    "publication", "roadmap",
}
EXCEPTION_CLASSES = {
    "CredentialUnavailable", "EnvContractError", "DependencyGateError",
    "InputContractError", "UserError", "AuthenticationError",
    "PermissionDeniedError", "RateLimitError", "APIConnectionError",
    "APITimeoutError", "ProxyError", "ConnectError", "TimeoutException",
    "ImportError", "ModuleNotFoundError", "ModelAPIError", "ModelHTTPError",
    "UnexpectedModelBehavior", "OutputContractError", "PublicationError",
    "OSError", "ExternalRuntimeError", "LocalContractError",
}
SANITIZED_REASONS = {
    "missing_credential": "credential is unavailable.",
    "malformed_env": "environment file violates the one-key contract.",
    "prerequisite_not_pass": "P1-06 or P1-07 prerequisite is not a validated pass.",
    "invalid_input_window": "monthly Arabica input window violates the fixed contract.",
    "provider_unavailable": "DeepSeek provider could not be resolved.",
    "provider_request_failed": "provider request failed for an unclassified external reason.",
    "authentication_rejected": "DeepSeek rejected the credential.",
    "rate_limited": "DeepSeek service rate limit blocked the run.",
    "proxy_unavailable": "configured proxy blocked the provider request.",
    "network_unavailable": "network connectivity blocked the provider request.",
    "timeout": "provider request timed out.",
    "runtime_dependency_unavailable": "required runtime dependency is unavailable.",
    "provider_response_invalid": "provider response metadata is unavailable or inconsistent.",
    "tool_contract_failed": "required TimeCopilot tool-call contract was not satisfied.",
    "output_contract_failed": "forecast analysis or query response did not satisfy the output contract.",
    "secret_detected": "secret material was detected in candidate output.",
    "publication_failed": "canonical P1-08 publication failed.",
    "roadmap_inconsistent": "P1-08 roadmap state is inconsistent with validated evidence.",
    "unexpected_runtime_failure": "an unexpected runtime failure prevented the run.",
}
BLOCKED_ERROR_KINDS = {
    "missing_credential", "provider_unavailable", "authentication_rejected",
    "rate_limited", "proxy_unavailable", "network_unavailable", "timeout",
    "runtime_dependency_unavailable", "provider_request_failed",
}
RUN_ID_PATTERN = re.compile(r"^P1-08-(\d{8}T\d{6}Z)$")
ROADMAP_PATTERN = re.compile(r"^- \[([ x])\] \*\*P1-08\b", re.MULTILINE)
GENERIC_SECRET_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:api[_-]?key|secret|token|password|authorization)"
    r"(?![A-Za-z0-9_])\s*[\"']?\s*(?::|=)\s*(?:bearer\s+)?"
    r"(?:\"[^\"\r\n]+\"|'[^'\r\n]+'|[^\s,}\]]+)"
)


class NaturalLanguageError(RuntimeError):
    """Base exception for the P1-08 contract."""


class CredentialUnavailable(NaturalLanguageError):
    """Raised when the one required credential is absent."""


class EnvContractError(NaturalLanguageError):
    """Raised when the exact one-key environment contract is malformed."""


class DependencyGateError(NaturalLanguageError):
    """Raised when P1-06 or P1-07 is not a validated pass."""


class InputContractError(NaturalLanguageError):
    """Raised when the fixed monthly history window is unavailable."""


class OutputContractError(NaturalLanguageError):
    """Raised when an agent result violates the closed output contract."""


class PublicationError(NaturalLanguageError):
    """Raised when evidence publication or validation fails."""


class LocalContractError(NaturalLanguageError):
    """Raised for a local closed-schema violation."""


def load_deepseek_api_key(
    env_path: Path,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> str:
    """Load exactly ``DEEPSEEK_API_KEY`` with strict, dependency-free semantics."""

    target = os.environ if environ is None else environ
    existing = target.get(ENV_KEY, "")
    if existing.strip():
        return existing
    try:
        handle = env_path.open("r", encoding="utf-8")
    except OSError as exc:
        raise CredentialUnavailable("credential is unavailable") from exc
    declarations: list[str] = []
    try:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export"):
                remainder = line[len("export"):]
                if remainder and remainder[0].isspace():
                    line = remainder.strip()
            if "=" not in line:
                if re.match(rf"^{re.escape(ENV_KEY)}(?:\s|$)", line):
                    raise EnvContractError("environment file violates the one-key contract")
                continue
            key, raw_value = line.split("=", 1)
            if key.strip() != ENV_KEY:
                continue
            value = raw_value.strip()
            if not value:
                raise EnvContractError("environment file violates the one-key contract")
            if value[0] in {"'", '"'}:
                quote = value[0]
                if len(value) < 2 or value[-1] != quote:
                    raise EnvContractError("environment file violates the one-key contract")
                value = value[1:-1]
            elif "'" in value or '"' in value:
                raise EnvContractError("environment file violates the one-key contract")
            if not value:
                raise EnvContractError("environment file violates the one-key contract")
            declarations.append(value)
    except UnicodeError as exc:
        raise EnvContractError("environment file violates the one-key contract") from exc
    finally:
        handle.close()
    if not declarations:
        raise CredentialUnavailable("credential is unavailable")
    if len(declarations) != 1:
        raise EnvContractError("environment file violates the one-key contract")
    target[ENV_KEY] = declarations[0]
    return declarations[0]


def input_contract() -> dict[str, object]:
    return {
        "reference_model_id": REFERENCE_MODEL_ID,
        "context_start": "2021-05-01",
        "context_end": "2026-04-01",
        "context_row_count": 60,
        "cutoff": "2026-04-01",
        "forecast_start": "2026-05-01",
        "forecast_end": "2026-07-01",
        "h": 3,
        "freq": "MS",
        "seasonality": 12,
    }


def _repo_path(root: Path, relative: Path) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise LocalContractError("repository artifact path escapes the repository root")
    return candidate


def load_validated_input(root: Path) -> tuple[dict[str, str], tuple[Any, ...]]:
    """Validate the prerequisite publications and return only the last history window."""

    try:
        p1_06 = rolling_origin.validate_rolling_origin_publication(root)
        p1_07 = evaluation.validate_evaluation_publication(root)
    except (rolling_origin.RollingOriginError, evaluation.EvaluationError, OSError) as exc:
        raise DependencyGateError("P1-06 or P1-07 prerequisite is not a validated pass") from exc
    p1_07_binding = p1_07.get("source_binding")
    if (
        p1_06.get("classification") != "pass"
        or p1_07.get("classification") != "pass"
        or not isinstance(p1_07_binding, Mapping)
        or p1_07_binding.get("p1_06_run_id") != p1_06.get("run_id")
    ):
        raise DependencyGateError("P1-06 or P1-07 prerequisite is not a validated pass")
    try:
        rows = parse_target_csv(_repo_path(root, TARGET_RELATIVE_PATH))
        schedule = rolling_origin.build_rolling_origin_schedule(rows)
        rolling_origin.validate_rolling_origin_schedule(schedule)
        window = schedule.windows[-1]
    except (
        OSError,
        rolling_origin.RollingOriginError,
        target_pipeline.TargetPipelineError,
        ValueError,
    ) as exc:
        raise InputContractError("monthly Arabica input window violates the fixed contract") from exc
    contract = input_contract()
    observed = {
        "context_start": window.historic_context_start.isoformat(),
        "context_end": window.historic_context_end.isoformat(),
        "context_row_count": len(window.context_rows),
        "cutoff": window.cutoff.isoformat(),
        "forecast_start": window.forecast_start.isoformat(),
        "forecast_end": window.forecast_end.isoformat(),
    }
    if any(observed[key] != contract[key] for key in observed):
        raise InputContractError("monthly Arabica input window violates the fixed contract")
    publication_protocol = p1_06.get("publication_protocol")
    if not isinstance(publication_protocol, Mapping):
        raise DependencyGateError("P1-06 or P1-07 prerequisite is not a validated pass")
    binding = {
        "p1_06_evidence_path": str(P1_06_EVIDENCE_RELATIVE_PATH),
        "p1_06_run_id": str(p1_06["run_id"]),
        "p1_06_classification": "pass",
        "p1_06_marker_state": str(publication_protocol["marker_state"]),
        "p1_06_reference_model_id": str(p1_06["reference_model_id"]),
        "p1_07_evidence_path": str(P1_07_EVIDENCE_RELATIVE_PATH),
        "p1_07_run_id": str(p1_07["run_id"]),
        "p1_07_classification": "pass",
        "p1_07_source_p1_06_run_id": str(p1_07_binding["p1_06_run_id"]),
        "target_path": str(TARGET_RELATIVE_PATH),
    }
    return binding, tuple(window.context_rows)


def _fallback_source_binding(root: Path) -> dict[str, str]:
    """Build the closed nonpass binding without claiming prerequisite validity."""

    p1_06_run_id = "unavailable"
    p1_07_run_id = "unavailable"
    try:
        raw_p1_06 = json.loads(_repo_path(root, P1_06_EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8"))
        if isinstance(raw_p1_06, Mapping) and isinstance(raw_p1_06.get("run_id"), str) and raw_p1_06["run_id"]:
            p1_06_run_id = raw_p1_06["run_id"]
    except (OSError, json.JSONDecodeError):
        pass
    try:
        raw_p1_07 = json.loads(_repo_path(root, P1_07_EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8"))
        if isinstance(raw_p1_07, Mapping) and isinstance(raw_p1_07.get("run_id"), str) and raw_p1_07["run_id"]:
            p1_07_run_id = raw_p1_07["run_id"]
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "p1_06_evidence_path": str(P1_06_EVIDENCE_RELATIVE_PATH),
        "p1_06_run_id": p1_06_run_id,
        "p1_06_classification": "unavailable",
        "p1_06_marker_state": "unavailable",
        "p1_06_reference_model_id": REFERENCE_MODEL_ID,
        "p1_07_evidence_path": str(P1_07_EVIDENCE_RELATIVE_PATH),
        "p1_07_run_id": p1_07_run_id,
        "p1_07_classification": "unavailable",
        "p1_07_source_p1_06_run_id": "unavailable",
        "target_path": str(TARGET_RELATIVE_PATH),
    }


def build_agent_frame(context_rows: Sequence[Any]) -> Any:
    """Convert only the history rows into TimeCopilot's public dataframe contract."""

    try:
        import pandas as pd
    except (ImportError, ModuleNotFoundError) as exc:
        raise ImportError("required runtime dependency is unavailable") from exc
    return pd.DataFrame(
        {
            "unique_id": [row.unique_id for row in context_rows],
            "ds": pd.to_datetime([row.ds.isoformat() for row in context_rows]),
            "y": [float(row.y) for row in context_rows],
        }
    )


def normalize_query_tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(part for part in re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE).split(" ") if part)


def query_anchors_present(value: object) -> bool:
    return isinstance(value, str) and REQUIRED_QUERY_ANCHORS.issubset(normalize_query_tokens(value))


def extract_message_history(result: object) -> dict[str, object]:
    """Extract only tool names and canonical provider/model observations."""

    try:
        all_messages = getattr(result, "all_messages", None)
        if not callable(all_messages):
            raise OutputContractError("agent message history is unavailable")
        messages = all_messages()
        if (
            not isinstance(messages, Sequence)
            or isinstance(messages, (str, bytes, bytearray))
            or isinstance(messages, Mapping)
        ):
            raise OutputContractError("agent message history is unavailable")
        response_count = 0
        metadata_valid = True
        calls: list[str] = []
        for message in messages:
            if message is None or isinstance(message, (str, bytes, bytearray, Mapping, int, float, bool)):
                raise OutputContractError("agent message history is unavailable")
            kind = getattr(message, "kind", None)
            parts = getattr(message, "parts", None)
            if (
                not isinstance(kind, str)
                or not kind
                or not isinstance(parts, Sequence)
                or isinstance(parts, (str, bytes, bytearray))
                or isinstance(parts, Mapping)
            ):
                raise OutputContractError("agent message history is unavailable")
            for part in parts:
                if part is None or isinstance(part, (str, bytes, bytearray, Mapping, int, float, bool)):
                    raise OutputContractError("agent message history is unavailable")
                part_kind = getattr(part, "part_kind", None)
                if not isinstance(part_kind, str) or not part_kind:
                    raise OutputContractError("agent message history is unavailable")
                if kind == "response" and part_kind == "tool-call":
                    name = getattr(part, "tool_name", None)
                    if not isinstance(name, str) or not name.strip():
                        raise OutputContractError("agent message history is unavailable")
                    calls.append(name.strip())
            if kind != "response":
                continue
            response_count += 1
            provider = getattr(message, "provider_name", None)
            model = getattr(message, "model_name", None)
            if not isinstance(provider, str) or not isinstance(model, str):
                metadata_valid = False
            else:
                normalized_provider = provider.strip().casefold()
                normalized_model = model.strip().casefold()
                if normalized_model.startswith("deepseek:"):
                    normalized_model = normalized_model[len("deepseek:"):]
                if normalized_provider != "deepseek" or normalized_model != "deepseek-v4-flash":
                    metadata_valid = False
        if response_count == 0 or not metadata_valid:
            observed_provider: str | None = None
            observed_model: str | None = None
        else:
            observed_provider = "deepseek"
            observed_model = "deepseek-v4-flash"
        if calls.count(DEFAULT_OUTPUT_TOOL_NAME) == 1:
            structured = DEFAULT_OUTPUT_TOOL_NAME
        else:
            structured = None
        workflow_calls = [name for name in calls if name != structured]
        return {
            "tool_calls": workflow_calls,
            "structured_output_tool": structured,
            "observed_provider": observed_provider,
            "observed_model": observed_model,
            "response_count": response_count,
        }
    except OutputContractError:
        raise
    except Exception:
        raise OutputContractError("agent message history is unavailable") from None


def assert_no_secret_material(value: object, *, exact_secret: str | None = None) -> None:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    if exact_secret and exact_secret in text:
        raise LocalContractError("secret material was detected")
    if GENERIC_SECRET_PATTERN.search(text):
        raise LocalContractError("secret material was detected")


def _classification_for(error_kind: str) -> str:
    if error_kind not in SANITIZED_REASONS:
        raise LocalContractError("diagnostic error kind is invalid")
    return "blocked" if error_kind in BLOCKED_ERROR_KINDS else "fail"


def diagnostic(stage: str, exception_class: str, error_kind: str) -> dict[str, str]:
    classification = _classification_for(error_kind)
    if stage not in STAGES or exception_class not in EXCEPTION_CLASSES:
        raise LocalContractError("diagnostic allowlist value is invalid")
    return {
        "classification": classification,
        "stage": stage,
        "exception_class": exception_class,
        "error_kind": error_kind,
        "sanitized_reason": SANITIZED_REASONS[error_kind],
    }


def _instant(now: datetime | None = None) -> tuple[str, str]:
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    return f"P1-08-{instant.strftime('%Y%m%dT%H%M%SZ')}", instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def _checks(**overrides: bool) -> dict[str, bool]:
    values = {key: False for key in CHECK_KEYS}
    values.update(overrides)
    return values


def build_evidence(
    *,
    source_binding: Mapping[str, str],
    classification: str,
    checks: Mapping[str, bool],
    diagnostics: Sequence[Mapping[str, str]],
    observed_provider: str | None = None,
    observed_model: str | None = None,
    tool_calls: Sequence[str] = (),
    structured_output_tool: str | None = None,
    forecast_analysis: str | None = None,
    user_query_response: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    run_id, timestamp = _instant(now)
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": run_id,
        "timestamp_utc": timestamp,
        "classification": classification,
        "source_binding": dict(source_binding),
        "query": QUERY,
        "requested_llm": REQUESTED_LLM,
        "observed_provider": observed_provider,
        "observed_model": observed_model,
        "input_contract": input_contract(),
        "tool_calls": list(tool_calls),
        "structured_output_tool": structured_output_tool,
        "forecast_analysis": forecast_analysis,
        "user_query_response": user_query_response,
        "checks": dict(checks),
        "diagnostics": [dict(item) for item in diagnostics],
        "artifact_paths": list(ARTIFACT_PATHS),
    }


def _exact_mapping(value: object, keys: Sequence[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise LocalContractError(f"{label} differs from the closed schema")
    return value


def validate_evidence(record: Mapping[str, object], *, exact_secret: str | None = None) -> None:
    _exact_mapping(record, TOP_LEVEL_KEYS, "evidence")
    if record.get("schema_version") != 1 or type(record.get("schema_version")) is not int or record.get("task_id") != TASK_ID:
        raise LocalContractError("evidence identity is invalid")
    run_match = RUN_ID_PATTERN.fullmatch(str(record.get("run_id", "")))
    if run_match is None:
        raise LocalContractError("run ID is invalid")
    try:
        expected_timestamp = datetime.strptime(run_match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        actual_timestamp = datetime.strptime(str(record.get("timestamp_utc")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise LocalContractError("timestamp is invalid") from exc
    if actual_timestamp != expected_timestamp:
        raise LocalContractError("timestamp does not match run ID")
    classification = record.get("classification")
    if classification not in {"pass", "fail", "blocked"}:
        raise LocalContractError("classification is invalid")
    binding = _exact_mapping(record.get("source_binding"), SOURCE_BINDING_KEYS, "source binding")
    if any(not isinstance(value, str) or not value for value in binding.values()):
        raise LocalContractError("source binding fields must be non-empty strings")
    fixed_binding = {
        "p1_06_evidence_path": str(P1_06_EVIDENCE_RELATIVE_PATH),
        "p1_06_reference_model_id": REFERENCE_MODEL_ID,
        "p1_07_evidence_path": str(P1_07_EVIDENCE_RELATIVE_PATH),
        "target_path": str(TARGET_RELATIVE_PATH),
    }
    if any(binding.get(key) != value for key, value in fixed_binding.items()):
        raise LocalContractError("source binding differs from the fixed contract")
    binding_statuses = {
        "p1_06_classification": binding.get("p1_06_classification"),
        "p1_06_marker_state": binding.get("p1_06_marker_state"),
        "p1_07_classification": binding.get("p1_07_classification"),
    }
    if classification == "pass":
        if binding_statuses != {
            "p1_06_classification": "pass",
            "p1_06_marker_state": "pass_final",
            "p1_07_classification": "pass",
        } or binding.get("p1_07_source_p1_06_run_id") != binding.get("p1_06_run_id"):
            raise LocalContractError("validated pass source binding is inconsistent")
    else:
        if (
            binding.get("p1_06_classification") not in {"pass", "unavailable"}
            or binding.get("p1_06_marker_state") not in {"pass_final", "unavailable"}
            or binding.get("p1_07_classification") not in {"pass", "unavailable"}
        ):
            raise LocalContractError("nonpass source binding status is invalid")
        if (
            binding.get("p1_06_classification") == "pass"
            and binding.get("p1_07_classification") == "pass"
            and binding.get("p1_07_source_p1_06_run_id") != binding.get("p1_06_run_id")
        ):
            raise LocalContractError("nonpass source binding does not match validated prerequisites")
    if record.get("query") != QUERY or record.get("requested_llm") != REQUESTED_LLM:
        raise LocalContractError("query or requested LLM differs from the fixed contract")
    if dict(_exact_mapping(record.get("input_contract"), INPUT_CONTRACT_KEYS, "input contract")) != input_contract():
        raise LocalContractError("input contract differs from the fixed contract")
    for key in ("observed_provider", "observed_model", "structured_output_tool", "forecast_analysis", "user_query_response"):
        value = record.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise LocalContractError(f"{key} must be null or a non-empty string")
    observed_provider = record.get("observed_provider")
    observed_model = record.get("observed_model")
    if (observed_provider, observed_model) not in {
        (None, None),
        ("deepseek", "deepseek-v4-flash"),
    }:
        raise LocalContractError("observed provider/model pair is invalid")
    structured_output_tool = record.get("structured_output_tool")
    if structured_output_tool not in {None, DEFAULT_OUTPUT_TOOL_NAME}:
        raise LocalContractError("structured output tool is invalid")
    calls = record.get("tool_calls")
    if not isinstance(calls, list) or any(not isinstance(item, str) or not item for item in calls):
        raise LocalContractError("tool calls must be strings")
    checks = _exact_mapping(record.get("checks"), CHECK_KEYS, "checks")
    if any(type(value) is not bool for value in checks.values()):
        raise LocalContractError("checks must be booleans")
    derived_checks = {
        "provider_resolved": record.get("observed_provider") == "deepseek",
        "model_resolved": record.get("observed_model") == "deepseek-v4-flash",
        "provider_model_consistent": (
            record.get("observed_provider") == "deepseek"
            and record.get("observed_model") == "deepseek-v4-flash"
        ),
        "required_tool_calls_exact": calls == list(REQUIRED_TOOL_CALLS),
        "analysis_nonempty": (
            isinstance(record.get("forecast_analysis"), str)
            and bool(str(record["forecast_analysis"]).strip())
        ),
        "query_response_nonempty": (
            isinstance(record.get("user_query_response"), str)
            and bool(str(record["user_query_response"]).strip())
        ),
        "query_anchors_present": query_anchors_present(record.get("user_query_response")),
    }
    if any(checks.get(key) is not expected for key, expected in derived_checks.items()):
        raise LocalContractError("checks differ from derived evidence state")
    raw_diagnostics = record.get("diagnostics")
    if not isinstance(raw_diagnostics, list):
        raise LocalContractError("diagnostics must be a list")
    for raw in raw_diagnostics:
        item = _exact_mapping(raw, DIAGNOSTIC_KEYS, "diagnostic")
        error_kind = item.get("error_kind")
        if not isinstance(error_kind, str) or error_kind not in SANITIZED_REASONS:
            raise LocalContractError("diagnostic error kind is invalid")
        if (
            item.get("classification") != classification
            or item.get("classification") != _classification_for(error_kind)
            or item.get("stage") not in STAGES
            or item.get("exception_class") not in EXCEPTION_CLASSES
            or item.get("sanitized_reason") != SANITIZED_REASONS[error_kind]
        ):
            raise LocalContractError("diagnostic mapping is inconsistent")
    secret_detected = any(
        isinstance(raw, Mapping) and raw.get("error_kind") == "secret_detected"
        for raw in raw_diagnostics
    )
    if checks.get("secret_free") is not (not secret_detected):
        raise LocalContractError("secret-free check differs from diagnostics")
    if classification != "pass":
        diagnostic_stages = {str(item["stage"]) for item in raw_diagnostics}
        prerequisite_checks = {
            "dependency_gate_pass": checks.get("dependency_gate_pass"),
            "env_key_loaded": checks.get("env_key_loaded"),
            "input_window_valid": checks.get("input_window_valid"),
            "no_future_leakage": checks.get("no_future_leakage"),
        }
        if diagnostic_stages in ({"dependency_gate"}, {"input"}):
            expected_prerequisite_checks = {
                "dependency_gate_pass": False,
                "env_key_loaded": False,
                "input_window_valid": False,
                "no_future_leakage": False,
            }
        elif diagnostic_stages == {"credential"}:
            expected_prerequisite_checks = {
                "dependency_gate_pass": True,
                "env_key_loaded": False,
                "input_window_valid": True,
                "no_future_leakage": True,
            }
        elif diagnostic_stages and diagnostic_stages.issubset(
            {
                "dataframe_construction", "forecaster_construction",
                "provider_resolution", "request", "response", "publication", "roadmap",
            }
        ):
            expected_prerequisite_checks = {
                "dependency_gate_pass": True,
                "env_key_loaded": True,
                "input_window_valid": True,
                "no_future_leakage": True,
            }
        else:
            raise LocalContractError("diagnostic stages do not describe one run progression")
        if prerequisite_checks != expected_prerequisite_checks:
            raise LocalContractError("prerequisite checks differ from diagnostic stage")
    if record.get("artifact_paths") != list(ARTIFACT_PATHS):
        raise LocalContractError("artifact paths differ from the fixed order")
    if classification == "pass":
        required_text = ("observed_provider", "observed_model", "structured_output_tool", "forecast_analysis", "user_query_response")
        if any(not isinstance(record.get(key), str) or not str(record[key]).strip() for key in required_text):
            raise LocalContractError("pass evidence has empty required output")
        if (
            record.get("structured_output_tool") != DEFAULT_OUTPUT_TOOL_NAME
            or raw_diagnostics
            or any(checks.get(key) is not True for key in PASS_REQUIRED_CHECK_KEYS)
        ):
            raise LocalContractError("pass evidence state is inconsistent")
    else:
        if not raw_diagnostics or checks.get("roadmap_eligible") is not False:
            raise LocalContractError("nonpass evidence state is inconsistent")
    assert_no_secret_material(record, exact_secret=exact_secret)


def render_markdown(record: Mapping[str, object]) -> str:
    diagnostics = record["diagnostics"]
    assert isinstance(diagnostics, list)
    raw_tool_calls = record["tool_calls"]
    if not isinstance(raw_tool_calls, list) or any(not isinstance(item, str) for item in raw_tool_calls):
        raise LocalContractError("tool calls must be strings")
    tool_calls = cast(list[str], raw_tool_calls)
    lines = [
        "# Phase 1 Natural-Language Exercise",
        "",
        f"- Classification: `{record['classification']}`",
        f"- Run ID: `{record['run_id']}`",
        f"- Requested LLM: `{record['requested_llm']}`",
        f"- Observed provider/model: `{record['observed_provider'] or 'none'}` / `{record['observed_model'] or 'none'}`",
        f"- Tool calls: `{', '.join(tool_calls) or 'none'}`",
        f"- Structured output tool: `{record['structured_output_tool'] or 'none'}`",
        "",
        "## Fixed Query",
        "",
        str(record["query"]),
        "",
        "## Forecast Analysis",
        "",
        str(record["forecast_analysis"] or "Unavailable for this nonpass attempt."),
        "",
        "## User Query Response",
        "",
        str(record["user_query_response"] or "Unavailable for this nonpass attempt."),
        "",
        "## Diagnostics",
        "",
    ]
    if diagnostics:
        lines.extend(
            f"- `{item['classification']}` / `{item['error_kind']}`: {item['sanitized_reason']}"
            for item in diagnostics
        )
    else:
        lines.append("- None.")
    lines.extend(["", f"Machine-readable evidence: `{EVIDENCE_RELATIVE_PATH}`", ""])
    return "\n".join(lines)


def _stage_bytes(destination: Path, payload: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    staged = Path(name)
    completed = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        completed = True
    finally:
        if not completed:
            staged.unlink(missing_ok=True)
    return staged


def publish_bundle(
    record: Mapping[str, object],
    root: Path,
    *,
    exact_secret: str | None = None,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> dict[str, object]:
    validate_evidence(record, exact_secret=exact_secret)
    markdown_bytes = render_markdown(record).encode("utf-8")
    evidence_bytes = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    assert_no_secret_material(markdown_bytes.decode("utf-8"), exact_secret=exact_secret)
    assert_no_secret_material(evidence_bytes.decode("utf-8"), exact_secret=exact_secret)
    destinations = (
        (_repo_path(root, FINDING_RELATIVE_PATH), markdown_bytes),
        (_repo_path(root, EVIDENCE_RELATIVE_PATH), evidence_bytes),
    )
    staged: list[tuple[Path, Path]] = []
    originals: dict[Path, bytes | None] = {}
    committed: list[Path] = []
    try:
        originals = {
            destination: destination.read_bytes() if destination.exists() else None
            for destination, _ in destinations
        }
        for destination, payload in destinations:
            staged.append((_stage_bytes(destination, payload), destination))
        for temporary, destination in staged:  # Markdown first, JSON commit marker last.
            replace_file(temporary, destination)
            committed.append(destination)
    except Exception as exc:
        for destination in reversed(committed):
            original = originals[destination]
            if original is None:
                destination.unlink(missing_ok=True)
            else:
                rollback = _stage_bytes(destination, original)
                try:
                    os.replace(rollback, destination)
                finally:
                    rollback.unlink(missing_ok=True)
        raise PublicationError("canonical P1-08 publication failed") from exc
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return validate_publication(root)


def validate_publication(root: Path | None = None) -> dict[str, object]:
    active_root = (root or Path.cwd()).resolve()
    try:
        value = json.loads(_repo_path(active_root, EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationError("canonical P1-08 evidence is unavailable") from exc
    if not isinstance(value, dict):
        raise PublicationError("canonical P1-08 evidence must be an object")
    validate_evidence(value)
    if value["classification"] == "pass":
        try:
            current_binding, _ = load_validated_input(active_root)
        except (DependencyGateError, InputContractError) as exc:
            raise PublicationError("canonical P1-08 evidence is stale against prerequisites") from exc
        if value["source_binding"] != current_binding:
            raise PublicationError("canonical P1-08 source binding is stale")
    try:
        markdown = _repo_path(active_root, FINDING_RELATIVE_PATH).read_text(encoding="utf-8")
    except OSError as exc:
        raise PublicationError("canonical P1-08 finding is unavailable") from exc
    if markdown != render_markdown(value):
        raise PublicationError("canonical P1-08 finding differs from evidence")
    assert_no_secret_material(markdown)
    return value


def _external_diagnostic(exc: Exception, *, stage: str) -> dict[str, str]:
    name = type(exc).__name__
    detail = str(exc).casefold()
    if name in {"UserError", "AuthenticationError", "PermissionDeniedError"}:
        return diagnostic(stage, name, "authentication_rejected")
    if name == "RateLimitError":
        return diagnostic(stage, name, "rate_limited")
    if name == "ProxyError":
        return diagnostic(stage, name, "proxy_unavailable")
    if name in {"APITimeoutError", "TimeoutException"}:
        return diagnostic(stage, name, "timeout")
    if name in {"APIConnectionError", "ConnectError"}:
        return diagnostic(stage, name, "network_unavailable")
    if name == "ModelAPIError":
        if "proxy" in detail or "socks" in detail:
            return diagnostic(stage, name, "proxy_unavailable")
        if "timeout" in detail:
            return diagnostic(stage, name, "timeout")
        if "connect" in detail or "network" in detail:
            return diagnostic(stage, name, "network_unavailable")
        if stage == "request":
            return diagnostic(stage, name, "provider_request_failed")
        return diagnostic(stage, name, "provider_unavailable")
    if name == "ModelHTTPError":
        status_code = getattr(exc, "status_code", None)
        if status_code in {401, 403}:
            return diagnostic(stage, name, "authentication_rejected")
        if status_code == 429:
            return diagnostic(stage, name, "rate_limited")
        return diagnostic(stage, name, "provider_request_failed")
    if name in {"ImportError", "ModuleNotFoundError"} and ("proxy" in detail or "socks" in detail):
        return diagnostic(stage, name, "proxy_unavailable")
    if name in {"ImportError", "ModuleNotFoundError"}:
        return diagnostic(stage, name, "runtime_dependency_unavailable")
    if name == "OSError":
        return diagnostic(stage, name, "runtime_dependency_unavailable")
    if name == "UnexpectedModelBehavior":
        return diagnostic("response", name, "provider_response_invalid")
    return diagnostic(stage, "ExternalRuntimeError", "unexpected_runtime_failure")


def run_live_exercise(
    root: Path | None = None,
    *,
    timecopilot_factory: Callable[..., object] | None = None,
    forecaster_factory: Callable[[], object] | None = None,
    environ: MutableMapping[str, str] | None = None,
    env_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Execute the fixed request once and return a validated secret-free record."""

    active_root = (root or Path.cwd()).resolve()
    checks = _checks()
    try:
        binding, context_rows = load_validated_input(active_root)
        checks.update(dependency_gate_pass=True, input_window_valid=True, no_future_leakage=True)
    except DependencyGateError:
        checks["secret_free"] = True
        item = diagnostic("dependency_gate", "DependencyGateError", "prerequisite_not_pass")
        record = build_evidence(
            source_binding=_fallback_source_binding(active_root),
            classification="fail",
            checks=checks,
            diagnostics=(item,),
            now=now,
        )
        validate_evidence(record)
        return record
    except InputContractError:
        checks["secret_free"] = True
        item = diagnostic("input", "InputContractError", "invalid_input_window")
        record = build_evidence(
            source_binding=_fallback_source_binding(active_root),
            classification="fail",
            checks=checks,
            diagnostics=(item,),
            now=now,
        )
        validate_evidence(record)
        return record
    try:
        secret = load_deepseek_api_key(env_path or active_root / ".env", environ=environ)
        checks["env_key_loaded"] = True
    except CredentialUnavailable:
        checks["secret_free"] = True
        item = diagnostic("credential", "CredentialUnavailable", "missing_credential")
        record = build_evidence(source_binding=binding, classification="blocked", checks=checks, diagnostics=(item,), now=now)
        validate_evidence(record)
        return record
    except EnvContractError:
        checks["secret_free"] = True
        item = diagnostic("credential", "EnvContractError", "malformed_env")
        record = build_evidence(source_binding=binding, classification="fail", checks=checks, diagnostics=(item,), now=now)
        validate_evidence(record)
        return record
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    agent: Any
    try:
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            frame = build_agent_frame(context_rows)
    except Exception as exc:
        try:
            assert_no_secret_material(captured_stdout.getvalue(), exact_secret=secret)
            assert_no_secret_material(captured_stderr.getvalue(), exact_secret=secret)
        except LocalContractError:
            item = diagnostic("dataframe_construction", "OutputContractError", "secret_detected")
        else:
            checks["secret_free"] = True
            item = _external_diagnostic(exc, stage="dataframe_construction")
        record = build_evidence(source_binding=binding, classification=item["classification"], checks=checks, diagnostics=(item,), now=now)
        validate_evidence(record)
        return record
    try:
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            if forecaster_factory is None:
                from timecopilot.models.foundation.chronos import Chronos
                forecaster_factory = lambda: Chronos(repo_id=REFERENCE_MODEL_ID, batch_size=1, alias="P105")
            forecaster = forecaster_factory()
    except Exception as exc:
        try:
            assert_no_secret_material(captured_stdout.getvalue(), exact_secret=secret)
            assert_no_secret_material(captured_stderr.getvalue(), exact_secret=secret)
        except LocalContractError:
            item = diagnostic("forecaster_construction", "OutputContractError", "secret_detected")
        else:
            checks["secret_free"] = True
            item = _external_diagnostic(exc, stage="forecaster_construction")
        record = build_evidence(source_binding=binding, classification=item["classification"], checks=checks, diagnostics=(item,), now=now)
        validate_evidence(record)
        return record
    try:
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            if timecopilot_factory is None:
                from timecopilot import TimeCopilot
                timecopilot_factory = TimeCopilot
            agent = timecopilot_factory(llm=REQUESTED_LLM, forecasters=[forecaster])
    except Exception as exc:
        try:
            assert_no_secret_material(captured_stdout.getvalue(), exact_secret=secret)
            assert_no_secret_material(captured_stderr.getvalue(), exact_secret=secret)
        except LocalContractError:
            item = diagnostic("provider_resolution", "OutputContractError", "secret_detected")
        else:
            checks["secret_free"] = True
            item = _external_diagnostic(exc, stage="provider_resolution")
        record = build_evidence(source_binding=binding, classification=item["classification"], checks=checks, diagnostics=(item,), now=now)
        validate_evidence(record)
        return record
    try:
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            result = agent.forecast(  # type: ignore[attr-defined]
                df=frame,
                h=3,
                freq="MS",
                seasonality=12,
                query=QUERY,
            )
    except Exception as exc:
        try:
            assert_no_secret_material(captured_stdout.getvalue(), exact_secret=secret)
            assert_no_secret_material(captured_stderr.getvalue(), exact_secret=secret)
        except LocalContractError:
            item = diagnostic("request", "OutputContractError", "secret_detected")
        else:
            checks["secret_free"] = True
            item = _external_diagnostic(exc, stage="request")
        record = build_evidence(source_binding=binding, classification=item["classification"], checks=checks, diagnostics=(item,), now=now)
        validate_evidence(record)
        return record
    try:
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            history = extract_message_history(result)
    except OutputContractError:
        try:
            assert_no_secret_material(captured_stdout.getvalue(), exact_secret=secret)
            assert_no_secret_material(captured_stderr.getvalue(), exact_secret=secret)
        except LocalContractError:
            item = diagnostic("response", "OutputContractError", "secret_detected")
        else:
            checks["secret_free"] = True
            item = diagnostic("response", "OutputContractError", "output_contract_failed")
        record = build_evidence(
            source_binding=binding,
            classification="fail",
            checks=checks,
            diagnostics=(item,),
            now=now,
        )
        validate_evidence(record)
        return record
    try:
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            output = getattr(result, "output", None)
            analysis = getattr(output, "forecast_analysis", None)
            response = getattr(output, "user_query_response", None)
            analysis = analysis.strip() if isinstance(analysis, str) and analysis.strip() else None
            response = response.strip() if isinstance(response, str) and response.strip() else None
    except Exception:
        try:
            assert_no_secret_material(captured_stdout.getvalue(), exact_secret=secret)
            assert_no_secret_material(captured_stderr.getvalue(), exact_secret=secret)
        except LocalContractError:
            item = diagnostic("response", "OutputContractError", "secret_detected")
        else:
            checks["secret_free"] = True
            item = diagnostic("response", "OutputContractError", "output_contract_failed")
        record = build_evidence(
            source_binding=binding,
            classification="fail",
            checks=checks,
            diagnostics=(item,),
            now=now,
        )
        validate_evidence(record)
        return record
    calls = history["tool_calls"]
    structured = history["structured_output_tool"]
    checks.update(
        provider_resolved=history["observed_provider"] == "deepseek",
        model_resolved=history["observed_model"] == "deepseek-v4-flash",
        provider_model_consistent=history["observed_provider"] == "deepseek" and history["observed_model"] == "deepseek-v4-flash",
        required_tool_calls_exact=calls == list(REQUIRED_TOOL_CALLS),
        analysis_nonempty=analysis is not None,
        query_response_nonempty=response is not None,
        query_anchors_present=query_anchors_present(response),
    )
    failures: list[dict[str, str]] = []
    if history["response_count"] == 0:
        failures.append(diagnostic("response", "UnexpectedModelBehavior", "provider_response_invalid"))
    else:
        if not checks["provider_model_consistent"]:
            failures.append(diagnostic("response", "UnexpectedModelBehavior", "provider_response_invalid"))
        if (
            structured != DEFAULT_OUTPUT_TOOL_NAME
            or not checks["analysis_nonempty"]
            or not checks["query_response_nonempty"]
            or not checks["query_anchors_present"]
        ):
            failures.append(diagnostic("response", "OutputContractError", "output_contract_failed"))
    record = build_evidence(
        source_binding=binding,
        classification="fail" if failures else "pass",
        checks=checks,
        diagnostics=failures,
        observed_provider=cast(str | None, history["observed_provider"]),
        observed_model=cast(str | None, history["observed_model"]),
        tool_calls=calls,  # type: ignore[arg-type]
        structured_output_tool=structured if isinstance(structured, str) else None,
        forecast_analysis=analysis,
        user_query_response=response,
        now=now,
    )
    try:
        assert_no_secret_material(record, exact_secret=secret)
        assert_no_secret_material(captured_stdout.getvalue(), exact_secret=secret)
        assert_no_secret_material(captured_stderr.getvalue(), exact_secret=secret)
        checks["secret_free"] = True
    except LocalContractError:
        secret_item = diagnostic("response", "OutputContractError", "secret_detected")
        record = build_evidence(
            source_binding=binding,
            classification="fail",
            checks=checks,
            diagnostics=(secret_item,),
            now=now,
        )
        validate_evidence(record)
        return record
    record["checks"] = dict(checks)
    if not failures:
        checks["roadmap_eligible"] = True
        record["checks"] = dict(checks)
    validate_evidence(record, exact_secret=secret)
    return record


def update_roadmap(root: Path | None = None) -> None:
    active_root = (root or Path.cwd()).resolve()
    record = validate_publication(active_root)
    if record["classification"] != "pass" or record["checks"]["roadmap_eligible"] is not True:  # type: ignore[index]
        raise PublicationError("P1-08 roadmap update requires validated pass evidence")
    path = _repo_path(active_root, ROADMAP_RELATIVE_PATH)
    original = path.read_text(encoding="utf-8")
    matches = ROADMAP_PATTERN.findall(original)
    if matches not in ([" "], ["x"]):
        raise PublicationError("roadmap must contain exactly one P1-08 checkbox")
    if matches == ["x"]:
        return
    updated = ROADMAP_PATTERN.sub(lambda match: match.group(0).replace("[ ]", "[x]", 1), original, count=1)
    staged = _stage_bytes(path, updated.encode("utf-8"))
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def check_roadmap(root: Path | None = None) -> bool:
    active_root = (root or Path.cwd()).resolve()
    record = validate_publication(active_root)
    matches = ROADMAP_PATTERN.findall(_repo_path(active_root, ROADMAP_RELATIVE_PATH).read_text(encoding="utf-8"))
    if len(matches) != 1:
        raise PublicationError("roadmap must contain exactly one P1-08 checkbox")
    return (matches == ["x"]) == (record["classification"] == "pass")


def build_live_child_environment(
    runtime_dir: Path,
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the isolated runtime required before importing TimeCopilot."""

    source = dict(os.environ if environ is None else environ)
    try:
        configured = runtime_compatibility.configure_cuda_environment(source)
    except runtime_compatibility.RuntimePreflightError as exc:
        raise OSError("required runtime dependency is unavailable") from exc

    runtime_dir = runtime_dir.resolve()
    cache_dirs = {
        "MPLCONFIGDIR": runtime_dir / "matplotlib",
        "HF_HOME": runtime_dir / "huggingface",
        "TORCH_HOME": runtime_dir / "torch",
        "XDG_CACHE_HOME": runtime_dir / "xdg",
    }
    for path in cache_dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    configured.update({name: str(path) for name, path in cache_dirs.items()})
    configured["HF_HUB_CACHE"] = str(cache_dirs["HF_HOME"] / "hub")
    configured["PYTHONPATH"] = str((root / "src").resolve())
    configured[RUNTIME_PREPARED_ENV] = "1"
    configured.pop("ALL_PROXY", None)
    configured.pop("all_proxy", None)
    configured.pop("HF_HUB_OFFLINE", None)
    configured.pop("TRANSFORMERS_OFFLINE", None)
    return configured


def run_live_child(
    root: Path,
    *,
    publish: bool,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run the live exercise once in a prepared child process."""

    with tempfile.TemporaryDirectory(prefix="p1-08-runtime.", dir="/tmp") as directory:
        environment = build_live_child_environment(
            Path(directory),
            root,
            environ=environ,
        )
        command = [
            sys.executable,
            "-m",
            "commodity_forecasting.phase1.natural_language",
            "--repo-root",
            str(root),
            "--live",
        ]
        if publish:
            command.append("--publish")
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            check=False,
        )
    return completed.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--live", action="store_true")
    actions.add_argument("--validate-publication", action="store_true")
    actions.add_argument("--update-roadmap", action="store_true")
    actions.add_argument("--check-roadmap", action="store_true")
    parser.add_argument("--publish", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.repo_root.resolve()
    try:
        if arguments.live:
            if os.environ.get(RUNTIME_PREPARED_ENV) != "1":
                return run_live_child(root, publish=arguments.publish)
            record = run_live_exercise(root)
            if arguments.publish:
                publish_bundle(record, root)
            return 0 if record["classification"] == "pass" else 1
        if arguments.publish:
            raise PublicationError("--publish is valid only with --live")
        if arguments.validate_publication:
            validate_publication(root)
        elif arguments.update_roadmap:
            update_roadmap(root)
        elif arguments.check_roadmap and not check_roadmap(root):
            raise PublicationError("P1-08 roadmap is inconsistent with validated evidence")
    except (NaturalLanguageError, OSError) as exc:
        print(f"natural-language: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
