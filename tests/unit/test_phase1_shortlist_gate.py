from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from commodity_forecasting.phase1 import screening, selection

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVED = [
    "amazon/chronos-2",
    "autogluon/chronos-2-synth",
    "autogluon/chronos-2-small",
    "google/timesfm-1.0-200m-pytorch",
    "google/timesfm-2.5-200m-transformers",
]
STATEMENTS = [
    "I approve these variants with accepted unknown risks.",
    "I approve autogluon/chronos-2-synth.",
    "No, proceed with the five previously approved variant. The unknown risk is their actual edge feasbility in terms of loading weights on the local machine, which is the recorded task for P1-05",
]
APPROVED_AT = "2026-08-15T03:19:54Z"


@pytest.fixture(scope="module")
def screening_record() -> dict[str, Any]:
    return screening.validate_published_state(REPO_ROOT)


@pytest.fixture(scope="module")
def screening_sha256() -> str:
    return selection.sha256_file(REPO_ROOT / selection.SCREENING_RELATIVE_PATH)


@pytest.fixture()
def approval_record(
    screening_record: dict[str, Any], screening_sha256: str
) -> dict[str, Any]:
    return selection.build_approval_record(
        screening_record,
        screening_sha256=screening_sha256,
        approved_variant_ids=APPROVED,
        approval_statements=STATEMENTS,
        approved_at_utc=APPROVED_AT,
    )


def test_exact_user_approved_order_is_preserved(approval_record: dict[str, Any]) -> None:
    assert approval_record["approved_variant_ids"] == APPROVED
    assert approval_record["accepted_unknown_risk_variant_ids"] == APPROVED
    assert approval_record["screening_eligible_variant_ids"] == []
    assert approval_record["execution_authorized"] is True
    assert any("loading weights on the local machine" in statement for statement in approval_record["approval_statements"])
    assert any("P1-05 must test that compatibility" in note for note in approval_record["notes"])


def test_missing_approval_blocks_execution(tmp_path: Path) -> None:
    with pytest.raises(selection.ApprovalMissingError, match="approval evidence is missing"):
        selection.validate_published_state(tmp_path)


def test_unknown_candidate_requires_exact_risk_acceptance(
    approval_record: dict[str, Any],
    screening_record: dict[str, Any],
    screening_sha256: str,
) -> None:
    mutated = copy.deepcopy(approval_record)
    mutated["accepted_unknown_risk_variant_ids"] = APPROVED[:-1]
    with pytest.raises(selection.ApprovalInvalidError, match="exactly match"):
        selection.validate_approval_record(
            mutated, screening_record, screening_sha256=screening_sha256
        )


def test_generic_approval_basis_cannot_admit_unknown_candidates(
    approval_record: dict[str, Any],
    screening_record: dict[str, Any],
    screening_sha256: str,
) -> None:
    mutated = copy.deepcopy(approval_record)
    mutated["approval_basis"] = "ordinary_approval"
    with pytest.raises(selection.ApprovalInvalidError, match="unknown-risk acceptance"):
        selection.validate_approval_record(
            mutated, screening_record, screening_sha256=screening_sha256
        )


@pytest.mark.parametrize("identifier", ["theforecastingcompany/t0-alpha", "TimeGPT"])
def test_excluded_candidate_cannot_be_approved(
    identifier: str,
    approval_record: dict[str, Any],
    screening_record: dict[str, Any],
    screening_sha256: str,
) -> None:
    mutated = copy.deepcopy(approval_record)
    mutated["approved_variant_ids"].append(identifier)
    mutated["accepted_unknown_risk_variant_ids"].append(identifier)
    with pytest.raises(selection.ApprovalInvalidError, match="cannot be approved"):
        selection.validate_approval_record(
            mutated, screening_record, screening_sha256=screening_sha256
        )


def test_unknown_or_unlisted_candidate_identity_is_rejected(
    approval_record: dict[str, Any],
    screening_record: dict[str, Any],
    screening_sha256: str,
) -> None:
    mutated = copy.deepcopy(approval_record)
    mutated["approved_variant_ids"].append("amazon/chronos-2-synth")
    mutated["accepted_unknown_risk_variant_ids"].append("amazon/chronos-2-synth")
    with pytest.raises(selection.ApprovalInvalidError, match="absent from P1-03"):
        selection.validate_approval_record(
            mutated, screening_record, screening_sha256=screening_sha256
        )


