from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.workflows import phase1_exit_rollup as rollup


def _roadmap(overrides: dict[str, str] | None = None) -> str:
    lines = [
        "# Roadmap\n",
        "\n",
        "## Current Status: Phase 0 Complete; Phase 1 Exit Rollup Pending\n",
        "\n",
        "## Phase 1: Monthly Arabica History-Only Forecasting (Planned)\n",
    ]
    markers = {"P1-01": "x", "P1-02": "x", "P1-03": " ", "P1-04": "x", "P1-05": " "}
    markers.update({f"P1-{number:02d}": "x" for number in range(6, 9)})
    markers["P1-09"] = " "
    if overrides:
        markers.update(overrides)
    for task_id in rollup.OWNED_TASK_IDS:
        lines.append(f"- [{markers[task_id]}] **{task_id} — contract.** Evidence: canonical.\n")
    lines.extend(
        [
            "\n",
            "**Exit condition:** keep this sentence byte-identical.\n",
            "\n",
            "## Phase 2: Untouched\n",
            "\n",
            "- [ ] Deferred content remains unchanged.\n",
        ]
    )
    return "".join(lines)


def _results(*, failing: str | None = None) -> list[rollup.TaskResult]:
    results: list[rollup.TaskResult] = []
    for task_id in rollup.PREDECESSOR_TASK_IDS:
        outcome = "failed" if task_id == failing else "pass"
        results.append(
            {
                "task_id": task_id,
                "evidence_path": rollup._spec(task_id).evidence_path.as_posix(),
                "finding_path": rollup._spec(task_id).finding_path.as_posix(),
                "outcome": outcome,
                "reason": "canonical validator passed" if outcome == "pass" else "exact failure reason",
            }
        )
    return results


def _write_evidence(root: Path, task_id: str, value: object) -> None:
    spec = rollup._spec(task_id)
    path = root / spec.evidence_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _write_fixture_files(
    root: Path, values: dict[str, object], roadmap_markers: dict[str, str] | None = None
) -> None:
    for task_id, value in values.items():
        _write_evidence(root, task_id, value)
        finding = root / rollup._spec(task_id).finding_path
        finding.parent.mkdir(parents=True, exist_ok=True)
        finding.write_text("canonical finding", encoding="utf-8")
    roadmap = root / rollup.ROADMAP_RELATIVE_PATH
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text(_roadmap(roadmap_markers), encoding="utf-8")


def test_incomplete_transform_changes_only_owned_checkbox_tokens() -> None:
    original = _roadmap()
    updated = rollup.transform_roadmap(original, _results(failing="P1-05"), "incomplete")

    assert "## Current Status: Phase 0 Complete; Phase 1 Exit Rollup Pending\n" in updated
    assert "## Phase 1: Monthly Arabica History-Only Forecasting (Planned)\n" in updated
    assert "## Phase 2: Untouched\n" in updated
    assert "**Exit condition:** keep this sentence byte-identical.\n" in updated
    assert "- [ ] **P1-05" in updated
    assert "- [ ] **P1-09" in updated
    assert updated.count("- [x] **P1-01") == 1


def test_complete_transform_changes_exactly_the_two_status_headings() -> None:
    original = _roadmap()
    updated = rollup.transform_roadmap(original, _results(), "complete")

    assert "## Current Status: Phase 0 Complete; Phase 1 Complete\n" in updated
    assert "## Phase 1: Monthly Arabica History-Only Forecasting (Complete)\n" in updated
    assert "(Planned)" not in updated
    for task_id in rollup.OWNED_TASK_IDS:
        assert f"- [x] **{task_id}" in updated
    assert "## Phase 2: Untouched\n" in updated
    assert "**Exit condition:** keep this sentence byte-identical.\n" in updated


def test_transform_rejects_duplicate_owned_lines() -> None:
    with pytest.raises(rollup.RoadmapTransformError, match="P1-01"):
        rollup.transform_roadmap(_roadmap() + "- [ ] **P1-01 duplicate.\n", _results(), "complete")


