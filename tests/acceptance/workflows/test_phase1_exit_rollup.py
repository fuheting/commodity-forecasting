from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from tools.workflows import phase1_exit_rollup as rollup


def _roadmap() -> str:
    lines = [
        "# Roadmap\n",
        "\n",
        "## Current Status: Phase 0 Complete; Phase 1 Exit Rollup Pending\n",
        "\n",
        "## Phase 1: Monthly Arabica History-Only Forecasting (Planned)\n",
    ]
    for task_id in rollup.OWNED_TASK_IDS:
        lines.append(f"- [x] **{task_id} — contract.** Evidence: canonical.\n")
    lines.extend(["\n", "## Phase 2: Untouched\n", "\n", "- [ ] Keep this line.\n"])
    return "".join(lines)


def _results(failing: str | None = None) -> tuple[rollup.TaskResult, ...]:
    return tuple(
        {
            "task_id": task_id,
            "evidence_path": rollup._spec(task_id).evidence_path.as_posix(),
            "finding_path": rollup._spec(task_id).finding_path.as_posix(),
            "outcome": "failed" if task_id == failing else "pass",
            "reason": "injected exact failure" if task_id == failing else "canonical validator passed",
        }
        for task_id in rollup.PREDECESSOR_TASK_IDS
    )


def _fixture(root: Path) -> None:
    for task_id in rollup.PREDECESSOR_TASK_IDS:
        spec = rollup._spec(task_id)
        evidence = root / spec.evidence_path
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text("{}", encoding="utf-8")
        finding = root / spec.finding_path
        finding.parent.mkdir(parents=True, exist_ok=True)
        finding.write_text("finding", encoding="utf-8")
    roadmap = root / rollup.ROADMAP_RELATIVE_PATH
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text(_roadmap(), encoding="utf-8")


def test_complete_publication_reconciles_initially_unchecked_p104_and_cli_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fixture(tmp_path)
    roadmap = tmp_path / rollup.ROADMAP_RELATIVE_PATH
    roadmap.write_text(roadmap.read_text(encoding="utf-8").replace("- [x] **P1-04", "- [ ] **P1-04"), encoding="utf-8")
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: _results())
    roadmap.chmod(0o600)
    (tmp_path / rollup._spec("P1-01").finding_path).chmod(0o600)

    assert rollup.main(["--repo-root", str(tmp_path), "--publish"]) == 0
    assert json.loads(capsys.readouterr().out)["phase_outcome"] == "complete"
    published = rollup.validate_publication(tmp_path)
    assert published["phase_outcome"] == "complete"
    text = roadmap.read_text(encoding="utf-8")
    assert "- [x] **P1-04" in text
    assert "- [x] **P1-09" in text
    assert "## Current Status: Phase 0 Complete; Phase 1 Complete\n" in text
    assert "## Phase 1: Monthly Arabica History-Only Forecasting (Complete)\n" in text
    assert stat.S_IMODE((tmp_path / rollup.ROADMAP_RELATIVE_PATH).stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / rollup.FINDING_RELATIVE_PATH).stat().st_mode) == 0o644
    assert stat.S_IMODE((tmp_path / rollup.EVIDENCE_RELATIVE_PATH).stat().st_mode) == 0o644
    assert rollup.main(["--repo-root", str(tmp_path), "--validate-publication"]) == 0
    assert rollup.main(["--repo-root", str(tmp_path), "--check-roadmap"]) == 0


def test_validate_publication_rejects_current_predecessor_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path)
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: _results())
    assert rollup.publish(tmp_path, generated_at_utc="2026-08-24T15:00:00Z")["phase_outcome"] == "complete"
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: _results(failing="P1-05"))

    with pytest.raises(rollup.EvidenceRollupError, match="stale against current canonical evidence"):
        rollup.validate_publication(tmp_path)


def test_incomplete_publication_returns_one_and_reconciles_invalid_checked_p104(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path)
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: _results(failing="P1-04"))
    original = (tmp_path / rollup.ROADMAP_RELATIVE_PATH).read_text(encoding="utf-8")

    assert rollup.main(["--repo-root", str(tmp_path), "--publish"]) == 1
    record = rollup.validate_publication(tmp_path)
    assert record["phase_outcome"] == "incomplete"
    assert [gate["task_id"] for gate in record["incomplete_gates"]] == ["P1-04"]
    updated = (tmp_path / rollup.ROADMAP_RELATIVE_PATH).read_text(encoding="utf-8")
    assert "- [ ] **P1-04" in updated
    assert "- [ ] **P1-09" in updated
    assert "## Current Status: Phase 0 Complete; Phase 1 Exit Rollup Pending\n" in updated
    assert "## Phase 1: Monthly Arabica History-Only Forecasting (Planned)\n" in updated
    assert "## Phase 2: Untouched\n" in updated
    assert original.split("## Phase 2: Untouched\n", 1)[1] == updated.split("## Phase 2: Untouched\n", 1)[1]
    assert rollup.main(["--repo-root", str(tmp_path), "--validate-publication"]) == 0
    assert rollup.main(["--repo-root", str(tmp_path), "--check-roadmap"]) == 0


