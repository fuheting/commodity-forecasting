"""Validation and atomic publication for Phase 1 readiness evidence."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    ALLOWED_CLASSIFICATIONS,
    EVIDENCE_SCHEMA_VERSION,
    EXPECTED_PERIOD_COUNT,
    EXPECTED_PERIOD_END,
    EXPECTED_PERIOD_START,
    EXPECTED_RAW_SHA256,
    PUBLICATION_POLICY,
    READER_REQUIREMENT,
    REQUIRED_PASS_CHECKS,
    TARGET_COLUMN,
    TASK_ID,
    WORKSHEET_NAME,
    reader_version_supported,
)

REQUIRED_FIELDS = (
    "schema_version",
    "task_id",
    "run_id",
    "timestamp_utc",
    "classification",
    "mode",
    "controller_mode",
    "child_mode",
    "sanitized_command",
    "repo_root",
    "stage_outcomes",
    "failed_stage",
    "child_exit_code",
    "reader_requirement",
    "resolved_openpyxl_version",
    "installed_project_version",
    "python_version",
    "working_directory_class",
    "install_mode",
    "pythonpath_state",
    "host_pythonpath_state",
    "expected_raw_sha256",
    "raw_sha256_before",
    "raw_sha256_after",
    "sheet_name",
    "target_column",
    "header_row",
    "target_column_index",
    "period_start",
    "period_end",
    "period_count",
    "publication_policy",
    "checks",
    "errors",
    "cleanup_status",
    "artifact_paths",
    "phase0_evidence",
)

SECRET_ASSIGNMENT = re.compile(
    r'''(?ix)["']?\b(api[_-]?key|secret|token|password)\b["']?\s*[:=]\s*'''
    r'''(?!["']?\[REDACTED\])["']?[^,"'\s}\]]+["']?'''
)
SECRET_CLI_ARGUMENT = re.compile(
    r"(?i)--(?:api[_-]?key|secret|token|password)(?:=|\s+)(?!\[REDACTED\])\S+"
)
SECRET_BEARER = re.compile(r"(?i)\bbearer\s+(?!\[REDACTED\])[^,\s}\]]+")
SECRET_URL_USERINFO = re.compile(
    r"(?i)\b[a-z][a-z0-9+.-]*://(?!\[REDACTED\])[^/@\s]+@"
)
SECRET_PATTERNS = (
    SECRET_ASSIGNMENT,
    SECRET_CLI_ARGUMENT,
    SECRET_BEARER,
    SECRET_URL_USERINFO,
)


class EvidenceError(ValueError):
    """Raised when readiness evidence violates its schema or completion gate."""


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def assert_no_secret_material(value: Any) -> None:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise EvidenceError("evidence contains secret-like material")


def sanitize_diagnostic(value: str) -> str:
    """Redact common credential shapes before external diagnostics enter evidence."""

    redacted = SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)} [REDACTED]", value)
    redacted = SECRET_CLI_ARGUMENT.sub("[REDACTED]", redacted)
    redacted = SECRET_BEARER.sub("[REDACTED]", redacted)
    return SECRET_URL_USERINFO.sub(
        lambda match: match.group(0).split("://", 1)[0] + "://[REDACTED]",
        redacted,
    )


def _validate_timestamp(value: object) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError("timestamp_utc must be an ISO-8601 UTC value ending in Z")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("timestamp_utc is malformed") from exc


def _validate_stage_outcomes(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise EvidenceError("stage_outcomes must be a non-empty list")
    for outcome in value:
        if not isinstance(outcome, dict):
            raise EvidenceError("stage_outcomes entries must be objects")
        if outcome.get("status") not in {"pass", "fail", "blocked", "skipped"}:
            raise EvidenceError("stage outcome has an unsupported status")
        if not str(outcome.get("stage", "")).strip():
            raise EvidenceError("stage outcome must name its stage")


def validate_evidence_record(record: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise EvidenceError(f"missing evidence fields: {', '.join(missing)}")
    if record["schema_version"] != EVIDENCE_SCHEMA_VERSION:
        raise EvidenceError("unsupported evidence schema version")
    if record["task_id"] != TASK_ID:
        raise EvidenceError("evidence task_id must be P1-01")
    if not str(record["run_id"]).strip():
        raise EvidenceError("run_id must be non-empty")
    _validate_timestamp(record["timestamp_utc"])
    if record["classification"] not in ALLOWED_CLASSIFICATIONS:
        raise EvidenceError("unsupported evidence classification")
    if not isinstance(record["repo_root"], str) or not Path(record["repo_root"]).is_absolute():
        raise EvidenceError("repo_root must be an absolute path")
    _validate_stage_outcomes(record["stage_outcomes"])
    if not isinstance(record["checks"], dict):
        raise EvidenceError("checks must be an object")
    if not isinstance(record["errors"], list):
        raise EvidenceError("errors must be a list")
    if not isinstance(record["artifact_paths"], list) or not isinstance(record["phase0_evidence"], list):
        raise EvidenceError("artifact_paths and phase0_evidence must be lists")
    if record["publication_policy"] != PUBLICATION_POLICY.as_dict():
        raise EvidenceError("publication policy does not match the Phase 1 contract")

    if record["classification"] == "pass":
        stage_statuses = {outcome["stage"]: outcome["status"] for outcome in record["stage_outcomes"]}
        required_stages = ("create_environment", "install_project", "pip_check", "probe_installed", "cleanup")
        incomplete_stages = [stage for stage in required_stages if stage_statuses.get(stage) != "pass"]
        if incomplete_stages:
            raise EvidenceError(f"pass evidence has incomplete stages: {', '.join(incomplete_stages)}")
        missing_checks = [name for name in REQUIRED_PASS_CHECKS if record["checks"].get(name) is not True]
        if missing_checks:
            raise EvidenceError(f"pass evidence has incomplete checks: {', '.join(missing_checks)}")
        if record["errors"]:
            raise EvidenceError("pass evidence cannot contain errors")
        if record["failed_stage"] is not None:
            raise EvidenceError("pass evidence cannot name a failed stage")
        if record["child_mode"] != "probe-installed" or record["child_exit_code"] != 0:
            raise EvidenceError("pass requires a successful installed child probe")
        if record["install_mode"] != "non_editable":
            raise EvidenceError("pass requires a non-editable installation")
        if record["working_directory_class"] != "outside_repository":
            raise EvidenceError("pass requires an outside-repository child working directory")
        if record["pythonpath_state"] != "absent":
            raise EvidenceError("pass requires PYTHONPATH to be absent in the child")
        if record["cleanup_status"] != "pass":
            raise EvidenceError("pass requires temporary-environment cleanup")
        if record["reader_requirement"] != READER_REQUIREMENT:
            raise EvidenceError("pass evidence has the wrong reader requirement")
        version = record["resolved_openpyxl_version"]
        if not isinstance(version, str) or not reader_version_supported(version):
            raise EvidenceError("pass requires an openpyxl version satisfying >=3.1,<4")
        if record["installed_project_version"] in {None, "", "unknown"}:
            raise EvidenceError("pass requires the installed project version")
        if record["expected_raw_sha256"] != EXPECTED_RAW_SHA256:
            raise EvidenceError("pass evidence has the wrong expected raw hash")
        if not (
            record["raw_sha256_before"]
            == record["raw_sha256_after"]
            == record["expected_raw_sha256"]
        ):
            raise EvidenceError("pass evidence does not preserve the raw workbook hash")
        if record["sheet_name"] != WORKSHEET_NAME or record["target_column"] != TARGET_COLUMN:
            raise EvidenceError("pass evidence does not match the workbook target contract")
        if (
            record["period_start"] != EXPECTED_PERIOD_START
            or record["period_end"] != EXPECTED_PERIOD_END
            or record["period_count"] != EXPECTED_PERIOD_COUNT
        ):
            raise EvidenceError("pass evidence does not match the expected monthly extent")

    assert_no_secret_material(record)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_evidence(path: Path, record: dict[str, Any]) -> None:
    validate_evidence_record(record)
    _atomic_write_text(path, json.dumps(record, indent=2, sort_keys=True) + "\n")


def render_finding(record: dict[str, Any]) -> str:
    validate_evidence_record(record)
    checks = "\n".join(f"- `{name}`: `{value}`" for name, value in sorted(record["checks"].items()))
    errors = "\n".join(f"- {error}" for error in record["errors"]) or "- None"
    return (
        "# Phase 1 Dependency Readiness\n\n"
        f"- Run ID: `{record['run_id']}`\n"
        f"- Classification: `{record['classification']}`\n"
        f"- Reader: `openpyxl {record['resolved_openpyxl_version']}` (`{record['reader_requirement']}`)\n"
        f"- Installed project: `{record['installed_project_version']}`\n"
        f"- Acceptance command: `{record['sanitized_command']}`\n"
        f"- Controller / child mode: `{record['controller_mode']}` / `{record['child_mode']}`\n"
        f"- Host / child PYTHONPATH: `{record['host_pythonpath_state']}` / `{record['pythonpath_state']}`\n"
        f"- Workbook: `{record['repo_root']}/data/raw/world_bank/pink_sheet/CMO-Historical-Data-Monthly.xlsx`\n"
        f"- Raw SHA-256 before: `{record['raw_sha256_before']}`\n"
        f"- Raw SHA-256 after: `{record['raw_sha256_after']}`\n"
        f"- Worksheet / target: `{record['sheet_name']}` / `{record['target_column']}`\n"
        f"- Monthly extent: `{record['period_start']}` through `{record['period_end']}` "
        f"(`{record['period_count']}` rows)\n\n"
        "## Stage outcomes\n\n"
        + "\n".join(
            f"- `{outcome['stage']}`: `{outcome['status']}` (exit `{outcome.get('exit_code')}`)"
            for outcome in record["stage_outcomes"]
        )
        + "\n"
        f"- Failed stage: `{record['failed_stage']}`\n"
        f"- Cleanup: `{record['cleanup_status']}`\n\n"
        "## Checks\n\n"
        f"{checks}\n\n"
        "## Publication-availability policy\n\n"
        f"- Evaluation label: `{PUBLICATION_POLICY.evaluation_label}`\n"
        f"- Availability proxy: `{PUBLICATION_POLICY.availability_proxy}`\n"
        f"- Limitation: {PUBLICATION_POLICY.limitation}\n"
        f"- Prohibited claim: {PUBLICATION_POLICY.prohibited_claim}\n\n"
        "## Errors\n\n"
        f"{errors}\n\n"
        "Machine-readable evidence: `docs/findings/phase1/evidence/dependency_readiness.json`\n"
    )


def write_finding(path: Path, record: dict[str, Any]) -> None:
    _atomic_write_text(path, render_finding(record))


def assert_finding_matches_record(path: Path, record: dict[str, Any]) -> None:
    if not path.is_file():
        raise EvidenceError(f"finding file does not exist: {path}")
    if path.read_text(encoding="utf-8") != render_finding(record):
        raise EvidenceError("finding does not match canonical evidence")
