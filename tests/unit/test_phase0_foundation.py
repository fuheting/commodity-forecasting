from pathlib import Path

import pytest

from commodity_forecasting.phase0.evidence import EvidenceError, validate_evidence_record, write_evidence
from commodity_forecasting.phase0.fixtures import FIXTURE_ID, fixture_hash, weekly_target_rows
from commodity_forecasting.phase0.guards import (
    CatalogError,
    LeakageError,
    RoadmapGateError,
    assert_covariate_cutoff,
    assert_roadmap_evidence_links,
    assert_safe_artifact_content,
    assert_weekly_alignment,
    reject_centered_window,
    reject_cross_boundary_fill,
    reject_random_split,
    validate_catalog_row,
    walk_forward_windows,
)


def _valid_record() -> dict[str, object]:
    return {
        "run_id": "UT-record",
        "test_id": "SM-01",
        "work_item": "covariate-support smoke test",
        "timestamp_utc": "2026-08-13T00:00:00Z",
        "mode": "network-smoke",
        "command": "pytest tests/smoke/test_covariate_support.py",
        "tool": "pytest",
        "timecopilot_version": "not_installed",
        "model_or_adapter": "unconfigured",
        "fixture_id": FIXTURE_ID,
        "data_origin": "synthetic",
        "credential_state": "not_required_or_not_configured",
        "network_state": "not_checked",
        "observed_result": "blocked",
        "classification": "blocked",
        "leakage_controls": ["synthetic fixture", "walk-forward only"],
        "artifact_paths": ["docs/findings/phase0/evidence/covariate_support.json"],
        "model_native_capability": "unknown",
        "adapter_exposure": "unknown",
        "gate_result": "blocked_or_unknown",
    }


def test_ut01_historical_synthetic_fixtures_are_deterministic_and_weekly() -> None:
    rows = weekly_target_rows()

    assert fixture_hash(rows) == fixture_hash(weekly_target_rows())
    assert_weekly_alignment(rows)
    assert walk_forward_windows(rows, history=5, horizon=3)[0].cutoff == "2026-01-30"


def test_ut02_evidence_schema_rejects_missing_malformed_and_secret_fields(tmp_path: Path) -> None:
    record = _valid_record()
    validate_evidence_record(record)
    write_evidence(tmp_path / "record.json", record)

    missing = dict(record)
    missing.pop("run_id")
    with pytest.raises(EvidenceError):
        validate_evidence_record(missing)

    malformed = dict(record)
    malformed["classification"] = "maybe"
    with pytest.raises(EvidenceError):
        validate_evidence_record(malformed)

    secret = dict(record)
    secret["observed_result"] = "api_key=abc123"
    with pytest.raises(EvidenceError):
        validate_evidence_record(secret)


def test_ut03_leakage_guards_block_unsafe_operations() -> None:
    rows = weekly_target_rows()

    reject_random_split("rolling-origin")
    with pytest.raises(LeakageError):
        reject_random_split("random_split")
    with pytest.raises(LeakageError):
        reject_centered_window(centered=True)
    with pytest.raises(LeakageError):
        reject_cross_boundary_fill("bfill")
    with pytest.raises(LeakageError):
        assert_covariate_cutoff(
            [{"ds": "2026-02-06", "availability_class": "observed"}],
            cutoff="2026-01-30",
        )

    assert_covariate_cutoff(
        [{"ds": "2026-02-06", "availability_class": "known_at_origin"}],
        cutoff="2026-01-30",
        allow_known_future=True,
    )
    assert walk_forward_windows(rows, history=5, horizon=3)


def test_ut04_path_and_content_guard_blocks_raw_data_and_secrets(tmp_path: Path) -> None:
    safe = tmp_path / "tests" / "fixtures" / "phase0" / "metadata.json"
    safe.parent.mkdir(parents=True)
    safe.write_text('{"data_origin": "synthetic"}\n', encoding="utf-8")
    assert_safe_artifact_content(safe)

    raw = tmp_path / "data" / "raw" / "provider" / "coffee.csv"
    raw.parent.mkdir(parents=True)
    raw.write_text("secret-free\n", encoding="utf-8")
    with pytest.raises(EvidenceError):
        assert_safe_artifact_content(raw)

    unsafe = tmp_path / "docs" / "findings" / "phase0" / "evidence.json"
    unsafe.parent.mkdir(parents=True)
    unsafe.write_text("token: abc123\n", encoding="utf-8")
    with pytest.raises(EvidenceError):
        assert_safe_artifact_content(unsafe)


def test_ut05_catalog_schema_preserves_unknown_values() -> None:
    row = {
        "dataset_id": "coffee_c_candidate",
        "category": "Price & Liquidity",
        "name": "Coffee C candidate metadata",
        "source_provider": "unknown",
        "source_locator": "unknown",
        "access_method": "unknown",
        "native_frequency": "unknown",
        "fields": ["settlement"],
        "programmatic_access": "unknown",
        "auth_required": "unknown",
        "status": "candidate",
        "history_start": "unknown",
        "history_end": "unknown",
        "roll_methodology": "unknown",
    }
    validate_catalog_row(row)

    incomplete = dict(row)
    incomplete.pop("dataset_id")
    with pytest.raises(CatalogError):
        validate_catalog_row(incomplete)

    guessed = dict(row)
    guessed["programmatic_access"] = ""
    with pytest.raises(CatalogError):
        validate_catalog_row(guessed)


def test_ut06_roadmap_completion_requires_existing_phase0_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "docs" / "findings" / "phase0" / "evidence" / "covariate_support.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")
    assert_roadmap_evidence_links([evidence])

    with pytest.raises(RoadmapGateError):
        assert_roadmap_evidence_links([])
    with pytest.raises(RoadmapGateError):
        assert_roadmap_evidence_links([tmp_path / "missing.json"])
    outside = tmp_path / "docs" / "other.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RoadmapGateError):
        assert_roadmap_evidence_links([outside])