@pytest.mark.parametrize("roadmap_markers", [
    {"P1-01": first, "P1-04": second, "P1-05": third}
    for first in ("x", " ")
    for second in ("x", " ")
    for third in ("x", " ")
])
def test_evidence_only_p104_and_p105_ignore_current_roadmap_checkbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, roadmap_markers: dict[str, str]
) -> None:
    values = {
        "P1-01": {"classification": "pass"},
        "P1-02": {"classification": "pass"},
        "P1-03": {"overall_classification": "pass", "run_id": "screening-run"},
        "P1-04": {"classification": "approved", "execution_authorized": True, "decision_id": "decision"},
        "P1-05": {
            "approval_decision_id": "decision",
            "approval_evidence_sha256": "a" * 64,
            "task_outcome": "pass",
            "matrix_completeness": "complete",
            "selected_reference": "reference",
            "candidate_records": [
                {"variant_id": "failed-candidate", "classification": "failed", "errors": ["candidate failed"]}
            ],
        },
        "P1-06": {"classification": "pass", "publication_protocol": {"marker_state": "pass_final"}},
        "P1-07": {"classification": "pass"},
        "P1-08": {"classification": "pass", "checks": {"roadmap_eligible": True}},
    }
    _write_fixture_files(tmp_path, values, roadmap_markers)
    calls = {task_id: 0 for task_id in rollup.PREDECESSOR_TASK_IDS}

    def mark(task_id: str, value: object) -> object:
        calls[task_id] += 1
        return value

    def p101_validate(record: dict[str, object]) -> None:
        calls["P1-01"] += 1

    def p101_finding(path: Path, record: dict[str, object]) -> None:
        calls["P1-01"] += 1

    monkeypatch.setattr(rollup.readiness_evidence, "validate_evidence_record", p101_validate)
    monkeypatch.setattr(rollup.readiness_evidence, "assert_finding_matches_record", p101_finding)
    monkeypatch.setattr(rollup.target_publication, "validate_published_state", lambda root: mark("P1-02", None))
    monkeypatch.setattr(
        rollup.model_screening,
        "validate_published_state",
        lambda root: mark("P1-03", values["P1-03"]),
    )
    monkeypatch.setattr(
        rollup.shortlist_approval,
        "validate_approval_record",
        lambda record, screening, screening_sha256: mark("P1-04", record),
    )
    monkeypatch.setattr(rollup.shortlist_approval, "sha256_file", lambda path: "a" * 64)
    monkeypatch.setattr(rollup.shortlist_approval, "render_markdown", lambda record: "canonical finding")
    monkeypatch.setattr(
        rollup.runtime_compatibility,
        "validate_record",
        lambda record: mark("P1-05", record),
    )
    monkeypatch.setattr(rollup.runtime_compatibility, "render_markdown", lambda record: "canonical finding")
    monkeypatch.setattr(rollup.runtime_compatibility, "roadmap_ready", lambda record: True)
    monkeypatch.setattr(
        rollup.backtest_publication,
        "validate_rolling_origin_publication",
        lambda root: mark("P1-06", values["P1-06"]),
    )
    monkeypatch.setattr(
        rollup.evaluation_publication,
        "validate_evaluation_publication",
        lambda root: mark("P1-07", values["P1-07"]),
    )
    monkeypatch.setattr(
        rollup.natural_language_publication,
        "validate_publication",
        lambda root: mark("P1-08", values["P1-08"]),
    )
    monkeypatch.setattr(
        rollup.shortlist_approval,
        "validate_published_state",
        lambda root: (_ for _ in ()).throw(AssertionError("roadmap-coupled P1-04 wrapper was called")),
    )
    monkeypatch.setattr(
        rollup.runtime_compatibility,
        "validate_published_state",
        lambda root: (_ for _ in ()).throw(AssertionError("roadmap-coupled P1-05 wrapper was called")),
    )

    results = rollup.validate_predecessors(tmp_path)

    assert [(result["task_id"], result["outcome"]) for result in results] == [
        (task_id, "pass") for task_id in rollup.PREDECESSOR_TASK_IDS
    ]
    assert calls["P1-04"] == 1
    assert calls["P1-05"] == 1


