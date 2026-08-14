"""Repository path helpers for Phase 1 artifacts."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the source-checkout root for local development only."""

    return Path(__file__).resolve().parents[3]


def _root(root: Path | None) -> Path:
    return root if root is not None else repo_root()


def raw_workbook_path(root: Path | None = None) -> Path:
    return _root(root) / "data" / "raw" / "world_bank" / "pink_sheet" / "CMO-Historical-Data-Monthly.xlsx"


def source_metadata_path(root: Path | None = None) -> Path:
    return _root(root) / "data" / "raw" / "world_bank" / "pink_sheet" / "source_metadata.json"


def phase0_exit_evidence_path(root: Path | None = None) -> Path:
    return _root(root) / "docs" / "findings" / "phase0" / "evidence" / "roadmap_exit.json"


def phase1_findings_dir(root: Path | None = None) -> Path:
    return _root(root) / "docs" / "findings" / "phase1"


def phase1_evidence_dir(root: Path | None = None) -> Path:
    return phase1_findings_dir(root) / "evidence"


def dependency_readiness_evidence_path(root: Path | None = None) -> Path:
    return phase1_evidence_dir(root) / "dependency_readiness.json"


def dependency_readiness_finding_path(root: Path | None = None) -> Path:
    return phase1_findings_dir(root) / "dependency_readiness.md"


def standardized_root(root: Path | None = None) -> Path:
    return _root(root) / "data" / "standardized"


def model_ready_root(root: Path | None = None) -> Path:
    return _root(root) / "data" / "model_ready"