@pytest.mark.parametrize(
    ("fail_at", "label"),
    ((1, "finding"), (2, "JSON"), (3, "roadmap")),
)
def test_publication_surfaces_each_replacement_failure_without_rollback_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int, label: str
) -> None:
    _fixture(tmp_path)
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: _results())
    calls: list[Path] = []

    def replace(source: Path, destination: Path) -> None:
        calls.append(destination)
        if len(calls) == fail_at:
            raise OSError(f"injected {label} replacement failure")
        source.replace(destination)

    with pytest.raises(rollup.PublicationError, match=f"injected {label} replacement failure"):
        rollup.publish(tmp_path, replace_file=replace, generated_at_utc="2026-08-24T15:00:00Z")
    destinations = [
        tmp_path / rollup.FINDING_RELATIVE_PATH,
        tmp_path / rollup.EVIDENCE_RELATIVE_PATH,
        tmp_path / rollup.ROADMAP_RELATIVE_PATH,
    ]
    assert calls == destinations[:fail_at]
    for destination in destinations:
        assert list(destination.parent.glob(f".{destination.name}.*")) == []
    assert "## Current Status: Phase 0 Complete; Phase 1 Exit Rollup Pending\n" in (
        tmp_path / rollup.ROADMAP_RELATIVE_PATH
    ).read_text(encoding="utf-8")
    with pytest.raises(rollup.RollupError):
        rollup.validate_publication(tmp_path)


def test_publication_rejects_direct_roadmap_divergence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture(tmp_path)
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: _results(failing="P1-08"))
    assert rollup.main(["--repo-root", str(tmp_path), "--publish"]) == 1
    roadmap = tmp_path / rollup.ROADMAP_RELATIVE_PATH
    roadmap.write_text(roadmap.read_text(encoding="utf-8").replace("Keep this line.", "Changed line."), encoding="utf-8")
    assert rollup.main(["--repo-root", str(tmp_path), "--validate-publication"]) != 0
    assert rollup.main(["--repo-root", str(tmp_path), "--check-roadmap"]) != 0


def test_publication_rejects_owned_task_line_prose_divergence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path)
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: _results())
    assert rollup.publish(tmp_path, generated_at_utc="2026-08-24T15:00:00Z")["phase_outcome"] == "complete"
    roadmap = tmp_path / rollup.ROADMAP_RELATIVE_PATH
    roadmap.write_text(
        roadmap.read_text(encoding="utf-8").replace(
            "**P1-05 — contract.** Evidence: canonical.",
            "**P1-05 — changed contract.** Evidence: divergent.",
        ),
        encoding="utf-8",
    )

    with pytest.raises(rollup.RoadmapTransformError, match="owned task lines diverge"):
        rollup.validate_publication(tmp_path)


def test_structural_roadmap_error_is_not_an_incomplete_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture(tmp_path)
    roadmap = tmp_path / rollup.ROADMAP_RELATIVE_PATH
    roadmap.write_text(roadmap.read_text(encoding="utf-8").replace("## Phase 2: Untouched", "## Phase 2: Untouched\n## Phase 1: Monthly Arabica History-Only Forecasting (Planned)"), encoding="utf-8")
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: _results(failing="P1-01"))

    assert rollup.main(["--repo-root", str(tmp_path), "--publish"]) != 0
    assert not (tmp_path / rollup.EVIDENCE_RELATIVE_PATH).exists()


def test_publication_rejects_symlinked_output_ancestor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    docs = tmp_path / "docs"
    findings = docs / "findings"
    findings.rename(tmp_path / "findings-real")
    (outside / "findings").mkdir()
    findings.symlink_to(outside / "findings", target_is_directory=True)
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: _results())

    with pytest.raises(rollup.PublicationError, match="outside|symlinked"):
        rollup.publish(tmp_path)
    assert not (outside / "findings" / "phase1" / "exit_rollup.md").exists()


def test_real_canonical_validator_interoperability() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    results = rollup.validate_predecessors(repo_root)

    assert [result["task_id"] for result in results] == list(rollup.PREDECESSOR_TASK_IDS)
    assert all(result["outcome"] == "pass" or result["outcome"] in rollup.NON_PASS_OUTCOMES for result in results)