def test_all_nonpass_gates_and_candidate_observations_are_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw_values = {
        "P1-01": {"classification": "pass", "limitations": ["vintage limitation"]},
        "P1-02": {"classification": "blocked", "errors": ["dependency unavailable"]},
        "P1-03": {"overall_classification": "unknown", "unknowns": ["official edge unknown"]},
        "P1-04": {"classification": "malformed", "errors": ["schema differs"]},
        "P1-05": {
            "task_outcome": "pass",
            "candidate_records": [
                {"variant_id": "candidate-failed", "classification": "failed", "errors": ["failed detail"]},
                {"variant_id": "candidate-blocked", "classification": "blocked", "errors": ["blocked detail"]},
                {"variant_id": "candidate-unsupported", "classification": "unsupported", "errors": ["unsupported detail"]},
            ],
            "diagnostics": [{"message": "runtime diagnostic"}],
        },
        "P1-06": {"classification": "stale", "errors": ["stale marker"]},
        "P1-07": {"classification": "unknown", "non_pass_diagnostics": ["unknown metric source"]},
        "P1-08": {"classification": "failed", "diagnostics": [{"error_kind": "failed"}]},
    }
    _write_fixture_files(tmp_path, raw_values)
    reasons = {
        task_id: f"reason for {task_id}" for task_id in rollup.PREDECESSOR_TASK_IDS
    }
    task_results = [
        {
            "task_id": task_id,
            "evidence_path": rollup._spec(task_id).evidence_path.as_posix(),
            "finding_path": rollup._spec(task_id).finding_path.as_posix(),
            "outcome": "pass" if task_id == "P1-01" or task_id == "P1-05" else outcome,
            "reason": "canonical validator passed" if task_id in {"P1-01", "P1-05"} else reasons[task_id],
        }
        for task_id, outcome in zip(
            rollup.PREDECESSOR_TASK_IDS,
            ["pass", "blocked", "unknown", "malformed", "failed", "stale", "unknown", "failed"],
        )
    ]
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: tuple(task_results))

    record, transformed = rollup.build_exit_record(tmp_path, generated_at_utc="2026-08-24T15:00:00Z")

    assert record["phase_outcome"] == "incomplete"
    assert [gate["task_id"] for gate in record["incomplete_gates"]] == [
        "P1-02", "P1-03", "P1-04", "P1-06", "P1-07", "P1-08"
    ]
    assert [gate["reason"] for gate in record["incomplete_gates"]] == [reasons[task_id] for task_id in ["P1-02", "P1-03", "P1-04", "P1-06", "P1-07", "P1-08"]]
    candidate_observations = [
        observation for observation in record["preserved_observations"] if observation["kind"] == "candidate_non_pass"
    ]
    assert {observation["value"]["outcome"] for observation in candidate_observations} == {
        "failed", "blocked", "unsupported"
    }
    assert "## Current Status: Phase 0 Complete; Phase 1 Exit Rollup Pending\n" in transformed
    assert "## Phase 1: Monthly Arabica History-Only Forecasting (Planned)\n" in transformed
    assert "- [x] **P1-01" in transformed
    assert "- [x] **P1-05" in transformed
    assert "- [ ] **P1-09" in transformed
    rollup.validate_exit_record(record)


def test_rendering_is_deterministic_and_validates_mutual_agreement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_fixture_files(tmp_path, {task_id: {} for task_id in rollup.PREDECESSOR_TASK_IDS})
    results = _results()
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: tuple(results))
    record, transformed = rollup.build_exit_record(tmp_path, generated_at_utc="2026-08-24T15:00:00Z")

    markdown = rollup.render_exit_markdown(record)
    evidence = rollup.render_exit_json(record)
    assert markdown == rollup.render_exit_markdown(record)
    assert evidence == rollup.render_exit_json(record)
    rollup.validate_rendered_outputs(record, markdown, evidence)
    rollup.validate_roadmap_text(transformed, record)
    with pytest.raises(rollup.EvidenceRollupError):
        rollup.validate_rendered_outputs(record, markdown + "changed", evidence)


