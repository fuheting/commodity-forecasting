"""Validate and enforce the P1-04 user-approved runtime shortlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import screening

TASK_ID = "P1-04"
SCHEMA_VERSION = 1
SCREENING_RELATIVE_PATH = Path("docs/findings/phase1/evidence/model_screening.json")
EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/shortlist_approval.json")
FINDING_RELATIVE_PATH = Path("docs/findings/phase1/shortlist_approval.md")
ROADMAP_RELATIVE_PATH = Path("docs/roadmap.md")
APPROVAL_BASIS = "explicit_unknown_risk_acceptance"
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
P1_04_ROADMAP_PATTERN = re.compile(r"(?m)^- \[([ x-])\] \*\*P1-04\b.*$")

REQUIRED_FIELDS = {
    "schema_version",
    "task_id",
    "decision_id",
    "approved_at_utc",
    "approval_actor",
    "approval_basis",
    "approval_statements",
    "screening_evidence_path",
    "screening_evidence_sha256",
    "screening_run_id",
    "screening_overall_classification",
    "screening_counts",
    "screening_eligible_variant_ids",
    "approved_variant_ids",
    "accepted_unknown_risk_variant_ids",
    "unapproved_unknown_variant_ids",
    "excluded_variants",
    "execution_authorized",
    "classification",
    "checks",
    "notes",
    "errors",
}

REQUIRED_CHECKS = {
    "p1_03_valid",
    "roadmap_complete",
    "p1_03_pass",
    "screening_hash_matches",
    "exact_variant_ids",
    "stable_order",
    "unknown_risks_explicitly_accepted",
    "excluded_variants_rejected",
    "runtime_gate_enabled",
}


class SelectionError(RuntimeError):
    """Base error for P1-04 approval and execution-gate failures."""


class ApprovalMissingError(SelectionError):
    """Raised when no durable approval record exists."""


class ApprovalInvalidError(SelectionError):
    """Raised when an approval record is malformed or stale."""


class CandidateNotApprovedError(SelectionError):
    """Raised when a runtime request differs from the exact approved order."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ApprovalInvalidError(f"{name} keys differ; missing={missing}, extra={extra}")


