"""Static, no-import observation of the project TimeCopilot installation."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

INSTALLED_DISTRIBUTIONS = (
    "timecopilot", "torch", "transformers", "accelerate",
    "timecopilot-chronos-forecasting", "timecopilot-uni2ts", "timecopilot-timesfm",
    "timecopilot-tirex", "timecopilot-tirex2", "timecopilot-toto",
    "timecopilot-toto-2", "tfc-t0", "nixtla", "tabpfn-time-series",
)
ADAPTER_MANIFEST: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "timecopilot/models/foundation/chronos.py": (),
        "timecopilot/models/foundation/flowstate.py": (),
        "timecopilot/models/foundation/moirai.py": (
            "timecopilot/models/utils/gluonts_forecaster.py",
        ),
        "timecopilot/models/foundation/patchtst_fm.py": (),
        "timecopilot/models/foundation/sundial.py": (),
        "timecopilot/models/foundation/tabpfn.py": (),
        "timecopilot/models/foundation/tirex.py": (),
        "timecopilot/models/foundation/timesfm.py": (),
        "timecopilot/models/foundation/toto.py": (),
        "timecopilot/models/foundation/t0.py": (),
        "timecopilot/models/foundation/timegpt.py": (),
    }
)
REPOSITORY_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?![A-Za-z0-9_.-])"
)
REPOSITORY_ID_SYMBOLS = frozenset(
    {"repo_id", "repo_ids", "repository_id", "repository_ids", "repositories", "model_id", "model_ids"}
)
STATIC_EXPOSURE_UNKNOWN_RATIONALE = (
    "Static source inspection cannot prove the returned output contract without execution."
)


class ScreeningError(RuntimeError):
    """Base error for an invalid or unsafe screening operation."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScreeningError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _direct_string_literals(value: ast.AST | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return {value.value} if REPOSITORY_ID_PATTERN.fullmatch(value.value) else set()
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return set().union(*(_direct_string_literals(item) for item in value.elts))
    return set()


def _direct_string_literal(value: ast.AST) -> set[str]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return {value.value} if REPOSITORY_ID_PATTERN.fullmatch(value.value) else set()
    return set()


def _semantic_leaf(value: ast.AST) -> str | None:
    if isinstance(value, ast.Name):
        return value.id.lower()
    if isinstance(value, ast.Attribute):
        return value.attr.lower()
    return None


def _paired_assignment_ids(target: ast.AST, value: ast.AST | None) -> set[str]:
    leaf = _semantic_leaf(target)
    if leaf is not None:
        return _direct_string_literals(value) if leaf in REPOSITORY_ID_SYMBOLS else set()
    if (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
    ):
        return set().union(
            *(_paired_assignment_ids(target_item, value_item) for target_item, value_item in zip(target.elts, value.elts))
        )
    return set()


def _semantic_repository_ids(tree: ast.AST) -> list[str]:
    """Extract only repository IDs that participate in executable adapter semantics."""

    repositories: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = list(node.args.posonlyargs) + list(node.args.args)
            defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
            for argument, default in zip(positional, defaults):
                if argument.arg.lower() in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literals(default))
            for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                if argument.arg.lower() in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literals(default))
        elif isinstance(node, ast.Assign):
            if len(node.targets) == 1:
                repositories.update(_paired_assignment_ids(node.targets[0], node.value))
        elif isinstance(node, ast.AnnAssign):
            repositories.update(_paired_assignment_ids(node.target, node.value))
        elif isinstance(node, ast.Compare):
            expressions = [node.left, *node.comparators]
            for left, right in zip(expressions, expressions[1:]):
                if _semantic_leaf(left) in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literal(right))
                if _semantic_leaf(right) in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literal(left))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.lower() in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literals(value))
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literals(keyword.value))
    return sorted(repositories)