def test_markdown_escapes_untrusted_gate_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_fixture_files(tmp_path, {task_id: {} for task_id in rollup.PREDECESSOR_TASK_IDS})
    results = _results(failing="P1-08")
    results[-1]["reason"] = "`| [link](https://example.test)\n<script>"
    monkeypatch.setattr(rollup, "validate_predecessors", lambda root: tuple(results))
    record, _ = rollup.build_exit_record(tmp_path, generated_at_utc="2026-08-24T15:00:00Z")
    markdown = rollup.render_exit_markdown(record)

    assert "\n<script>" not in markdown
    assert "\\|" in markdown
    assert "\\n" in markdown
    assert "``" in markdown


def test_unexpected_canonical_validator_error_is_not_an_incomplete_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_fixture_files(tmp_path, {task_id: {} for task_id in rollup.PREDECESSOR_TASK_IDS})

    def explode(root: Path) -> None:
        raise RuntimeError("unexpected validator defect")

    monkeypatch.setattr(rollup.readiness_evidence, "validate_evidence_record", lambda record: None)
    monkeypatch.setattr(
        rollup.readiness_evidence,
        "assert_finding_matches_record",
        lambda path, record: None,
    )
    monkeypatch.setattr(rollup.target_publication, "validate_published_state", explode)
    with pytest.raises(RuntimeError, match="unexpected validator defect"):
        rollup.validate_predecessors(tmp_path)


def test_evidence_permission_error_is_a_command_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = tmp_path / "blocked.json"
    blocked.write_text("{}", encoding="utf-8")
    original_open = Path.open

    def deny_open(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> Any:
        if path == blocked:
            raise PermissionError("injected evidence permission failure")
        return original_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", deny_open)
    with pytest.raises(rollup.EvidenceRollupError, match="could not be read"):
        rollup._read_json_record(blocked)


@pytest.mark.parametrize("invalid_task_id", ["P1-01", "P1-02", "P1-03", "P1-06", "P1-07"])
def test_invalid_utf8_evidence_is_malformed_without_truncating_gates(
    tmp_path: Path, invalid_task_id: str
) -> None:
    _write_fixture_files(tmp_path, {task_id: {} for task_id in rollup.PREDECESSOR_TASK_IDS})
    invalid = tmp_path / rollup._spec(invalid_task_id).evidence_path
    invalid.write_bytes(b"{\xff")
    if invalid_task_id == "P1-06":
        p107 = tmp_path / rollup._spec("P1-07").evidence_path
        p107.write_text(json.dumps({"classification": "pass"}), encoding="utf-8")

    results = rollup.validate_predecessors(tmp_path)

    assert [result["task_id"] for result in results] == list(rollup.PREDECESSOR_TASK_IDS)
    result = next(result for result in results if result["task_id"] == invalid_task_id)
    assert result["outcome"] == "malformed"
    assert "encoding is malformed" in result["reason"]
    if invalid_task_id == "P1-06":
        assert next(result for result in results if result["task_id"] == "P1-07")["outcome"] == "failed"


@pytest.mark.parametrize("malformed_task_id", rollup.PREDECESSOR_TASK_IDS)
def test_invalid_utf8_finding_is_malformed_without_truncating_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed_task_id: str
) -> None:
    calls: list[str] = []

    def passing(task_id: str):
        def validate(root: Path, context: rollup.ValidationContext):
            calls.append(task_id)
            return _results()[rollup.PREDECESSOR_TASK_IDS.index(task_id)], None

        return validate

    for task_id in rollup.PREDECESSOR_TASK_IDS:
        validator_name = f"_validate_p1{task_id[-2:]}"
        monkeypatch.setattr(rollup, validator_name, passing(task_id))
    _write_fixture_files(tmp_path, {task_id: {} for task_id in rollup.PREDECESSOR_TASK_IDS})
    (tmp_path / rollup._spec(malformed_task_id).finding_path).write_bytes(b"\xff")

    results = rollup.validate_predecessors(tmp_path)

    assert calls == [task_id for task_id in rollup.PREDECESSOR_TASK_IDS if task_id != malformed_task_id]
    assert len(results) == len(rollup.PREDECESSOR_TASK_IDS)
    result = next(item for item in results if item["task_id"] == malformed_task_id)
    assert result["outcome"] == "malformed"
    assert rollup._spec(malformed_task_id).finding_path.as_posix() in result["reason"]
    assert "text encoding is malformed" in result["reason"]