def _string_list(value: object, name: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ApprovalInvalidError(f"{name} must be a list of non-empty strings")
    if not allow_empty and not value:
        raise ApprovalInvalidError(f"{name} must not be empty")
    if len(value) != len(set(value)):
        raise ApprovalInvalidError(f"{name} must not contain duplicates")
    return value


def _screening_index(screening_record: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    variants = screening_record.get("variant_records")
    if not isinstance(variants, list):
        raise ApprovalInvalidError("P1-03 variant_records must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for variant in variants:
        if not isinstance(variant, dict):
            raise ApprovalInvalidError("P1-03 variant record must be an object")
        identifier = variant.get("canonical_variant_id")
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise ApprovalInvalidError("P1-03 canonical variant IDs must be unique strings")
        result[identifier] = variant
    return result


def validate_approval_record(
    record: Mapping[str, Any],
    screening_record: Mapping[str, Any],
    *,
    screening_sha256: str,
) -> dict[str, Any]:
    """Validate a decision against the exact current P1-03 evidence."""

    if not isinstance(record, dict):
        raise ApprovalInvalidError("approval record must be an object")
    _require_exact_keys(record, REQUIRED_FIELDS, "approval record")
    if record["schema_version"] != SCHEMA_VERSION or record["task_id"] != TASK_ID:
        raise ApprovalInvalidError("approval schema_version or task_id is invalid")
    if not isinstance(record["decision_id"], str) or not record["decision_id"]:
        raise ApprovalInvalidError("decision_id must be a non-empty string")
    approved_at = record["approved_at_utc"]
    if not isinstance(approved_at, str) or TIMESTAMP_PATTERN.fullmatch(approved_at) is None:
        raise ApprovalInvalidError("approved_at_utc must be a UTC second timestamp")
    try:
        datetime.strptime(approved_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ApprovalInvalidError("approved_at_utc is not a real timestamp") from exc
    if record["approval_actor"] != "user" or record["approval_basis"] != APPROVAL_BASIS:
        raise ApprovalInvalidError("approval must be an explicit user unknown-risk acceptance")
    statements = _string_list(record["approval_statements"], "approval_statements", allow_empty=False)
    if not any("unknown risk" in statement.lower() for statement in statements):
        raise ApprovalInvalidError("approval statements must explicitly accept unknown risks")
    if record["screening_evidence_path"] != SCREENING_RELATIVE_PATH.as_posix():
        raise ApprovalInvalidError("screening evidence path is not canonical")
    recorded_sha = record["screening_evidence_sha256"]
    if (
        not isinstance(recorded_sha, str)
        or SHA256_PATTERN.fullmatch(recorded_sha) is None
        or recorded_sha != screening_sha256
    ):
        raise ApprovalInvalidError("screening evidence hash mismatch invalidates approval")
    if screening_record.get("overall_classification") != "pass":
        raise ApprovalInvalidError("P1-03 must be a current pass")
    if record["screening_run_id"] != screening_record.get("run_id"):
        raise ApprovalInvalidError("screening run ID mismatch")
    if record["screening_overall_classification"] != screening_record.get("overall_classification"):
        raise ApprovalInvalidError("screening classification mismatch")
    if record["screening_counts"] != screening_record.get("derived_counts"):
        raise ApprovalInvalidError("screening counts mismatch")
    if record["screening_eligible_variant_ids"] != screening_record.get("eligible_variant_ids"):
        raise ApprovalInvalidError("screening eligible list mismatch")

    approved = _string_list(record["approved_variant_ids"], "approved_variant_ids", allow_empty=False)
    accepted_unknown = _string_list(
        record["accepted_unknown_risk_variant_ids"],
        "accepted_unknown_risk_variant_ids",
        allow_empty=False,
    )
    index = _screening_index(screening_record)
    missing = [identifier for identifier in approved if identifier not in index]
    if missing:
        raise ApprovalInvalidError(f"approved variants are absent from P1-03: {missing}")
    forbidden = [
        identifier
        for identifier in approved
        if index[identifier].get("result") in {"excluded", "ineligible", "blocked"}
    ]
    if forbidden:
        raise ApprovalInvalidError(f"excluded, rejected, or blocked variants cannot be approved: {forbidden}")
    expected_accepted_unknown = [
        identifier for identifier in approved if index[identifier].get("result") == "unknown/ineligible"
    ]
    if accepted_unknown != expected_accepted_unknown:
        raise ApprovalInvalidError("unknown-risk acceptance must exactly match approved unknown variants")
    unexpected_results = [
        identifier
        for identifier in approved
        if index[identifier].get("result") not in {"eligible", "unknown/ineligible"}
    ]
    if unexpected_results:
        raise ApprovalInvalidError(f"approved variants have unsupported results: {unexpected_results}")

    expected_unapproved = [
        identifier
        for identifier, variant in index.items()
        if variant.get("result") == "unknown/ineligible" and identifier not in approved
    ]
    if record["unapproved_unknown_variant_ids"] != expected_unapproved:
        raise ApprovalInvalidError("unapproved unknown list is not the exact P1-03 remainder")
    expected_excluded = [
        {
            "canonical_variant_id": identifier,
            "notes": variant.get("notes", []),
        }
        for identifier, variant in index.items()
        if variant.get("result") == "excluded"
    ]
    if record["excluded_variants"] != expected_excluded:
        raise ApprovalInvalidError("excluded variant summary differs from P1-03")
    if record["execution_authorized"] is not True or record["classification"] != "approved":
        raise ApprovalInvalidError("approved record must explicitly authorize execution")
    checks = record["checks"]
    if not isinstance(checks, dict):
        raise ApprovalInvalidError("checks must be an object")
    _require_exact_keys(checks, REQUIRED_CHECKS, "checks")
    if any(value is not True for value in checks.values()):
        raise ApprovalInvalidError("every approval check must be exactly true")
    _string_list(record["notes"], "notes")
    if record["errors"] != []:
        raise ApprovalInvalidError("approved record must have no errors")
    return dict(record)


def build_approval_record(
    screening_record: Mapping[str, Any],
    *,
    screening_sha256: str,
    approved_variant_ids: Sequence[str],
    approval_statements: Sequence[str],
    approved_at_utc: str,
) -> dict[str, Any]:
    """Build a record only from an explicit ordered user decision."""

    index = _screening_index(screening_record)
    approved = list(approved_variant_ids)
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "decision_id": f"P1-04-{approved_at_utc.replace('-', '').replace(':', '')}",
        "approved_at_utc": approved_at_utc,
        "approval_actor": "user",
        "approval_basis": APPROVAL_BASIS,
        "approval_statements": list(approval_statements),
        "screening_evidence_path": SCREENING_RELATIVE_PATH.as_posix(),
        "screening_evidence_sha256": screening_sha256,
        "screening_run_id": screening_record["run_id"],
        "screening_overall_classification": screening_record["overall_classification"],
        "screening_counts": screening_record["derived_counts"],
        "screening_eligible_variant_ids": screening_record["eligible_variant_ids"],
        "approved_variant_ids": approved,
        "accepted_unknown_risk_variant_ids": [
            identifier for identifier in approved if index.get(identifier, {}).get("result") == "unknown/ineligible"
        ],
        "unapproved_unknown_variant_ids": [
            identifier
            for identifier, variant in index.items()
            if variant.get("result") == "unknown/ineligible" and identifier not in approved
        ],
        "excluded_variants": [
            {"canonical_variant_id": identifier, "notes": variant.get("notes", [])}
            for identifier, variant in index.items()
            if variant.get("result") == "excluded"
        ],
        "execution_authorized": True,
        "classification": "approved",
        "checks": {name: True for name in sorted(REQUIRED_CHECKS)},
        "notes": [
            "P1-03 unknown/ineligible is an evidence state, not proof of runtime infeasibility.",
            "The user explicitly accepted the recorded unknown risks for only the ordered variants above.",
            "The accepted unknown risk is actual edge feasibility when loading weights on the local machine.",
            "P1-05 must test that compatibility without adding, reordering, or substituting variants.",
        ],
        "errors": [],
    }
    return validate_approval_record(record, screening_record, screening_sha256=screening_sha256)


def render_markdown(record: Mapping[str, Any]) -> str:
    approved = record["approved_variant_ids"]
    unapproved = record["unapproved_unknown_variant_ids"]
    lines = [
        "# Phase 1 Shortlist Approval",
        "",
        f"- Decision ID: `{record['decision_id']}`",
        f"- Approved at: `{record['approved_at_utc']}`",
        f"- Classification: `{record['classification']}`",
        f"- Approval basis: `{record['approval_basis']}`",
        f"- P1-03 evidence SHA-256: `{record['screening_evidence_sha256']}`",
        "",
        "## Approved execution order",
        "",
    ]
    lines.extend(f"{number}. `{identifier}`" for number, identifier in enumerate(approved, start=1))
    lines.extend(
        [
            "",
            "All approved variants retain P1-03 `unknown/ineligible` evidence status. The user explicitly accepted the unknown local edge-feasibility risk for shortlist admission; actual weight loading and compatibility are deferred to P1-05. This approval does not rewrite the underlying evidence.",
            "",
            "## User approval statements",
            "",
        ]
    )
    lines.extend(f"- {statement}" for statement in record["approval_statements"])
    lines.extend(["", "## Exclusions", ""])
    for excluded in record["excluded_variants"]:
        notes = " ".join(excluded["notes"])
        lines.append(f"- `{excluded['canonical_variant_id']}` — {notes}")
    lines.extend(["", "## Remaining unknown/ineligible variants", ""])
    lines.append(f"{len(unapproved)} variants remain unapproved and cannot enter P1-05.")
    lines.extend(f"- `{identifier}`" for identifier in unapproved)
    lines.extend(
        [
            "",
            "## Gate",
            "",
            "Downstream execution must present the exact approved list in the recorded order. Any P1-03 evidence-byte change invalidates this approval and returns execution to P1-04.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish_approval(repo_root: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    root = repo_root.resolve()
    screening_path = root / SCREENING_RELATIVE_PATH
    screening_record = screening.validate_published_state(root)
    validated = validate_approval_record(
        record,
        screening_record,
        screening_sha256=sha256_file(screening_path),
    )
    markdown = render_markdown(validated).encode("utf-8")
    evidence = (json.dumps(validated, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(root / FINDING_RELATIVE_PATH, markdown)
    _atomic_write(root / EVIDENCE_RELATIVE_PATH, evidence)
    return validated


def validate_published_state(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    evidence_path = root / EVIDENCE_RELATIVE_PATH
    if not evidence_path.is_file():
        raise ApprovalMissingError("P1-04 approval evidence is missing; runtime execution is blocked")
    screening_record = screening.validate_published_state(root)
    try:
        raw = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApprovalInvalidError("P1-04 approval evidence is unreadable") from exc
    record = validate_approval_record(
        raw,
        screening_record,
        screening_sha256=sha256_file(root / SCREENING_RELATIVE_PATH),
    )
    finding_path = root / FINDING_RELATIVE_PATH
    if not finding_path.is_file() or finding_path.read_text(encoding="utf-8") != render_markdown(record):
        raise ApprovalInvalidError("P1-04 Markdown does not match canonical approval evidence")
    roadmap_path = root / ROADMAP_RELATIVE_PATH
    if not roadmap_path.is_file() or P1_04_ROADMAP_PATTERN.findall(
        roadmap_path.read_text(encoding="utf-8")
    ) != ["x"]:
        raise ApprovalInvalidError("P1-04 roadmap state is not complete")
    return record


def require_runtime_approval(repo_root: Path, requested_variant_ids: Sequence[str]) -> tuple[str, ...]:
    """Gate runtime entry with exact candidate identity and order."""

    record = validate_published_state(repo_root)
    requested = list(requested_variant_ids)
    approved = record["approved_variant_ids"]
    if requested != approved:
        raise CandidateNotApprovedError(
            f"runtime candidates must exactly match approved order; approved={approved}, requested={requested}"
        )
    return tuple(approved)


def require_variant_approved(repo_root: Path, variant_id: str) -> int:
    """Authorize one exact candidate and return its zero-based approved position."""

    record = validate_published_state(repo_root)
    approved = record["approved_variant_ids"]
    if variant_id not in approved:
        raise CandidateNotApprovedError(f"runtime candidate is not approved: {variant_id}")
    return approved.index(variant_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--repo-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.repo_root.is_absolute():
        print("--repo-root must be absolute", file=sys.stderr)
        return 1
    try:
        record = validate_published_state(args.repo_root)
    except (SelectionError, screening.ScreeningError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
