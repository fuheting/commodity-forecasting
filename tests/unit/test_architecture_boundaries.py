from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PACKAGE_ROOT = SOURCE_ROOT / "commodity_forecasting"
HISTORICAL_NAMESPACES = {"phase0", "phase1"}
DEVELOPER_PACKAGE_ROOTS = {"tests", "tools"}
REUSABLE_PACKAGE_ROOTS = (
    "commodity_forecasting.data",
    "commodity_forecasting.forecasting",
    "commodity_forecasting.evaluation",
    "commodity_forecasting.analysis",
    "commodity_forecasting.integrations",
)


def _production_modules() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SOURCE_ROOT).with_suffix("").parts)


def _imported_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = f"{node.module}." if node.module else ""
            names.extend(f"{prefix}{alias.name}" for alias in node.names)
    return names


def _path_literal_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [part for part in node.value.replace("\\", "/").split("/") if part]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _path_literal_parts(node.left) + _path_literal_parts(node.right)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [part for item in node.elts for part in _path_literal_parts(item)]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "joinpath"
    ):
        return [part for argument in node.args for part in _path_literal_parts(argument)]
    return []


def test_production_modules_do_not_import_test_or_tool_packages() -> None:
    violations: list[str] = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported_name in _imported_names(tree):
            if imported_name.partition(".")[0] in DEVELOPER_PACKAGE_ROOTS:
                violations.append(f"{_module_name(path)} imports {imported_name}")

    assert violations == [], "\n".join(violations)


def test_production_modules_do_not_reference_finding_or_roadmap_paths() -> None:
    violations: list[str] = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            parts = [part.casefold() for part in _path_literal_parts(node)]
            pairs = set(zip(parts, parts[1:]))
            if ("docs", "findings") in pairs or ("docs", "roadmap.md") in pairs:
                violations.append(_module_name(path))
                break

    assert violations == [], "\n".join(violations)


def test_historical_phase_namespaces_are_absent_from_production() -> None:
    namespace_directories = {
        namespace
        for namespace in HISTORICAL_NAMESPACES
        if any((PACKAGE_ROOT / namespace).rglob("*.py"))
    }
    assert namespace_directories == set()


def test_production_modules_do_not_import_historical_phase_namespaces() -> None:
    imported_names: list[str] = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported_name in _imported_names(tree):
            if HISTORICAL_NAMESPACES.intersection(imported_name.split(".")):
                imported_names.append(f"{_module_name(path)} imports {imported_name}")

    assert imported_names == [], "\n".join(imported_names)


def test_reusable_package_roots_import_without_developer_tooling() -> None:
    script = textwrap.dedent(
        f"""
        import importlib
        import importlib.abc
        import sys

        sys.path.insert(0, {str(SOURCE_ROOT)!r})

        class RejectDeveloperTooling(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.partition('.')[0] in {DEVELOPER_PACKAGE_ROOTS!r}:
                    raise RuntimeError(f"reusable core imported developer tooling: {{fullname}}")
                return None

        sys.meta_path.insert(0, RejectDeveloperTooling())
        for module_name in {REUSABLE_PACKAGE_ROOTS!r}:
            importlib.import_module(module_name)
        """
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_package_version_surface_matches_project_metadata() -> None:
    pyproject_lines = (
        (REPOSITORY_ROOT / "pyproject.toml")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    version_line = next(
        line for line in pyproject_lines if line.startswith("version = ")
    )
    expected_version = version_line.partition("=")[2].strip().strip('"')

    from commodity_forecasting import __version__

    assert __version__ == expected_version