def test_duplicate_approval_is_rejected(
    approval_record: dict[str, Any],
    screening_record: dict[str, Any],
    screening_sha256: str,
) -> None:
    mutated = copy.deepcopy(approval_record)
    mutated["approved_variant_ids"].append(APPROVED[0])
    with pytest.raises(selection.ApprovalInvalidError, match="duplicates"):
        selection.validate_approval_record(
            mutated, screening_record, screening_sha256=screening_sha256
        )


def test_screening_hash_mismatch_invalidates_approval(
    approval_record: dict[str, Any], screening_record: dict[str, Any]
) -> None:
    with pytest.raises(selection.ApprovalInvalidError, match="hash mismatch"):
        selection.validate_approval_record(
            approval_record, screening_record, screening_sha256="0" * 64
        )


def test_screening_summary_must_match_current_evidence(
    approval_record: dict[str, Any],
    screening_record: dict[str, Any],
    screening_sha256: str,
) -> None:
    mutated = copy.deepcopy(approval_record)
    mutated["screening_counts"]["unknown/ineligible"] = 42
    with pytest.raises(selection.ApprovalInvalidError, match="counts mismatch"):
        selection.validate_approval_record(
            mutated, screening_record, screening_sha256=screening_sha256
        )


def test_unapproved_unknown_remainder_is_exact(
    approval_record: dict[str, Any],
    screening_record: dict[str, Any],
    screening_sha256: str,
) -> None:
    mutated = copy.deepcopy(approval_record)
    mutated["unapproved_unknown_variant_ids"] = mutated["unapproved_unknown_variant_ids"][1:]
    with pytest.raises(selection.ApprovalInvalidError, match="exact P1-03 remainder"):
        selection.validate_approval_record(
            mutated, screening_record, screening_sha256=screening_sha256
        )


def test_exact_approved_shortlist_passes_runtime_gate() -> None:
    assert selection.require_runtime_approval(REPO_ROOT, APPROVED) == tuple(APPROVED)


@pytest.mark.parametrize(("position", "identifier"), list(enumerate(APPROVED)))
def test_each_exact_approved_variant_passes_individual_gate(
    position: int, identifier: str
) -> None:
    assert selection.require_variant_approved(REPO_ROOT, identifier) == position


@pytest.mark.parametrize(
    "identifier",
    [
        "amazon/chronos-2-synth",
        "thuml/sundial-base-128m",
        "google/timesfm-2.5-200m-flax",
        "TimeGPT",
    ],
)
def test_unapproved_variant_fails_individual_gate(identifier: str) -> None:
    with pytest.raises(selection.CandidateNotApprovedError, match="is not approved"):
        selection.require_variant_approved(REPO_ROOT, identifier)


@pytest.mark.parametrize(
    "requested",
    [
        APPROVED[:-1],
        list(reversed(APPROVED)),
        [*APPROVED, "thuml/sundial-base-128m"],
        [APPROVED[0]],
    ],
)
def test_runtime_gate_rejects_subset_reorder_addition_or_single_candidate(
    requested: list[str],
) -> None:
    with pytest.raises(selection.CandidateNotApprovedError, match="exactly match approved order"):
        selection.require_runtime_approval(REPO_ROOT, requested)


def test_published_record_and_markdown_are_canonical() -> None:
    record = selection.validate_published_state(REPO_ROOT)
    evidence = json.loads(
        (REPO_ROOT / selection.EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    finding = (REPO_ROOT / selection.FINDING_RELATIVE_PATH).read_text(encoding="utf-8")
    assert record == evidence
    assert finding == selection.render_markdown(record)


def test_incomplete_roadmap_blocks_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selection, "ROADMAP_RELATIVE_PATH", Path("docs/poc_scope.md"))
    with pytest.raises(selection.ApprovalInvalidError, match="roadmap state is not complete"):
        selection.require_runtime_approval(REPO_ROOT, APPROVED)


def test_later_screening_hash_change_returns_execution_to_p104(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = selection.sha256_file

    def drifted(path: Path) -> str:
        if path.name == "model_screening.json":
            return "f" * 64
        return original(path)

    monkeypatch.setattr(selection, "sha256_file", drifted)
    with pytest.raises(selection.ApprovalInvalidError, match="hash mismatch"):
        selection.require_runtime_approval(REPO_ROOT, APPROVED)


def test_closed_record_schema_rejects_extra_fields(
    approval_record: dict[str, Any],
    screening_record: dict[str, Any],
    screening_sha256: str,
) -> None:
    mutated = copy.deepcopy(approval_record)
    mutated["default_candidate"] = APPROVED[0]
    with pytest.raises(selection.ApprovalInvalidError, match="keys differ"):
        selection.validate_approval_record(
            mutated, screening_record, screening_sha256=screening_sha256
        )
