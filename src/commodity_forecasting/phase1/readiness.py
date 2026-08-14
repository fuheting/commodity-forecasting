"""Read-only workbook readiness probe and clean-install evidence controller."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .contracts import (
    EVIDENCE_SCHEMA_VERSION,
    EXPECTED_PERIOD_COUNT,
    EXPECTED_PERIOD_END,
    EXPECTED_PERIOD_START,
    EXPECTED_RAW_SHA256,
    PUBLICATION_POLICY,
    READER_PACKAGE,
    READER_REQUIREMENT,
    REQUIRED_PASS_CHECKS,
    TARGET_COLUMN,
    TASK_ID,
    WORKSHEET_NAME,
    reader_version_supported,
)
from .evidence import (
    EvidenceError,
    assert_finding_matches_record,
    sanitize_diagnostic,
    utc_timestamp,
    validate_evidence_record,
    write_evidence,
    write_finding,
)
from .paths import (
    dependency_readiness_evidence_path,
    dependency_readiness_finding_path,
    phase0_exit_evidence_path,
    raw_workbook_path,
    source_metadata_path,
)

MONTH_TOKEN = re.compile(r"^(\d{4})M(0[1-9]|1[0-2])$")
MONTH_LIKE_TOKEN = re.compile(r"^\d{4}M")


class ReadinessError(RuntimeError):
    classification = "fail"


class RepoRootError(ReadinessError):
    classification = "blocked"


class ReaderUnavailableError(ReadinessError):
    classification = "blocked"


class ReaderVersionError(ReadinessError):
    classification = "blocked"


class WorkbookOpenError(ReadinessError):
    classification = "blocked"


class WorkbookMissingError(ReadinessError):
    pass


class SourceMetadataError(ReadinessError):
    pass


class WorkbookHashMismatchError(ReadinessError):
    pass


class WorksheetMissingError(ReadinessError):
    pass


class TargetColumnMissingError(ReadinessError):
    pass


class DuplicateTargetColumnError(ReadinessError):
    pass


class MonthlyTimestampError(ReadinessError):
    pass


class RoadmapConsistencyError(ReadinessError):
    pass


@dataclass(frozen=True)
class WorkbookObservation:
    sheet_name: str
    target_column: str
    header_row: int
    target_column_index: int
    period_start: str
    period_end: str
    period_count: int
    sha256_before: str
    sha256_after: str


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[..., CommandResult]


def parse_month_token(value: object) -> date:
    if not isinstance(value, str):
        raise MonthlyTimestampError("monthly timestamp must be a string in YYYYMmm form")
    match = MONTH_TOKEN.fullmatch(value)
    if match is None:
        raise MonthlyTimestampError(f"invalid monthly timestamp: {value!r}")
    return date(int(match.group(1)), int(match.group(2)), 1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_reader() -> Any:
    try:
        return importlib.import_module(READER_PACKAGE)
    except (ImportError, ModuleNotFoundError) as exc:
        raise ReaderUnavailableError("openpyxl is not importable") from exc


def _reader_version() -> str:
    try:
        version = importlib.metadata.version(READER_PACKAGE)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ReaderUnavailableError("openpyxl distribution metadata is unavailable") from exc
    if not reader_version_supported(version):
        raise ReaderVersionError(f"openpyxl {version} does not satisfy >=3.1,<4")
    return version


def _scan_worksheet(worksheet: Any) -> tuple[int, int, list[str]]:
    target_positions: list[tuple[int, int]] = []
    periods: list[str] = []
    periods_started = False
    for row_index, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
        for column_index, value in enumerate(row, start=1):
            if value == TARGET_COLUMN:
                target_positions.append((row_index, column_index))
        first_value = row[0] if row else None
        if isinstance(first_value, str) and MONTH_TOKEN.fullmatch(first_value):
            parse_month_token(first_value)
            periods.append(first_value)
            periods_started = True
        elif periods_started and first_value not in {None, ""}:
            raise MonthlyTimestampError(f"invalid monthly timestamp after data began: {first_value!r}")
        elif isinstance(first_value, str) and MONTH_LIKE_TOKEN.match(first_value):
            parse_month_token(first_value)

    if not target_positions:
        raise TargetColumnMissingError(f"target column not found: {TARGET_COLUMN}")
    if len(target_positions) != 1:
        raise DuplicateTargetColumnError(f"target column must appear exactly once, found {len(target_positions)}")
    if not periods:
        raise MonthlyTimestampError("workbook contains no monthly timestamp tokens")
    parsed = [parse_month_token(period) for period in periods]
    if parsed != sorted(parsed) or len(set(parsed)) != len(parsed):
        raise MonthlyTimestampError("monthly timestamps must be unique and monotonic")
    header_row, target_column_index = target_positions[0]
    return header_row, target_column_index, periods


def probe_workbook(path: Path, *, expected_sha256: str) -> WorkbookObservation:
    if not path.is_file():
        raise WorkbookMissingError(f"raw workbook does not exist: {path}")
    sha256_before = sha256_file(path)
    if sha256_before != expected_sha256:
        raise WorkbookHashMismatchError("raw workbook hash does not match the preserved source metadata")

    workbook: Any | None = None
    pending_error: ReadinessError | None = None
    observation_data: tuple[int, int, list[str]] | None = None
    try:
        reader = _load_reader()
        workbook = reader.load_workbook(path, read_only=True, data_only=True)
        if WORKSHEET_NAME not in workbook.sheetnames:
            raise WorksheetMissingError(f"worksheet not found: {WORKSHEET_NAME}")
        observation_data = _scan_worksheet(workbook[WORKSHEET_NAME])
    except ReadinessError as exc:
        pending_error = exc
    except Exception as exc:
        pending_error = WorkbookOpenError(f"openpyxl could not read the workbook: {type(exc).__name__}: {exc}")
    finally:
        if workbook is not None:
            workbook.close()

    if not path.is_file():
        raise WorkbookHashMismatchError("raw workbook disappeared during the readiness probe")
    sha256_after = sha256_file(path)
    if sha256_after != expected_sha256:
        raise WorkbookHashMismatchError("raw workbook hash changed during the readiness probe")
    if pending_error is not None:
        raise pending_error
    if observation_data is None:
        raise WorkbookOpenError("workbook probe produced no observation")
    header_row, target_column_index, periods = observation_data
    return WorkbookObservation(
        sheet_name=WORKSHEET_NAME,
        target_column=TARGET_COLUMN,
        header_row=header_row,
        target_column_index=target_column_index,
        period_start=periods[0],
        period_end=periods[-1],
        period_count=len(periods),
        sha256_before=sha256_before,
        sha256_after=sha256_after,
    )


def child_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    result = dict(environment if environment is not None else os.environ)
    result.pop("PYTHONPATH", None)
    return result


def _absolute_repo_root(value: Path) -> Path:
    if not value.is_absolute():
        raise RepoRootError("--repo-root must be an absolute path")
    resolved = value.resolve()
    if not resolved.is_dir():
        raise RepoRootError(f"repository root does not exist: {resolved}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _load_json(path: Path, *, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise SourceMetadataError(f"{description} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceMetadataError(f"{description} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SourceMetadataError(f"{description} must be a JSON object")
    return value


def _project_version() -> str:
    try:
        return importlib.metadata.version("commodity-forecasting")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def installed_dependency_declared() -> bool:
    try:
        requirements = importlib.metadata.requires("commodity-forecasting") or []
    except importlib.metadata.PackageNotFoundError:
        return False
    for requirement in requirements:
        normalized = re.sub(r"\s+", "", requirement.lower()).split(";", maxsplit=1)[0]
        if normalized in {"openpyxl>=3.1,<4", "openpyxl<4,>=3.1"}:
            return True
    return False


def _empty_checks() -> dict[str, bool]:
    return {name: False for name in REQUIRED_PASS_CHECKS}


def _child_probe(repo_root: Path) -> dict[str, Any]:
    checks = _empty_checks()
    root = _absolute_repo_root(repo_root)
    checks["repo_root_explicit"] = True
    checks["publication_policy_present"] = True

    cwd = Path.cwd().resolve()
    outside_repo = not _is_relative_to(cwd, root)
    pythonpath_absent = "PYTHONPATH" not in os.environ
    installed_outside_repo = not _is_relative_to(Path(__file__).resolve(), root)
    checks["child_outside_repo"] = outside_repo
    checks["child_pythonpath_absent"] = pythonpath_absent
    checks["install_non_editable"] = installed_outside_repo
    if not outside_repo or not pythonpath_absent or not installed_outside_repo:
        raise RepoRootError("installed child must run outside the repo without PYTHONPATH from a non-editable install")
    if not installed_dependency_declared():
        raise SourceMetadataError("installed project metadata does not declare openpyxl>=3.1,<4")
    checks["dependency_declared"] = True
    exit_evidence = _load_json(phase0_exit_evidence_path(root), description="Phase 0 exit evidence")
    if exit_evidence.get("classification") != "pass":
        raise SourceMetadataError("Phase 0 exit evidence is not pass")
    checks["phase0_complete"] = True

    metadata = _load_json(source_metadata_path(root), description="raw source metadata")
    if metadata.get("sha256") != EXPECTED_RAW_SHA256:
        raise SourceMetadataError("source metadata does not contain the preserved workbook hash")
    workbook_path = raw_workbook_path(root)
    checks["workbook_exists"] = workbook_path.is_file()
    if not checks["workbook_exists"]:
        raise WorkbookMissingError(f"raw workbook does not exist: {workbook_path}")
    if sha256_file(workbook_path) != EXPECTED_RAW_SHA256:
        raise WorkbookHashMismatchError("raw workbook hash does not match the preserved source metadata")
    checks["raw_hash_before_matches"] = True

    version = _reader_version()
    checks["reader_version_supported"] = True
    observation = probe_workbook(workbook_path, expected_sha256=EXPECTED_RAW_SHA256)
    checks.update(
        {
            "raw_hash_before_matches": observation.sha256_before == EXPECTED_RAW_SHA256,
            "sheet_found": observation.sheet_name == WORKSHEET_NAME,
            "target_found_once": observation.target_column == TARGET_COLUMN,
            "periods_parse": (
                observation.period_start == EXPECTED_PERIOD_START
                and observation.period_end == EXPECTED_PERIOD_END
                and observation.period_count == EXPECTED_PERIOD_COUNT
            ),
            "raw_hash_after_matches": observation.sha256_after == EXPECTED_RAW_SHA256,
            "pip_check": True,
        }
    )
    child_owned_checks = set(REQUIRED_PASS_CHECKS) - {"cleanup_completed", "host_bootstrap_explicit"}
    if not all(checks[name] for name in child_owned_checks):
        raise ReadinessError("installed child did not satisfy every workbook-readiness check")
    return {
        "classification": "pass",
        "checks": checks,
        "errors": [],
        "resolved_openpyxl_version": version,
        "installed_project_version": _project_version(),
        "python_version": sys.version.split()[0],
        "working_directory_class": "outside_repository",
        "install_mode": "non_editable",
        "pythonpath_state": "absent",
        **asdict(observation),
    }


def _write_child_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def probe_installed(repo_root: Path, result_path: Path) -> dict[str, Any]:
    try:
        result = _child_probe(repo_root)
    except ReadinessError as exc:
        result = {
            "classification": exc.classification,
            "checks": _empty_checks(),
            "errors": [sanitize_diagnostic(str(exc))],
            "resolved_openpyxl_version": "unknown",
            "installed_project_version": _project_version(),
            "python_version": sys.version.split()[0],
            "working_directory_class": (
                "outside_repository" if not _is_relative_to(Path.cwd().resolve(), repo_root.resolve()) else "inside_repository"
            ),
            "install_mode": "unknown",
            "pythonpath_state": "absent" if "PYTHONPATH" not in os.environ else "present",
        }
    _write_child_result(result_path, result)
    return result


def run_command(
    stage: str,
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> CommandResult:
    del stage
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _stage_outcome(stage: str, command: Sequence[str], result: CommandResult) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": "pass" if result.returncode == 0 else "blocked",
        "exit_code": result.returncode,
        "sanitized_command": shlex.join(str(part) for part in command),
    }


def _base_record(repo_root: Path) -> dict[str, Any]:
    timestamp = utc_timestamp()
    expected_pythonpath = str(repo_root / "src")
    host_bootstrap_explicit = os.environ.get("PYTHONPATH") == expected_pythonpath
    host_pythonpath_state = "explicit_repo_src" if host_bootstrap_explicit else "missing_or_mismatch"
    pythonpath_prefix = f"PYTHONPATH={shlex.quote(expected_pythonpath)}" if host_bootstrap_explicit else "PYTHONPATH=<missing-or-mismatch>"
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": f"P1-01-{timestamp.replace(':', '').replace('-', '')}",
        "timestamp_utc": timestamp,
        "classification": "blocked",
        "mode": "clean-install-readiness",
        "controller_mode": "verify-clean-install",
        "child_mode": None,
        "sanitized_command": (
            f"{pythonpath_prefix} {shlex.quote(sys.executable)} -m "
            "commodity_forecasting.phase1.readiness verify-clean-install "
            f"--repo-root {shlex.quote(str(repo_root))}"
        ),
        "repo_root": str(repo_root),
        "stage_outcomes": [],
        "failed_stage": None,
        "child_exit_code": None,
        "reader_requirement": READER_REQUIREMENT,
        "resolved_openpyxl_version": "unknown",
        "installed_project_version": "unknown",
        "python_version": sys.version.split()[0],
        "working_directory_class": "controller",
        "install_mode": "unknown",
        "pythonpath_state": "host_bootstrap_only",
        "host_pythonpath_state": host_pythonpath_state,
        "expected_raw_sha256": EXPECTED_RAW_SHA256,
        "raw_sha256_before": None,
        "raw_sha256_after": None,
        "sheet_name": None,
        "target_column": None,
        "header_row": None,
        "target_column_index": None,
        "period_start": None,
        "period_end": None,
        "period_count": None,
        "publication_policy": PUBLICATION_POLICY.as_dict(),
        "checks": {**_empty_checks(), "host_bootstrap_explicit": host_bootstrap_explicit},
        "errors": [],
        "cleanup_status": "not_started",
        "artifact_paths": [
            "docs/findings/phase1/evidence/dependency_readiness.json",
            "docs/findings/phase1/dependency_readiness.md",
        ],
        "phase0_evidence": [
            "docs/findings/phase0/evidence/roadmap_exit.json",
            "docs/findings/phase0/evidence/world_bank_pink_sheet_availability.json",
        ],
    }


def _error_summary(result: CommandResult) -> str:
    text = result.stderr.strip() or result.stdout.strip() or "command failed without output"
    return sanitize_diagnostic(text)[-2000:]


def _venv_python(venv_root: Path) -> Path:
    return venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _prepare_install_source(repo_root: Path, temporary_root: Path) -> Path:
    """Copy the build inputs so setuptools never writes metadata into the checkout."""

    source_root = temporary_root / "source"
    source_root.mkdir()
    pyproject = repo_root / "pyproject.toml"
    package_source = repo_root / "src"
    if not pyproject.is_file() or not package_source.is_dir():
        raise SourceMetadataError("repository build inputs are missing")
    shutil.copy2(pyproject, source_root / "pyproject.toml")
    shutil.copytree(
        package_source,
        source_root / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    return source_root


def reconcile_roadmap(repo_root: Path, record: Mapping[str, Any]) -> None:
    path = repo_root / "docs" / "roadmap.md"
    if not path.is_file():
        raise RoadmapConsistencyError(f"roadmap does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"(?m)^- \[[ x-]\] (\*\*P1-01\b.*)$")
    state = "x" if record["classification"] == "pass" else " "
    updated, count = pattern.subn(rf"- [{state}] \1", text)
    if count != 1:
        raise RoadmapConsistencyError(f"expected exactly one P1-01 roadmap entry, found {count}")
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def verify_clean_install(
    repo_root: Path,
    *,
    command_runner: CommandRunner = run_command,
    temporary_root_factory: Callable[[], Path] | None = None,
    enforce_host_bootstrap: bool = False,
) -> dict[str, Any]:
    root = _absolute_repo_root(repo_root)
    record = _base_record(root)
    if enforce_host_bootstrap and not record["checks"]["host_bootstrap_explicit"]:
        record["failed_stage"] = "controller"
        record["errors"] = ["host bootstrap must set PYTHONPATH to the explicit repository src directory"]
        record["cleanup_status"] = "pass"
        record["checks"]["cleanup_completed"] = True
        record["stage_outcomes"] = [
            {"stage": "cleanup", "status": "pass", "exit_code": 0, "sanitized_command": "no temporary environment"}
        ]
        write_evidence(dependency_readiness_evidence_path(root), record)
        write_finding(dependency_readiness_finding_path(root), record)
        reconcile_roadmap(root, record)
        return record
    temporary_root: Path | None = None
    failed = False
    controller_blocked = False
    child_result: dict[str, Any] | None = None
    factory = temporary_root_factory or (lambda: Path(tempfile.mkdtemp(prefix="commodity-forecasting-p101-")))

    try:
        temporary_root = factory()
        temporary_root.mkdir(parents=True, exist_ok=True)
        venv_root = temporary_root / "venv"
        create_command = [sys.executable, "-m", "venv", str(venv_root)]
        create_result = command_runner(
            "create_environment",
            create_command,
            cwd=temporary_root,
            env=child_environment(),
        )
        record["stage_outcomes"].append(_stage_outcome("create_environment", create_command, create_result))
        if create_result.returncode != 0:
            record["failed_stage"] = "create_environment"
            record["errors"].append(_error_summary(create_result))
            failed = True
            controller_blocked = True

        clean_python = _venv_python(venv_root)
        if not failed:
            try:
                install_source = _prepare_install_source(root, temporary_root)
            except ReadinessError as exc:
                record["stage_outcomes"].append(
                    {
                        "stage": "install_project",
                        "status": "blocked",
                        "exit_code": 1,
                        "sanitized_command": "prepare temporary source snapshot",
                    }
                )
                record["failed_stage"] = "install_project"
                record["errors"].append(str(exc))
                failed = True
                controller_blocked = True
        if not failed:
            install_command = [
                str(clean_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(install_source),
            ]
            install_result = command_runner(
                "install_project",
                install_command,
                cwd=temporary_root,
                env=child_environment(),
            )
            record["stage_outcomes"].append(_stage_outcome("install_project", install_command, install_result))
            if install_result.returncode != 0:
                record["failed_stage"] = "install_project"
                record["errors"].append(_error_summary(install_result))
                failed = True
                controller_blocked = True

        if not failed:
            check_command = [str(clean_python), "-m", "pip", "check"]
            check_result = command_runner(
                "pip_check",
                check_command,
                cwd=temporary_root,
                env=child_environment(),
            )
            record["stage_outcomes"].append(_stage_outcome("pip_check", check_command, check_result))
            if check_result.returncode != 0:
                record["failed_stage"] = "pip_check"
                record["errors"].append(_error_summary(check_result))
                failed = True
                controller_blocked = True
            else:
                record["checks"]["pip_check"] = True

        child_result_path = temporary_root / "child-result.json"
        if not failed:
            probe_command = [
                str(clean_python),
                "-m",
                "commodity_forecasting.phase1.readiness",
                "probe-installed",
                "--repo-root",
                str(root),
                "--result-path",
                str(child_result_path),
            ]
            probe_result = command_runner(
                "probe_installed",
                probe_command,
                cwd=temporary_root,
                env=child_environment(),
            )
            probe_outcome = _stage_outcome("probe_installed", probe_command, probe_result)
            record["stage_outcomes"].append(probe_outcome)
            record["child_exit_code"] = probe_result.returncode
            if child_result_path.is_file():
                try:
                    loaded = json.loads(child_result_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        child_result = loaded
                except (OSError, json.JSONDecodeError):
                    child_result = None
            child_classification = child_result.get("classification") if child_result is not None else None
            valid_child_classification = child_classification in {"pass", "fail", "blocked", "unsupported"}
            expected_exit = 0 if child_classification == "pass" else 1
            if child_result is None or not valid_child_classification or probe_result.returncode != expected_exit:
                record["failed_stage"] = "probe_installed"
                record["errors"].append(
                    _error_summary(probe_result) if probe_result.returncode else "installed child wrote no valid result"
                )
                failed = True
                controller_blocked = True
            elif child_classification != "pass":
                probe_outcome["status"] = "fail" if child_classification == "fail" else "blocked"
                record["failed_stage"] = "probe_installed"
                failed = True
    except Exception as exc:
        if record["failed_stage"] is None:
            record["failed_stage"] = "create_environment" if temporary_root is None else "controller"
        record["errors"].append(sanitize_diagnostic(f"{type(exc).__name__}: {exc}"))
        failed = True
        controller_blocked = True
    finally:
        cleanup_error: Exception | None = None
        if temporary_root is not None and temporary_root.exists():
            try:
                shutil.rmtree(temporary_root)
                record["cleanup_status"] = "pass"
                record["checks"]["cleanup_completed"] = True
                record["stage_outcomes"].append(
                    {"stage": "cleanup", "status": "pass", "exit_code": 0, "sanitized_command": "cleanup temporary environment"}
                )
            except Exception as exc:
                cleanup_error = exc
        else:
            record["cleanup_status"] = "pass"
            record["checks"]["cleanup_completed"] = True
            record["stage_outcomes"].append(
                {"stage": "cleanup", "status": "pass", "exit_code": 0, "sanitized_command": "no temporary environment"}
            )
        if cleanup_error is not None:
            record["cleanup_status"] = "blocked"
            record["checks"]["cleanup_completed"] = False
            record["failed_stage"] = "cleanup"
            record["errors"].append(sanitize_diagnostic(f"cleanup failed: {cleanup_error}"))
            record["stage_outcomes"].append(
                {"stage": "cleanup", "status": "blocked", "exit_code": 1, "sanitized_command": "cleanup temporary environment"}
            )
            failed = True
            controller_blocked = True

    if child_result is not None:
        for key in (
            "resolved_openpyxl_version",
            "installed_project_version",
            "python_version",
            "working_directory_class",
            "install_mode",
            "pythonpath_state",
        ):
            if key in child_result:
                record[key] = child_result[key]
        child_checks = child_result.get("checks")
        if isinstance(child_checks, dict):
            record["checks"].update(
                {
                    name: value
                    for name, value in child_checks.items()
                    if name not in {"cleanup_completed", "host_bootstrap_explicit"}
                }
            )
        child_errors = child_result.get("errors")
        if isinstance(child_errors, list):
            record["errors"].extend(
                sanitized
                for error in child_errors
                if (sanitized := sanitize_diagnostic(str(error))) not in record["errors"]
            )
        observation_keys = {
            "sha256_before": "raw_sha256_before",
            "sha256_after": "raw_sha256_after",
            "sheet_name": "sheet_name",
            "target_column": "target_column",
            "header_row": "header_row",
            "target_column_index": "target_column_index",
            "period_start": "period_start",
            "period_end": "period_end",
            "period_count": "period_count",
        }
        for source, target in observation_keys.items():
            if source in child_result:
                record[target] = child_result[source]
        record["child_mode"] = "probe-installed"
        record["checks"]["cleanup_completed"] = record["cleanup_status"] == "pass"
        if child_result.get("classification") != "pass":
            record["classification"] = child_result.get("classification", "blocked")
            failed = True

    if controller_blocked:
        record["classification"] = "blocked"
    elif not failed and child_result is not None and child_result.get("classification") == "pass":
        record["classification"] = "pass"
        record["failed_stage"] = None
        record["errors"] = []
    elif child_result is not None:
        record["classification"] = child_result.get("classification", "blocked")
    else:
        record["classification"] = "blocked"

    try:
        validate_evidence_record(record)
    except EvidenceError as exc:
        record["classification"] = "fail"
        record["failed_stage"] = "evidence_validation"
        record["errors"].append(sanitize_diagnostic(f"evidence validation failed: {exc}"))

    write_evidence(dependency_readiness_evidence_path(root), record)
    write_finding(dependency_readiness_finding_path(root), record)
    reconcile_roadmap(root, record)
    return record


def assert_latest_run_roadmap_consistency(repo_root: Path) -> None:
    evidence_path = dependency_readiness_evidence_path(repo_root)
    finding_path = dependency_readiness_finding_path(repo_root)
    if not evidence_path.is_file():
        raise EvidenceError(f"canonical readiness evidence does not exist: {evidence_path}")
    record = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise EvidenceError("canonical readiness evidence must be an object")
    validate_evidence_record(record)
    assert_finding_matches_record(finding_path, record)
    roadmap = (repo_root / "docs" / "roadmap.md").read_text(encoding="utf-8")
    matches = re.findall(r"(?m)^- \[([ x-])\] \*\*P1-01\b.*$", roadmap)
    expected_state = "x" if record["classification"] == "pass" else " "
    if matches != [expected_state]:
        raise RoadmapConsistencyError("P1-01 roadmap state does not match canonical readiness evidence")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-clean-install", help="run the host clean-install controller")
    verify.add_argument("--repo-root", type=Path, required=True)
    probe = subparsers.add_parser("probe-installed", help="run the installed workbook probe")
    probe.add_argument("--repo-root", type=Path, required=True)
    probe.add_argument("--result-path", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        root = _absolute_repo_root(arguments.repo_root)
        if arguments.command == "verify-clean-install":
            record = verify_clean_install(root, enforce_host_bootstrap=True)
            return 0 if record["classification"] == "pass" else 1
        result = probe_installed(root, arguments.result_path)
        return 0 if result["classification"] == "pass" else 1
    except ReadinessError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