def inspect_timecopilot_adapter_source(
    distribution: importlib.metadata.Distribution,
    adapter_file: str | Path,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Inspect an installed adapter as text/AST without importing package modules."""

    requested = Path(adapter_file).as_posix()
    if requested not in ADAPTER_MANIFEST:
        raise ScreeningError(f"adapter is not in the fixed P1-03 manifest: {requested}")
    files = tuple(distribution.files or ())
    match = next((entry for entry in files if Path(str(entry)).as_posix().endswith(requested)), None)
    if match is None:
        raise ScreeningError(f"adapter file is not present in timecopilot distribution: {requested}")
    path = Path(str(distribution.locate_file(match))).resolve()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    trees = [tree]
    supporting_sources: list[dict[str, str]] = []
    for support_locator in ADAPTER_MANIFEST[requested]:
        support_match = next(
            (
                entry
                for entry in files
                if Path(str(entry)).as_posix().endswith(support_locator)
            ),
            None,
        )
        if support_match is None:
            raise ScreeningError(f"adapter inspection requires installed support source: {support_locator}")
        support_path = Path(str(distribution.locate_file(support_match))).resolve()
        support_source = support_path.read_text(encoding="utf-8")
        trees.append(ast.parse(support_source, filename=str(support_path)))
        supporting_sources.append(
            {
                "adapter_module_path": str(support_path),
                "adapter_module_sha256": sha256_file(support_path),
                "stable_locator": Path(str(support_match)).as_posix(),
            }
        )
    distribution_name = distribution.metadata.get("Name", "timecopilot")
    repositories = sorted(
        {repository for current_tree in trees for repository in _semantic_repository_ids(current_tree)}
    )
    return {
        "distribution_name": distribution_name,
        "distribution_present": True,
        "distribution_version": distribution.version,
        "observed_at_utc": _timestamp(observed_at or _utc_now()),
        "adapter_module_path": str(path),
        "adapter_module_sha256": sha256_file(path),
        "stable_locator": Path(str(match)).as_posix(),
        "supporting_sources": supporting_sources,
        "repository_ids": repositories,
        "point_exposure": "unknown",
        "interval_exposure": "unknown",
        "quantile_exposure": "unknown",
        "exposure_rationale": STATIC_EXPOSURE_UNKNOWN_RATIONALE,
    }

def observe_local_packages(
    repo_root: Path,
    *,
    injected_versions: Mapping[str, str | None] | None = None,
    injected_adapter_sources: Sequence[Mapping[str, Any]] | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Observe only the explicit project .venv, or a frozen injected unit-test mapping."""

    root = repo_root.resolve()
    timestamp = _timestamp(observed_at or _utc_now())
    if injected_versions is not None:
        return {
            "interpreter_path": str(root / ".venv/bin/python"),
            "interpreter_realpath": "injected",
            "project_root": str(root),
            "python_version": "injected",
            "observed_at_utc": timestamp,
            "distributions": [
                {
                    "distribution_name": name,
                    "distribution_present": version is not None,
                    "distribution_version": version,
                }
                for name, version in injected_versions.items()
            ],
            "adapter_sources": [dict(source) for source in (injected_adapter_sources or ())],
            "observation_mode": "injected",
        }
    expected_interpreter = (root / ".venv/bin/python").resolve()
    actual_interpreter = Path(sys.executable).resolve()
    if actual_interpreter != expected_interpreter or sys.prefix != str((root / ".venv").resolve()):
        raise ScreeningError(
            f"local observation requires the exact project .venv interpreter: {expected_interpreter}"
        )
    distributions: list[dict[str, Any]] = []
    for name in INSTALLED_DISTRIBUTIONS:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            distributions.append({"distribution_name": name, "distribution_present": False, "distribution_version": None})
        else:
            distributions.append({"distribution_name": name, "distribution_present": True, "distribution_version": distribution.version})
    try:
        timecopilot_distribution = importlib.metadata.distribution("timecopilot")
    except importlib.metadata.PackageNotFoundError:
        adapters: list[dict[str, Any]] = []
    else:
        adapters = [
            inspect_timecopilot_adapter_source(timecopilot_distribution, adapter, observed_at=observed_at)
            for adapter in ADAPTER_MANIFEST
        ]
    return {
        "interpreter_path": str(root / ".venv/bin/python"),
        "interpreter_realpath": str(actual_interpreter),
        "project_root": str(root),
        "python_version": sys.version.split()[0],
        "observed_at_utc": timestamp,
        "distributions": distributions,
        "adapter_sources": adapters,
        "observation_mode": "project_venv",
    }
