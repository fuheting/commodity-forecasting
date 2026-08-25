"""Validate Phase 1 evidence and publish a bounded exit rollup."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypedDict, cast

from . import (
    backtest_publication,
    evaluation_publication,
    model_screening,
    natural_language_publication,
    readiness_evidence,
    runtime_compatibility,
    shortlist_approval,
    target_publication,
)


TASK_ID = "P1-09"
SCHEMA_VERSION = 1
ROADMAP_RELATIVE_PATH = Path("docs/roadmap.md")
FINDING_RELATIVE_PATH = Path("docs/findings/phase1/exit_rollup.md")
EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/exit_rollup.json")
PREDECESSOR_TASK_IDS = tuple(f"P1-{number:02d}" for number in range(1, 9))
OWNED_TASK_IDS = PREDECESSOR_TASK_IDS + (TASK_ID,)
NON_PASS_OUTCOMES = frozenset(
    {"missing", "malformed", "stale", "blocked", "unsupported", "unknown", "failed"}
)
OBSERVATION_KINDS = frozenset(
    {"limitations", "unknowns", "diagnostics", "errors", "candidate_non_pass"}
)

_CURRENT_STATUS_PATTERN = re.compile(r"(?m)^## Current Status:.*$")
_PHASE_ONE_HEADING_PATTERN = re.compile(
    r"(?m)^## Phase 1: Monthly Arabica History-Only Forecasting.*$"
)
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class RollupError(RuntimeError):
    """Base error for P1-09 validation and publication failures."""


class EvidenceRollupError(RollupError):
    """Raised when the exit record or predecessor evidence is invalid."""


class RoadmapTransformError(RollupError):
    """Raised when the roadmap cannot be transformed without ambiguity."""


class PublicationError(RollupError):
    """Raised when an output cannot be staged, replaced, or revalidated."""


class TaskResult(TypedDict):
    task_id: str
    evidence_path: str
    finding_path: str
    outcome: str
    reason: str


class IncompleteGate(TypedDict):
    task_id: str
    source_path: str
    outcome: str
    reason: str


class Observation(TypedDict):
    task_id: str
    source_path: str
    kind: str
    field: str
    value: Any


class ExitRecord(TypedDict):
    schema_version: int
    task_id: str
    generated_at_utc: str
    phase_outcome: str
    task_results: list[TaskResult]
    incomplete_gates: list[IncompleteGate]
    preserved_observations: list[Observation]
    roadmap_expectations: dict[str, Any]
    artifact_paths: dict[str, str]


ReplaceFile = Callable[[Path, Path], None]


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    evidence_path: Path
    finding_path: Path


@dataclass
class ValidationContext:
    """Cached canonical results shared by dependent evidence-only validators."""

    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, BaseException] = field(default_factory=dict)
    pre_read_failures: set[str] = field(default_factory=set)


def _task_specs() -> tuple[TaskSpec, ...]:
    return (
        TaskSpec(
            "P1-01",
            Path("docs/findings/phase1/evidence/dependency_readiness.json"),
            Path("docs/findings/phase1/dependency_readiness.md"),
        ),
        TaskSpec("P1-02", target_publication.EVIDENCE_RELATIVE_PATH, target_publication.FINDING_RELATIVE_PATH),
        TaskSpec("P1-03", model_screening.EVIDENCE_RELATIVE_PATH, model_screening.FINDING_RELATIVE_PATH),
        TaskSpec("P1-04", shortlist_approval.EVIDENCE_RELATIVE_PATH, shortlist_approval.FINDING_RELATIVE_PATH),
        TaskSpec("P1-05", runtime_compatibility.EVIDENCE_RELATIVE_PATH, runtime_compatibility.FINDING_RELATIVE_PATH),
        TaskSpec("P1-06", backtest_publication.EVIDENCE_RELATIVE_PATH, backtest_publication.FINDING_RELATIVE_PATH),
        TaskSpec("P1-07", evaluation_publication.EVIDENCE_RELATIVE_PATH, evaluation_publication.FINDING_RELATIVE_PATH),
        TaskSpec(
            "P1-08",
            natural_language_publication.EVIDENCE_RELATIVE_PATH,
            natural_language_publication.FINDING_RELATIVE_PATH,
        ),
    )


def _spec(task_id: str) -> TaskSpec:
    for item in _task_specs():
        if item.task_id == task_id:
            return item
    raise EvidenceRollupError(f"unsupported predecessor task: {task_id}")


def _root(repo_root: Path) -> Path:
    root = repo_root.resolve()
    if not root.is_dir():
        raise EvidenceRollupError(f"repository root is not a directory: {root}")
    return root


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json_record(path: Path) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Read an evidence object while retaining an exact, user-visible failure reason."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"canonical evidence file does not exist: {path.as_posix()}", "missing"
    except json.JSONDecodeError as exc:
        return None, f"canonical evidence JSON is malformed: {exc}", "malformed"
    except UnicodeDecodeError as exc:
        return None, f"canonical evidence text encoding is malformed: {exc}", "malformed"
    except OSError as exc:
        raise EvidenceRollupError(f"canonical evidence file could not be read: {exc}") from exc
    if not isinstance(value, dict):
        return None, "canonical evidence JSON must be an object", "malformed"
    return cast(dict[str, Any], value), None, None


def _finding_encoding_failure(path: Path) -> str | None:
    """Return an exact malformed-text reason without absorbing filesystem failures."""

    if not path.is_file():
        return None
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return f"canonical finding text encoding is malformed: {path.as_posix()}: {exc}"
    except OSError as exc:
        raise EvidenceRollupError(f"canonical finding file could not be read: {exc}") from exc
    return None


def _outcome_value(record: Mapping[str, Any] | None, task_id: str) -> str:
    if record is None:
        return "failed"
    if task_id == "P1-03":
        value = record.get("overall_classification")
        if value == "pass":
            return "pass"
    elif task_id == "P1-04":
        if record.get("classification") == "approved" and record.get("execution_authorized") is True:
            return "pass"
    elif task_id == "P1-05":
        if record.get("task_outcome") == "pass":
            return "pass"
    elif record.get("classification") == "pass":
        return "pass"

    for key in ("classification", "overall_classification", "task_outcome"):
        value = record.get(key)
        if isinstance(value, str):
            normalized = value.lower()
            if normalized in {"pass", "approved"}:
                return "pass"
            if normalized in NON_PASS_OUTCOMES:
                return normalized
            if normalized == "fail":
                return "failed"
            if normalized == "unknown/ineligible":
                return "unknown"
    return "failed"


def _stable_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _record_reason(record: Mapping[str, Any] | None, task_id: str, outcome: str) -> str:
    if outcome == "pass":
        return "canonical validator passed"
    if record is not None:
        for key in ("reason", "failure_reason", "error", "errors", "diagnostics", "non_pass_diagnostics"):
            value = record.get(key)
            if value not in (None, "", [], {}):
                return _stable_value(value)
        for key in ("classification", "overall_classification", "task_outcome"):
            value = record.get(key)
            if value not in (None, "", [], {}):
                return f"canonical evidence reported {key}={value!r}"
    return f"canonical evidence outcome is {outcome}"


def _failure_category(
    spec: TaskSpec,
    error: BaseException,
    raw_record: Mapping[str, Any] | None,
    read_category: str | None,
) -> str:
    if read_category is not None:
        return read_category
    if raw_record is not None:
        raw_outcome = _outcome_value(raw_record, spec.task_id)
        if raw_outcome in NON_PASS_OUTCOMES:
            return raw_outcome
    message = str(error).lower()
    if "stale" in message or "hash mismatch" in message:
        return "stale"
    if "unsupported" in message:
        return "unsupported"
    if "unknown" in message:
        return "unknown"
    if "blocked" in message or "unavailable" in message:
        return "blocked"
    if "missing" in message or "does not exist" in message:
        return "missing"
    if "malformed" in message or "schema" in message or "must be" in message:
        return "malformed"
    return "failed"


def _result(
    spec: TaskSpec,
    outcome: str,
    reason: str,
) -> TaskResult:
    return {
        "task_id": spec.task_id,
        "evidence_path": spec.evidence_path.as_posix(),
        "finding_path": spec.finding_path.as_posix(),
        "outcome": outcome,
        "reason": reason,
    }


def _failed_result(
    spec: TaskSpec,
    error: BaseException,
    raw_record: Mapping[str, Any] | None,
    read_category: str | None = None,
    read_reason: str | None = None,
) -> TaskResult:
    category = _failure_category(spec, error, raw_record, read_category)
    reason = read_reason if read_reason is not None else str(error) or type(error).__name__
    return _result(spec, category, reason)


def _dependency_failed_result(
    spec: TaskSpec,
    error: BaseException,
    raw_record: Mapping[str, Any] | None,
) -> TaskResult:
    """Report an explicit dependent-task failure without parsing upstream text."""

    raw_outcome = _outcome_value(raw_record, spec.task_id)
    outcome = raw_outcome if raw_outcome != "pass" else "failed"
    return _result(spec, outcome, str(error) or type(error).__name__)


def _validate_p101(root: Path, context: ValidationContext) -> tuple[TaskResult, dict[str, Any] | None]:
    spec = _spec("P1-01")
    evidence_path = root / spec.evidence_path
    raw, read_reason, read_category = _read_json_record(evidence_path)
    if raw is None:
        context.errors[spec.task_id] = EvidenceRollupError(cast(str, read_reason))
        context.pre_read_failures.add(spec.task_id)
        return _result(spec, cast(str, read_category), cast(str, read_reason)), None
    context.raw_records[spec.task_id] = raw
    try:
        readiness_evidence.validate_evidence_record(raw)
        readiness_evidence.assert_finding_matches_record(root / spec.finding_path, raw)
        outcome = _outcome_value(raw, spec.task_id)
        result = _result(spec, outcome, _record_reason(raw, spec.task_id, outcome))
        if outcome == "pass":
            context.records[spec.task_id] = raw
        return result, raw
    except readiness_evidence.EvidenceError as exc:
        context.errors[spec.task_id] = exc
        return _failed_result(spec, exc, raw), raw


def _validate_p102(root: Path, context: ValidationContext) -> tuple[TaskResult, dict[str, Any] | None]:
    spec = _spec("P1-02")
    raw, read_reason, read_category = _read_json_record(root / spec.evidence_path)
    if raw is None:
        context.errors[spec.task_id] = target_publication.TargetPipelineError(
            cast(str, read_reason)
        )
        context.pre_read_failures.add(spec.task_id)
        return _result(spec, cast(str, read_category), cast(str, read_reason)), None
    p101_error = context.errors.get("P1-01")
    if isinstance(p101_error, readiness_evidence.EvidenceError) or "P1-01" in context.pre_read_failures:
        error = target_publication.TargetPipelineError(
            f"P1-01 evidence or finding could not be validated: {p101_error}"
        )
        context.errors[spec.task_id] = error
        return _dependency_failed_result(spec, error, raw), raw
    try:
        target_publication.validate_published_state(root)
    except target_publication.TargetPipelineError as exc:
        context.errors[spec.task_id] = exc
        return _failed_result(spec, exc, raw, read_category, read_reason), raw
    outcome = _outcome_value(raw, spec.task_id)
    result = _result(spec, outcome, _record_reason(raw, spec.task_id, outcome))
    if outcome == "pass":
        context.records[spec.task_id] = raw
    return result, raw


def _validate_p103(root: Path, context: ValidationContext) -> tuple[TaskResult, dict[str, Any] | None]:
    spec = _spec("P1-03")
    raw, read_reason, read_category = _read_json_record(root / spec.evidence_path)
    if raw is None:
        context.raw_records[spec.task_id] = {}
        context.errors[spec.task_id] = model_screening.ScreeningError(cast(str, read_reason))
        context.pre_read_failures.add(spec.task_id)
        return _result(spec, cast(str, read_category), cast(str, read_reason)), None
    p102_error = context.errors.get("P1-02")
    if isinstance(p102_error, target_publication.TargetPipelineError) or "P1-02" in context.pre_read_failures:
        error = model_screening.ScreeningError(
            f"P1-02 evidence or finding could not be validated: {p102_error}"
        )
        context.errors[spec.task_id] = error
        return _dependency_failed_result(spec, error, raw), raw
    try:
        validated = model_screening.validate_published_state(root)
    except model_screening.ScreeningError as exc:
        context.errors[spec.task_id] = exc
        return _failed_result(spec, exc, raw, read_category, read_reason), raw
    record = validated if isinstance(validated, dict) else raw
    context.records[spec.task_id] = record
    outcome = _outcome_value(record, spec.task_id)
    return _result(spec, outcome, _record_reason(record, spec.task_id, outcome)), record


def _validated_p104(
    root: Path,
    context: ValidationContext,
) -> tuple[dict[str, Any] | None, BaseException | None, dict[str, Any] | None, str | None, str | None]:
    """Validate P1-04 without its roadmap-coupled published-state wrapper."""

    if "P1-04" in context.records:
        return context.records["P1-04"], None, context.raw_records.get("P1-04"), None, None
    spec = _spec("P1-04")
    raw, read_reason, read_category = _read_json_record(root / spec.evidence_path)
    context.raw_records[spec.task_id] = raw or {}
    if raw is None:
        context.pre_read_failures.add(spec.task_id)
        return None, None, None, read_category, read_reason
    if "P1-04" in context.pre_read_failures:
        upstream = context.errors.get("P1-04")
        error = shortlist_approval.ApprovalInvalidError(
            f"P1-04 evidence or finding could not be validated: {upstream}"
        )
        context.errors[spec.task_id] = error
        return None, error, raw, "malformed", str(error)
    if "P1-03" in context.pre_read_failures:
        upstream = context.errors.get("P1-03")
        error = shortlist_approval.ApprovalInvalidError(
            f"P1-03 evidence or finding could not be validated: {upstream}"
        )
        context.errors[spec.task_id] = error
        return None, error, raw, None, None
    try:
        screening_record = context.records.get("P1-03")
        if screening_record is None:
            if "P1-03" in context.errors:
                raise context.errors["P1-03"]
            screening_record = model_screening.validate_published_state(root)
            if not isinstance(screening_record, dict):
                raise shortlist_approval.ApprovalInvalidError("P1-03 validator returned no evidence object")
            context.records["P1-03"] = screening_record
        screening_path = root / shortlist_approval.SCREENING_RELATIVE_PATH
        validated = shortlist_approval.validate_approval_record(
            raw,
            screening_record,
            screening_sha256=shortlist_approval.sha256_file(screening_path),
        )
        finding = root / spec.finding_path
        if not finding.is_file() or finding.read_text(encoding="utf-8") != shortlist_approval.render_markdown(validated):
            raise shortlist_approval.ApprovalInvalidError("P1-04 Markdown does not match canonical approval evidence")
        context.records[spec.task_id] = validated
        return validated, None, raw, None, None
    except (shortlist_approval.SelectionError, model_screening.ScreeningError) as exc:
        context.errors[spec.task_id] = exc
        return None, exc, raw, read_category, read_reason


def _validate_p104(root: Path, context: ValidationContext) -> tuple[TaskResult, dict[str, Any] | None]:
    spec = _spec("P1-04")
    validated, error, raw, read_category, read_reason = _validated_p104(root, context)
    if error is not None:
        return _failed_result(spec, error, raw, read_category, read_reason), raw
    if raw is None and validated is None:
        return _result(spec, cast(str, read_category), cast(str, read_reason)), None
    record = validated or raw
    if record is None:
        return _result(spec, "failed", "P1-04 validator returned no evidence object"), None
    outcome = _outcome_value(record, spec.task_id)
    if outcome != "pass":
        context.records.pop(spec.task_id, None)
    return _result(spec, outcome, _record_reason(record, spec.task_id, outcome)), record


def _validate_p105(root: Path, context: ValidationContext) -> tuple[TaskResult, dict[str, Any] | None]:
    spec = _spec("P1-05")
    raw, read_reason, read_category = _read_json_record(root / spec.evidence_path)
    if raw is None:
        context.pre_read_failures.add(spec.task_id)
        return _result(spec, cast(str, read_category), cast(str, read_reason)), None
    context.raw_records[spec.task_id] = raw
    try:
        validated = runtime_compatibility.validate_record(raw)
        approval, approval_error, _, _, approval_reason = _validated_p104(root, context)
        if approval_error is not None:
            raise runtime_compatibility.RuntimeEvidenceError(
                f"P1-04 evidence could not be validated: {approval_error}"
            ) from approval_error
        if approval is None:
            raise runtime_compatibility.RuntimeEvidenceError(
                approval_reason or "P1-04 evidence could not be validated"
            )
        if validated.get("approval_decision_id") != approval.get("decision_id"):
            raise runtime_compatibility.RuntimeEvidenceError("P1-05 evidence is stale against the P1-04 decision")
        approval_path = root / shortlist_approval.EVIDENCE_RELATIVE_PATH
        if validated.get("approval_evidence_sha256") != shortlist_approval.sha256_file(approval_path):
            raise runtime_compatibility.RuntimeEvidenceError("P1-05 evidence is stale against P1-04 bytes")
        finding = root / spec.finding_path
        if not finding.is_file() or finding.read_text(encoding="utf-8") != runtime_compatibility.render_markdown(validated):
            raise runtime_compatibility.RuntimeEvidenceError("P1-05 Markdown differs from canonical JSON")
        if not runtime_compatibility.roadmap_ready(validated):
            raise runtime_compatibility.RuntimeEvidenceError(
                "P1-05 evidence is not roadmap-ready according to the canonical predicate"
            )
        context.records[spec.task_id] = validated
        outcome = _outcome_value(validated, spec.task_id)
        return _result(spec, outcome, _record_reason(validated, spec.task_id, outcome)), validated
    except runtime_compatibility.RuntimeCompatibilityError as exc:
        context.errors[spec.task_id] = exc
        return _failed_result(spec, exc, raw, read_category, read_reason), raw


def _validate_p106(root: Path, context: ValidationContext) -> tuple[TaskResult, dict[str, Any] | None]:
    spec = _spec("P1-06")
    raw, read_reason, read_category = _read_json_record(root / spec.evidence_path)
    if raw is None:
        context.raw_records[spec.task_id] = {}
        context.errors[spec.task_id] = backtest_publication.RollingOriginError(cast(str, read_reason))
        context.pre_read_failures.add(spec.task_id)
        return _result(spec, cast(str, read_category), cast(str, read_reason)), None
    try:
        validated = backtest_publication.validate_rolling_origin_publication(root)
    except backtest_publication.RollingOriginError as exc:
        context.errors[spec.task_id] = exc
        return _failed_result(spec, exc, raw, read_category, read_reason), raw
    record = validated if isinstance(validated, dict) else raw
    context.records[spec.task_id] = record
    outcome = _outcome_value(record, spec.task_id)
    protocol = record.get("publication_protocol")
    if outcome == "pass" and (not isinstance(protocol, Mapping) or protocol.get("marker_state") != "pass_final"):
        outcome = "stale"
    return _result(spec, outcome, _record_reason(record, spec.task_id, outcome)), record


def _validate_p107(root: Path, context: ValidationContext) -> tuple[TaskResult, dict[str, Any] | None]:
    spec = _spec("P1-07")
    raw, read_reason, read_category = _read_json_record(root / spec.evidence_path)
    if raw is None:
        context.errors[spec.task_id] = evaluation_publication.EvaluationError(cast(str, read_reason))
        context.pre_read_failures.add(spec.task_id)
        return _result(spec, cast(str, read_category), cast(str, read_reason)), None
    if "P1-06" in context.pre_read_failures:
        error = evaluation_publication.PublicationValidationError(
            f"P1-06 evidence could not be validated: {context.errors['P1-06']}"
        )
        context.errors[spec.task_id] = error
        return _dependency_failed_result(spec, error, raw), raw
    try:
        validated = evaluation_publication.validate_evaluation_publication(root)
    except evaluation_publication.EvaluationError as exc:
        context.errors[spec.task_id] = exc
        return _failed_result(spec, exc, raw, read_category, read_reason), raw
    record = validated if isinstance(validated, dict) else raw
    context.records[spec.task_id] = record
    outcome = _outcome_value(record, spec.task_id)
    return _result(spec, outcome, _record_reason(record, spec.task_id, outcome)), record


def _validate_p108(root: Path, context: ValidationContext) -> tuple[TaskResult, dict[str, Any] | None]:
    spec = _spec("P1-08")
    raw, read_reason, read_category = _read_json_record(root / spec.evidence_path)
    if raw is None:
        context.errors[spec.task_id] = natural_language_publication.NaturalLanguageError(cast(str, read_reason))
        context.pre_read_failures.add(spec.task_id)
        return _result(spec, cast(str, read_category), cast(str, read_reason)), None
    if context.pre_read_failures.intersection({"P1-06", "P1-07"}):
        upstream = ", ".join(sorted(context.pre_read_failures.intersection({"P1-06", "P1-07"})))
        error = natural_language_publication.DependencyGateError(
            f"upstream evidence could not be read: {upstream}"
        )
        context.errors[spec.task_id] = error
        return _dependency_failed_result(spec, error, raw), raw
    try:
        validated = natural_language_publication.validate_publication(root)
    except natural_language_publication.NaturalLanguageError as exc:
        context.errors[spec.task_id] = exc
        return _failed_result(spec, exc, raw, read_category, read_reason), raw
    record = validated if isinstance(validated, dict) else raw
    context.records[spec.task_id] = record
    outcome = _outcome_value(record, spec.task_id)
    if outcome == "pass":
        checks = record.get("checks")
        if not isinstance(checks, Mapping) or checks.get("roadmap_eligible") is not True:
            outcome = "failed"
    return _result(spec, outcome, _record_reason(record, spec.task_id, outcome)), record


def validate_predecessors(repo_root: Path) -> tuple[TaskResult, ...]:
    """Run every canonical predecessor validator and collect all gate outcomes."""

    root = _root(repo_root)
    context = ValidationContext()
    validators = (
        _validate_p101,
        _validate_p102,
        _validate_p103,
        _validate_p104,
        _validate_p105,
        _validate_p106,
        _validate_p107,
        _validate_p108,
    )
    results: list[TaskResult] = []
    for task_id, validator in zip(PREDECESSOR_TASK_IDS, validators, strict=True):
        spec = _spec(task_id)
        malformed_reason = _finding_encoding_failure(root / spec.finding_path)
        if malformed_reason is not None:
            error = EvidenceRollupError(malformed_reason)
            context.errors[task_id] = error
            context.pre_read_failures.add(task_id)
            result = _result(
                spec,
                "malformed",
                malformed_reason,
            )
        else:
            result, _ = validator(root, context)
        results.append(result)
    return tuple(results)


def _observation_kind(field_name: str) -> str | None:
    normalized = field_name.lower().replace("-", "_")
    if "limit" in normalized:
        return "limitations"
    if "unknown" in normalized:
        return "unknowns"
    if "diagnos" in normalized or "non_pass" in normalized:
        return "diagnostics"
    if "error" in normalized:
        return "errors"
    return None


def _walk_observation_fields(value: object, path: str = "") -> list[tuple[str, str, Any]]:
    found: list[tuple[str, str, Any]] = []
    if isinstance(value, Mapping):
        for key in sorted(value):
            child_path = f"{path}.{key}" if path else str(key)
            child = value[key]
            kind = _observation_kind(str(key))
            if kind is not None and child not in (None, [], {}, ""):
                found.append((kind, child_path, copy.deepcopy(child)))
            found.extend(_walk_observation_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_observation_fields(child, f"{path}[{index}]"))
    return found


def project_task_evidence(
    task_id: str,
    source_path: str,
    record: Mapping[str, Any] | None,
) -> tuple[Observation, ...]:
    """Project required traceability observations without copying predecessor schemas."""

    if record is None:
        return ()
    observations: list[Observation] = []
    seen: set[str] = set()
    for kind, field_name, value in _walk_observation_fields(record):
        identity = json.dumps([kind, field_name, value], sort_keys=True, ensure_ascii=False)
        if identity in seen:
            continue
        seen.add(identity)
        observations.append(
            {
                "task_id": task_id,
                "source_path": source_path,
                "kind": kind,
                "field": field_name,
                "value": value,
            }
        )

    candidates = record.get("candidate_records")
    if isinstance(candidates, list):
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, Mapping):
                continue
            outcome = candidate.get("classification", candidate.get("outcome"))
            if outcome not in {"failed", "fail", "blocked", "unsupported", "unknown"}:
                continue
            value = {
                "candidate_id": candidate.get("variant_id", candidate.get("candidate_id")),
                "outcome": outcome,
                "errors": copy.deepcopy(candidate.get("errors", [])),
            }
            field_name = f"candidate_records[{index}]"
            identity = json.dumps(["candidate_non_pass", field_name, value], sort_keys=True, ensure_ascii=False)
            if identity in seen:
                continue
            seen.add(identity)
            observations.append(
                {
                    "task_id": task_id,
                    "source_path": source_path,
                    "kind": "candidate_non_pass",
                    "field": field_name,
                    "value": value,
                }
            )
    return tuple(observations)


def _roadmap_line_indices(text: str) -> tuple[dict[str, int], dict[str, int]]:
    lines = text.splitlines(keepends=True)
    task_indices: dict[str, int] = {}
    for index, line in enumerate(lines):
        for task_id in OWNED_TASK_IDS:
            pattern = re.compile(rf"^- \[[ x-]\] \*\*{re.escape(task_id)}\b")
            if pattern.match(line.rstrip("\r\n")):
                if task_id in task_indices:
                    raise RoadmapTransformError(f"roadmap must contain exactly one {task_id} line")
                task_indices[task_id] = index
    missing = [task_id for task_id in OWNED_TASK_IDS if task_id not in task_indices]
    if missing:
        raise RoadmapTransformError(f"roadmap is missing owned task lines: {', '.join(missing)}")

    current_matches = list(_CURRENT_STATUS_PATTERN.finditer(text))
    phase_matches = list(_PHASE_ONE_HEADING_PATTERN.finditer(text))
    if len(current_matches) != 1:
        raise RoadmapTransformError("roadmap must contain exactly one current-status heading")
    if len(phase_matches) != 1:
        raise RoadmapTransformError("roadmap must contain exactly one Phase 1 heading")
    line_starts: list[int] = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line)
    heading_indices = {
        "current_status": max(
            index for index, start in enumerate(line_starts) if start == current_matches[0].start()
        ),
        "phase1": max(index for index, start in enumerate(line_starts) if start == phase_matches[0].start()),
    }
    return task_indices, heading_indices


def _replace_task_marker(text: str, task_id: str, marker: str) -> str:
    pattern = re.compile(rf"(?m)^(- )\[[ x-]\]( \*\*{re.escape(task_id)}\b.*)$")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise RoadmapTransformError(f"roadmap must contain exactly one {task_id} line")
    return pattern.sub(rf"\1[{marker}]\2", text, count=1)


def _non_owned_lines(text: str) -> list[str]:
    task_indices, heading_indices = _roadmap_line_indices(text)
    excluded = set(task_indices.values()) | set(heading_indices.values())
    return [line for index, line in enumerate(text.splitlines(keepends=True)) if index not in excluded]


def transform_roadmap(
    roadmap_text: str,
    task_results: Sequence[Mapping[str, Any]],
    phase_outcome: str,
) -> str:
    """Apply only owned checkbox tokens and, for completion, two exact headings."""

    if phase_outcome not in {"complete", "incomplete"}:
        raise RoadmapTransformError(f"unsupported phase outcome: {phase_outcome}")
    result_by_task = {str(result.get("task_id")): result for result in task_results}
    if set(result_by_task) != set(PREDECESSOR_TASK_IDS):
        raise RoadmapTransformError("roadmap transform requires exactly the eight predecessor results")
    updated = roadmap_text
    for task_id in PREDECESSOR_TASK_IDS:
        marker = "x" if result_by_task[task_id].get("outcome") == "pass" else " "
        updated = _replace_task_marker(updated, task_id, marker)
    updated = _replace_task_marker(updated, TASK_ID, "x" if phase_outcome == "complete" else " ")

    if phase_outcome == "complete":
        current_pattern = _CURRENT_STATUS_PATTERN
        phase_pattern = _PHASE_ONE_HEADING_PATTERN
        if len(list(current_pattern.finditer(updated))) != 1 or len(list(phase_pattern.finditer(updated))) != 1:
            raise RoadmapTransformError("roadmap headings became ambiguous during transformation")
        updated = current_pattern.sub(
            "## Current Status: Phase 0 Complete; Phase 1 Complete", updated, count=1
        )
        updated = phase_pattern.sub(
            "## Phase 1: Monthly Arabica History-Only Forecasting (Complete)", updated, count=1
        )
    original_tasks, original_headings = _roadmap_line_indices(roadmap_text)
    updated_tasks, updated_headings = _roadmap_line_indices(updated)
    if original_tasks != updated_tasks or original_headings != updated_headings:
        raise RoadmapTransformError("roadmap transformation changed line ownership or structure")
    original_lines = roadmap_text.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)
    if len(original_lines) != len(updated_lines):
        raise RoadmapTransformError("roadmap transformation changed the line count")
    excluded = set(original_tasks.values()) | set(original_headings.values())
    for index, (before, after) in enumerate(zip(original_lines, updated_lines)):
        if index not in excluded and before != after:
            raise RoadmapTransformError(f"roadmap changed an unowned line at index {index}")
    if phase_outcome == "incomplete":
        for key, index in original_headings.items():
            if original_lines[index] != updated_lines[index]:
                raise RoadmapTransformError(f"incomplete exit changed the {key} heading")
    return updated


def _roadmap_expectations(text: str, phase_outcome: str) -> dict[str, Any]:
    task_indices, heading_indices = _roadmap_line_indices(text)
    lines = text.splitlines(keepends=True)
    markers: dict[str, str] = {}
    for task_id, index in task_indices.items():
        marker = re.match(r"^- \[([ x-])\]", lines[index])
        if marker is None or marker.group(1) not in {"x", " "}:
            raise RoadmapTransformError(f"roadmap marker is invalid for {task_id}")
        markers[task_id] = marker.group(1)
    return {
        "phase_outcome": phase_outcome,
        "owned_task_markers": markers,
        "owned_task_lines": {
            task_id: lines[index].rstrip("\r\n") for task_id, index in task_indices.items()
        },
        "current_status_heading": lines[heading_indices["current_status"]].rstrip("\r\n"),
        "phase1_heading": lines[heading_indices["phase1"]].rstrip("\r\n"),
        "owned_line_numbers": task_indices,
        "heading_line_numbers": heading_indices,
        "non_owned_lines": _non_owned_lines(text),
    }


def validate_roadmap_text(roadmap_text: str, record: Mapping[str, Any]) -> None:
    """Validate roadmap state and direct non-owned-line agreement with an exit record."""

    expectations = record.get("roadmap_expectations")
    if not isinstance(expectations, Mapping):
        raise RoadmapTransformError("exit record roadmap expectations are missing")
    task_indices, heading_indices = _roadmap_line_indices(roadmap_text)
    lines = roadmap_text.splitlines(keepends=True)
    expected_markers = expectations.get("owned_task_markers")
    if not isinstance(expected_markers, Mapping):
        raise RoadmapTransformError("exit record owned roadmap markers are missing")
    actual_markers: dict[str, str] = {}
    for task_id, index in task_indices.items():
        match = re.match(r"^- \[([ x-])\]", lines[index])
        if match is None or match.group(1) not in {"x", " "}:
            raise RoadmapTransformError(f"roadmap marker is invalid for {task_id}")
        actual_markers[task_id] = match.group(1)
    if dict(expected_markers) != actual_markers:
        raise RoadmapTransformError("roadmap task markers diverge from the published exit record")
    expected_task_lines = expectations.get("owned_task_lines")
    actual_task_lines = {
        task_id: lines[index].rstrip("\r\n") for task_id, index in task_indices.items()
    }
    if not isinstance(expected_task_lines, Mapping) or dict(expected_task_lines) != actual_task_lines:
        raise RoadmapTransformError("roadmap owned task lines diverge from the published exit record")
    if lines[heading_indices["current_status"]].rstrip("\r\n") != expectations.get("current_status_heading"):
        raise RoadmapTransformError("roadmap current-status heading diverges from the published exit record")
    if lines[heading_indices["phase1"]].rstrip("\r\n") != expectations.get("phase1_heading"):
        raise RoadmapTransformError("roadmap Phase 1 heading diverges from the published exit record")
    expected_task_numbers = expectations.get("owned_line_numbers")
    expected_heading_numbers = expectations.get("heading_line_numbers")
    if dict(expected_task_numbers or {}) != task_indices or dict(expected_heading_numbers or {}) != heading_indices:
        raise RoadmapTransformError("roadmap line ownership diverges from the published exit record")
    if expectations.get("non_owned_lines") != _non_owned_lines(roadmap_text):
        raise RoadmapTransformError("roadmap non-owned lines diverge from the published exit record")
    if record.get("phase_outcome") == "complete":
        if expectations.get("current_status_heading") != "## Current Status: Phase 0 Complete; Phase 1 Complete":
            raise RoadmapTransformError("complete exit has the wrong current-status heading")
        if expectations.get("phase1_heading") != "## Phase 1: Monthly Arabica History-Only Forecasting (Complete)":
            raise RoadmapTransformError("complete exit has the wrong Phase 1 heading")


def _incomplete_gates(task_results: Sequence[TaskResult]) -> list[IncompleteGate]:
    return [
        {
            "task_id": result["task_id"],
            "source_path": result["evidence_path"],
            "outcome": result["outcome"],
            "reason": result["reason"],
        }
        for result in task_results
        if result["outcome"] != "pass"
    ]


def _validate_timestamp(value: object) -> None:
    if not isinstance(value, str) or _TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise EvidenceRollupError("generated_at_utc must be a UTC second timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise EvidenceRollupError("generated_at_utc is not a real timestamp") from exc


def validate_exit_record(record: Mapping[str, Any]) -> None:
    """Validate the closed, task-level P1-09 record without invoking predecessors."""

    required = {
        "schema_version",
        "task_id",
        "generated_at_utc",
        "phase_outcome",
        "task_results",
        "incomplete_gates",
        "preserved_observations",
        "roadmap_expectations",
        "artifact_paths",
    }
    if set(record) != required:
        raise EvidenceRollupError("exit record fields differ from the closed schema")
    if record["schema_version"] != SCHEMA_VERSION or record["task_id"] != TASK_ID:
        raise EvidenceRollupError("exit record schema version or task ID is invalid")
    _validate_timestamp(record["generated_at_utc"])
    phase_outcome = record["phase_outcome"]
    if phase_outcome not in {"complete", "incomplete"}:
        raise EvidenceRollupError("phase_outcome must be complete or incomplete")

    task_results = record["task_results"]
    if not isinstance(task_results, list) or [item.get("task_id") for item in task_results if isinstance(item, Mapping)] != list(PREDECESSOR_TASK_IDS):
        raise EvidenceRollupError("task_results must contain P1-01 through P1-08 exactly once in order")
    for item in task_results:
        if not isinstance(item, Mapping) or set(item) != {
            "task_id", "evidence_path", "finding_path", "outcome", "reason"
        }:
            raise EvidenceRollupError("task result fields differ from the closed schema")
        if item["outcome"] != "pass" and item["outcome"] not in NON_PASS_OUTCOMES:
            raise EvidenceRollupError(f"unsupported predecessor outcome: {item['outcome']}")
        if not all(isinstance(item[key], str) and item[key] for key in ("task_id", "evidence_path", "finding_path", "reason")):
            raise EvidenceRollupError("task result paths and reason must be non-empty strings")
        expected = _spec(cast(str, item["task_id"]))
        if item["evidence_path"] != expected.evidence_path.as_posix() or item["finding_path"] != expected.finding_path.as_posix():
            raise EvidenceRollupError(f"canonical paths are invalid for {item['task_id']}")

    expected_gates = _incomplete_gates(cast(list[TaskResult], task_results))
    if record["incomplete_gates"] != expected_gates:
        raise EvidenceRollupError("incomplete_gates is not the exact non-pass task subset")
    if phase_outcome == "complete" and expected_gates:
        raise EvidenceRollupError("complete exit contains incomplete predecessor gates")
    if phase_outcome == "incomplete" and not expected_gates:
        raise EvidenceRollupError("incomplete exit has no incomplete predecessor gates")

    observations = record["preserved_observations"]
    if not isinstance(observations, list):
        raise EvidenceRollupError("preserved_observations must be a list")
    for observation in observations:
        if not isinstance(observation, Mapping) or set(observation) != {
            "task_id", "source_path", "kind", "field", "value"
        }:
            raise EvidenceRollupError("observation fields differ from the closed schema")
        if observation["task_id"] not in PREDECESSOR_TASK_IDS or observation["kind"] not in OBSERVATION_KINDS:
            raise EvidenceRollupError("observation task or kind is invalid")
        if not all(isinstance(observation[key], str) and observation[key] for key in ("source_path", "field")):
            raise EvidenceRollupError("observation source and field must be non-empty strings")

    expectations = record["roadmap_expectations"]
    if not isinstance(expectations, Mapping) or set(expectations) != {
        "phase_outcome", "owned_task_markers", "owned_task_lines", "current_status_heading", "phase1_heading",
        "owned_line_numbers", "heading_line_numbers", "non_owned_lines",
    }:
        raise EvidenceRollupError("roadmap expectations differ from the closed schema")
    if expectations["phase_outcome"] != phase_outcome:
        raise EvidenceRollupError("roadmap expectation outcome differs from exit outcome")
    markers = expectations["owned_task_markers"]
    if not isinstance(markers, Mapping) or set(markers) != set(OWNED_TASK_IDS):
        raise EvidenceRollupError("roadmap expectations must own P1-01 through P1-09")
    expected_markers = {
        task_id: "x"
        if (phase_outcome == "complete" or (task_id != TASK_ID and next(item for item in task_results if item["task_id"] == task_id)["outcome"] == "pass"))
        else " "
        for task_id in OWNED_TASK_IDS
    }
    if dict(markers) != expected_markers:
        raise EvidenceRollupError("roadmap markers do not match validated predecessor outcomes")
    owned_task_lines = expectations["owned_task_lines"]
    if (
        not isinstance(owned_task_lines, Mapping)
        or set(owned_task_lines) != set(OWNED_TASK_IDS)
        or any(not isinstance(line, str) or not line for line in owned_task_lines.values())
    ):
        raise EvidenceRollupError("roadmap owned task lines must contain P1-01 through P1-09")
    if not isinstance(expectations["current_status_heading"], str) or not isinstance(expectations["phase1_heading"], str):
        raise EvidenceRollupError("roadmap headings must be strings")
    if not isinstance(expectations["owned_line_numbers"], Mapping) or not isinstance(expectations["heading_line_numbers"], Mapping):
        raise EvidenceRollupError("roadmap line numbers must be objects")
    if not isinstance(expectations["non_owned_lines"], list) or not all(isinstance(line, str) for line in expectations["non_owned_lines"]):
        raise EvidenceRollupError("roadmap non-owned lines must be a string list")

    artifacts = record["artifact_paths"]
    expected_artifacts = {
        "finding": FINDING_RELATIVE_PATH.as_posix(),
        "evidence": EVIDENCE_RELATIVE_PATH.as_posix(),
        "roadmap": ROADMAP_RELATIVE_PATH.as_posix(),
    }
    if artifacts != expected_artifacts:
        raise EvidenceRollupError("exit artifact paths are not canonical")


def render_exit_json(record: Mapping[str, Any]) -> str:
    validate_exit_record(record)
    return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _markdown_value(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _markdown_code(value: object) -> str:
    """Render dynamic values in a code span without allowing Markdown injection."""

    raw = value if isinstance(value, str) else _markdown_value(value)
    raw = raw.replace("\r\n", "\\n").replace("\r", "\\r").replace("\n", "\\n")
    raw = raw.replace("|", "\\|")
    longest_ticks = max((len(match.group(0)) for match in re.finditer(r"`+", raw)), default=0)
    fence = "`" * (longest_ticks + 1)
    if raw.startswith(" ") or raw.endswith(" "):
        raw = f" {raw} "
    return f"{fence}{raw}{fence}"


def render_exit_markdown(record: Mapping[str, Any]) -> str:
    """Render the deterministic human-readable companion for a validated exit record."""

    validate_exit_record(record)
    lines = [
        "# Phase 1 Evidence Rollup and Exit",
        "",
        f"- Task: {_markdown_code(record['task_id'])}",
        f"- Generated at: {_markdown_code(record['generated_at_utc'])}",
        f"- Phase outcome: {_markdown_code(record['phase_outcome'])}",
        "",
        "## Predecessor task results",
        "",
        "| Task | Outcome | Canonical evidence | Finding | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in record["task_results"]:
        lines.append(
            f"| {_markdown_code(result['task_id'])} | {_markdown_code(result['outcome'])} | "
            f"{_markdown_code(result['evidence_path'])} | {_markdown_code(result['finding_path'])} | "
            f"{_markdown_code(result['reason'])} |"
        )
    lines.extend(["", "## Incomplete gates", ""])
    gates = record["incomplete_gates"]
    if gates:
        for gate in gates:
            lines.append(
                f"- {_markdown_code(gate['task_id'])} — {_markdown_code(gate['outcome'])} — "
                f"{_markdown_code(gate['source_path'])} — {_markdown_code(gate['reason'])}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Preserved observations", ""])
    observations = record["preserved_observations"]
    if observations:
        for observation in observations:
            lines.extend(
                [
                    f"- {_markdown_code(observation['task_id'])} / {_markdown_code(observation['kind'])} / "
                    f"{_markdown_code(observation['field'])}",
                    f"  - Source: {_markdown_code(observation['source_path'])}",
                    f"  - Value: {_markdown_code(observation['value'])}",
                ]
            )
    else:
        lines.append("- None")
    expectations = record["roadmap_expectations"]
    lines.extend(
        [
            "",
            "## Roadmap reconciliation",
            "",
            f"- Current-status heading: {_markdown_code(expectations['current_status_heading'])}",
            f"- Phase 1 heading: {_markdown_code(expectations['phase1_heading'])}",
            f"- Directly compared non-owned lines: {_markdown_code(len(expectations['non_owned_lines']))}",
        ]
    )
    for task_id in OWNED_TASK_IDS:
        marker = f"[{expectations['owned_task_markers'][task_id]}]"
        lines.append(
            f"- {_markdown_code(task_id)} checkbox: {_markdown_code(marker)}"
        )
    lines.extend(
        [
            "",
            "## Published artifacts",
            "",
            f"- Markdown: {_markdown_code(record['artifact_paths']['finding'])}",
            f"- JSON: {_markdown_code(record['artifact_paths']['evidence'])}",
            f"- Roadmap: {_markdown_code(record['artifact_paths']['roadmap'])}",
            "",
        ]
    )
    return "\n".join(lines)


def validate_rendered_outputs(record: Mapping[str, Any], markdown: str, evidence_json: str) -> None:
    validate_exit_record(record)
    if evidence_json != render_exit_json(record):
        raise EvidenceRollupError("rendered exit JSON is not canonical")
    if markdown != render_exit_markdown(record):
        raise EvidenceRollupError("rendered exit Markdown is not canonical")


def build_exit_record(
    repo_root: Path,
    *,
    generated_at_utc: str | None = None,
) -> tuple[ExitRecord, str]:
    """Validate predecessors and render the exit record and roadmap in memory."""

    root = _root(repo_root)
    task_results = list(validate_predecessors(root))
    phase_outcome = "complete" if not _incomplete_gates(task_results) else "incomplete"
    roadmap_path = root / ROADMAP_RELATIVE_PATH
    try:
        original_roadmap = roadmap_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RoadmapTransformError(f"roadmap could not be read: {exc}") from exc
    transformed_roadmap = transform_roadmap(original_roadmap, task_results, phase_outcome)
    observations: list[Observation] = []
    for result in task_results:
        raw_path = root / result["evidence_path"]
        raw, _, _ = _read_json_record(raw_path)
        observations.extend(project_task_evidence(result["task_id"], result["evidence_path"], raw))
    record: ExitRecord = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "generated_at_utc": generated_at_utc or _utc_timestamp(),
        "phase_outcome": phase_outcome,
        "task_results": cast(list[TaskResult], task_results),
        "incomplete_gates": _incomplete_gates(task_results),
        "preserved_observations": observations,
        "roadmap_expectations": _roadmap_expectations(transformed_roadmap, phase_outcome),
        "artifact_paths": {
            "finding": FINDING_RELATIVE_PATH.as_posix(),
            "evidence": EVIDENCE_RELATIVE_PATH.as_posix(),
            "roadmap": ROADMAP_RELATIVE_PATH.as_posix(),
        },
    }
    evidence_json = render_exit_json(record)
    markdown = render_exit_markdown(record)
    validate_rendered_outputs(record, markdown, evidence_json)
    validate_roadmap_text(transformed_roadmap, record)
    return record, transformed_roadmap


def _assert_safe_destination(root: Path, destination: Path) -> None:
    """Reject output paths that resolve outside the selected repository."""

    try:
        relative = destination.relative_to(root)
    except ValueError as exc:
        raise PublicationError(f"publication destination is outside repository: {destination}") from exc
    resolved = destination.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PublicationError(f"publication destination resolves outside repository: {destination}") from exc
    cursor = root
    for part in relative.parts[:-1]:
        cursor /= part
        if cursor.is_symlink():
            raise PublicationError(f"publication destination has a symlinked directory: {cursor}")
    if destination.is_symlink():
        raise PublicationError(f"publication destination is a symlink: {destination}")


def _destination_mode(destination: Path) -> int:
    try:
        return stat.S_IMODE(destination.stat().st_mode)
    except FileNotFoundError:
        return 0o644
    except OSError as exc:
        raise PublicationError(f"publication destination mode is unavailable: {exc}") from exc


def _stage_bytes(destination: Path, payload: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    mode = _destination_mode(destination)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
        os.chmod(staged, mode)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def publish(
    repo_root: Path,
    *,
    replace_file: ReplaceFile | None = None,
    generated_at_utc: str | None = None,
) -> ExitRecord:
    """Stage and replace the three destinations after all rendered validation succeeds."""

    root = _root(repo_root)
    output_destinations = tuple(
        root / relative_path
        for relative_path in (FINDING_RELATIVE_PATH, EVIDENCE_RELATIVE_PATH, ROADMAP_RELATIVE_PATH)
    )
    for destination in output_destinations:
        _assert_safe_destination(root, destination)
    record, transformed_roadmap = build_exit_record(root, generated_at_utc=generated_at_utc)
    markdown = render_exit_markdown(record)
    evidence_json = render_exit_json(record)
    validate_rendered_outputs(record, markdown, evidence_json)
    validate_roadmap_text(transformed_roadmap, record)
    destinations = (
        (output_destinations[0], markdown.encode("utf-8")),
        (output_destinations[1], evidence_json.encode("utf-8")),
        (output_destinations[2], transformed_roadmap.encode("utf-8")),
    )
    replacer = replace_file or os.replace
    staged: list[tuple[Path, Path]] = []
    try:
        for destination, payload in destinations:
            _assert_safe_destination(root, destination)
            staged.append((_stage_bytes(destination, payload), destination))
        for temporary, destination in staged:
            try:
                _assert_safe_destination(root, destination)
                replacer(temporary, destination)
            except Exception as exc:
                raise PublicationError(
                    f"publication replacement failed for {destination.as_posix()}: {type(exc).__name__}: {exc}"
                ) from exc
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    try:
        validate_publication(root)
    except Exception as exc:
        if isinstance(exc, RollupError):
            raise
        raise PublicationError(f"published exit could not be revalidated: {exc}") from exc
    return record


def validate_publication(repo_root: Path) -> ExitRecord:
    """Validate the published JSON, Markdown, and directly reconciled roadmap."""

    root = _root(repo_root)
    evidence_path = root / EVIDENCE_RELATIVE_PATH
    try:
        value = json.loads(evidence_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceRollupError("published exit evidence is missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceRollupError("published exit evidence is unreadable or malformed") from exc
    if not isinstance(value, dict):
        raise EvidenceRollupError("published exit evidence must be an object")
    record = cast(ExitRecord, value)
    validate_exit_record(record)
    current_record, _ = build_exit_record(root, generated_at_utc=record["generated_at_utc"])
    for field_name in ("phase_outcome", "task_results", "incomplete_gates", "preserved_observations"):
        if current_record[field_name] != record[field_name]:
            raise EvidenceRollupError(
                f"published exit is stale against current canonical evidence: {field_name}"
            )
    markdown_path = root / FINDING_RELATIVE_PATH
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceRollupError("published exit Markdown is unavailable") from exc
    validate_rendered_outputs(record, markdown, render_exit_json(record))
    try:
        roadmap = (root / ROADMAP_RELATIVE_PATH).read_text(encoding="utf-8")
    except OSError as exc:
        raise RoadmapTransformError("published roadmap is unavailable") from exc
    validate_roadmap_text(roadmap, record)
    return record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--publish", action="store_true")
    actions.add_argument("--validate-publication", action="store_true")
    actions.add_argument("--check-roadmap", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Thin CLI dispatch for publication and read-only consistency checks."""

    arguments = _parser().parse_args(argv)
    try:
        if arguments.publish:
            record = publish(arguments.repo_root)
            print(json.dumps({"phase_outcome": record["phase_outcome"], "task_id": TASK_ID}, sort_keys=True))
            return 0 if record["phase_outcome"] == "complete" else 1
        validate_publication(arguments.repo_root)
        return 0
    except (RollupError, OSError, ValueError) as exc:
        print(f"phase1-exit-rollup: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
