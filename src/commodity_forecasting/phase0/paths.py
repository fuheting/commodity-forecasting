"""Repository path helpers for Phase 0 artifacts."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def phase0_fixture_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "tests" / "fixtures" / "phase0"


def phase0_findings_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "docs" / "findings" / "phase0"


def phase0_evidence_dir(root: Path | None = None) -> Path:
    return phase0_findings_dir(root) / "evidence"