@pytest.mark.parametrize(
    ("malformed_task_id", "dependent_task_id"),
    (("P1-02", "P1-03"), ("P1-03", "P1-04"), ("P1-04", "P1-05")),
)
def test_malformed_finding_dependency_is_not_misattributed_downstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformed_task_id: str,
    dependent_task_id: str,
) -> None:
    _write_fixture_files(tmp_path, {task_id: {} for task_id in rollup.PREDECESSOR_TASK_IDS})
    (tmp_path / rollup._spec(malformed_task_id).finding_path).write_bytes(b"\xff")

    def passing(task_id: str):
        def validate(root: Path, context: rollup.ValidationContext):
            return _results()[rollup.PREDECESSOR_TASK_IDS.index(task_id)], None

        return validate

    dependent_name = f"_validate_p1{dependent_task_id[-2:]}"
    dependent_validator = getattr(rollup, dependent_name)
    for task_id in rollup.PREDECESSOR_TASK_IDS:
        monkeypatch.setattr(rollup, f"_validate_p1{task_id[-2:]}", passing(task_id))
    monkeypatch.setattr(rollup, dependent_name, dependent_validator)
    monkeypatch.setattr(rollup.runtime_compatibility, "validate_record", lambda record: record)

    results = rollup.validate_predecessors(tmp_path)

    malformed = next(item for item in results if item["task_id"] == malformed_task_id)
    dependent = next(item for item in results if item["task_id"] == dependent_task_id)
    assert len(results) == len(rollup.PREDECESSOR_TASK_IDS)
    assert malformed["outcome"] == "malformed"
    assert rollup._spec(malformed_task_id).finding_path.as_posix() in malformed["reason"]
    assert dependent["outcome"] == "failed"
    assert rollup._spec(malformed_task_id).finding_path.as_posix() in dependent["reason"]
    assert rollup._spec(dependent_task_id).finding_path.as_posix() not in dependent["reason"]


def test_readable_p102_domain_failure_does_not_truncate_p103(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_fixture_files(tmp_path, {task_id: {} for task_id in rollup.PREDECESSOR_TASK_IDS})

    def passing(task_id: str):
        def validate(root: Path, context: rollup.ValidationContext):
            return _results()[rollup.PREDECESSOR_TASK_IDS.index(task_id)], None

        return validate

    monkeypatch.setattr(rollup, "_validate_p101", passing("P1-01"))
    for task_id in rollup.PREDECESSOR_TASK_IDS[3:]:
        monkeypatch.setattr(rollup, f"_validate_p1{task_id[-2:]}", passing(task_id))
    monkeypatch.setattr(
        rollup.target_publication,
        "validate_published_state",
        lambda root: (_ for _ in ()).throw(
            rollup.target_publication.RoadmapEligibilityError("readable P1-02 is not eligible")
        ),
    )
    monkeypatch.setattr(
        rollup.model_screening,
        "validate_published_state",
        lambda root: pytest.fail("P1-03 must not re-enter a failed P1-02 validator"),
    )

    results = rollup.validate_predecessors(tmp_path)

    p102 = next(item for item in results if item["task_id"] == "P1-02")
    p103 = next(item for item in results if item["task_id"] == "P1-03")
    assert len(results) == len(rollup.PREDECESSOR_TASK_IDS)
    assert p102["outcome"] == "failed"
    assert p103["outcome"] == "failed"
    assert p102["reason"] == "readable P1-02 is not eligible"
    assert "P1-02 evidence or finding could not be validated" in p103["reason"]
    assert "readable P1-02 is not eligible" in p103["reason"]
