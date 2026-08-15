from __future__ import annotations

import ast
import copy
import hashlib
import importlib.metadata
import json
import socket
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from commodity_forecasting.phase1 import screening


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / screening.INVENTORY_BASELINE_RELATIVE_PATH
NOW = datetime(2026, 8, 14, 14, 30, tzinfo=timezone.utc)
SOURCE_ID = "src:test"
LOCAL_SOURCE_ID = "src:local:test"


def fact(value: object, *, status: str = "known") -> dict[str, object]:
    return {
        "status": status,
        "value": value,
        "source_refs": [SOURCE_ID],
        "rationale": "Pinned test evidence establishes this fact.",
    }


def local_fact(value: object, *, status: str = "known") -> dict[str, object]:
    result = fact(value, status=status)
    result["source_refs"] = [LOCAL_SOURCE_ID, SOURCE_ID]
    return result


def local_observations() -> dict[str, object]:
    distributions = [
        {
            "distribution_name": name,
            "distribution_present": name == "timecopilot",
            "distribution_version": "0.0.30" if name == "timecopilot" else None,
        }
        for name in screening.INSTALLED_DISTRIBUTIONS
    ]
    adapters = []
    for index, (locator, supporting) in enumerate(screening.ADAPTER_MANIFEST.items()):
        repositories = ["vendor/model"] if index == 0 else [f"vendor/model-{index}"]
        adapters.append(
            {
                "distribution_name": "timecopilot",
                "distribution_present": True,
                "distribution_version": "0.0.30",
                "observed_at_utc": "2026-08-14T14:30:00Z",
                "adapter_module_path": str(REPO_ROOT / ".venv/lib/python3.13/site-packages" / locator),
                "adapter_module_sha256": "b" * 64,
                "stable_locator": locator,
                "supporting_sources": [
                    {
                        "adapter_module_path": str(REPO_ROOT / ".venv/lib/python3.13/site-packages" / item),
                        "adapter_module_sha256": "c" * 64,
                        "stable_locator": item,
                    }
                    for item in supporting
                ],
                "repository_ids": repositories,
                "point_exposure": "unknown",
                "interval_exposure": "unknown",
                "quantile_exposure": "unknown",
                "exposure_rationale": screening.STATIC_EXPOSURE_UNKNOWN_RATIONALE,
            }
        )
    return {
        "interpreter_path": str(REPO_ROOT / ".venv/bin/python"),
        "interpreter_realpath": str((REPO_ROOT / ".venv/bin/python").resolve()),
        "project_root": str(REPO_ROOT),
        "python_version": "3.13.12",
        "observed_at_utc": "2026-08-14T14:30:00Z",
        "distributions": distributions,
        "adapter_sources": adapters,
        "observation_mode": "project_venv",
    }


def valid_variant(identifier: str = "vendor/model") -> dict[str, object]:
    variant: dict[str, object] = {
        "family": "Chronos",
        "canonical_variant_id": identifier,
        "inventory_disposition": "screened_variant",
        "official_source_url": fact("https://example.test/model"),
        "source_version_or_date": fact("revision-1"),
        "retrieved_at_utc": fact("2026-08-14T14:30:00Z"),
        "applicable_installed_package_versions": fact({"timecopilot": "0.0.30"}),
        "artifact_identity": fact(identifier),
        "artifact_size": fact({"bytes": 123}),
        "runtime_framework": fact("torch"),
        "model_native": {
            "monthly_frequency": fact("frequency_agnostic"),
            "usable_context_months": fact(60),
            "forecast_horizon_months": fact(3),
            "history_only": fact(True),
            "univariate_only": fact(True),
            "model_specific_minimums": fact(True),
        },
        "timecopilot_adapter": {
            "artifact_identity": local_fact(identifier),
            "point": local_fact("unknown", status="unknown"),
            "interval": local_fact("unknown", status="unknown"),
            "quantile": local_fact("unknown", status="unknown"),
        },
        "probabilistic": {
            "point": fact(True),
            "interval": fact(True),
            "quantile": fact(False),
        },
        "device_target": "cuda",
        "device_status": fact("supported"),
        "offline_after_acquisition": fact("supported"),
        "cold_start_offline": fact("requires_prior_acquisition"),
        "runtime_auth": fact("none"),
        "acquisition_auth": fact("none"),
        "code_license": fact(
            {"status": "known", "identifier": "Apache-2.0", "terms": "official", "poc_use": "allowed"}
        ),
        "artifact_license": fact(
            {"status": "known", "identifier": "Apache-2.0", "terms": "official", "poc_use": "allowed"}
        ),
        "documented_memory_vram_requirement": fact(
            {
                "amount": 16,
                "unit": "GB",
                "normalized_gb": 16,
                "normalized_unit": "GB",
                "basis": "documented_inference_vram",
                "assumptions": "single sample inference in the documented configuration",
            }
        ),
        "fit_against_16gb_target": fact(True),
        "monthly_history_only_60x3_support": fact("unknown", status="unknown"),
        "result": "unknown/ineligible",
        "notes": [],
        "unknowns": [],
    }
    variant["unknowns"] = screening.canonical_unknown_fact_paths(variant)
    return variant


def valid_record(variants: list[dict[str, object]] | None = None) -> dict[str, object]:
    rows = variants or [valid_variant()]
    counts, eligible = screening.derive_eligible_projection(rows)
    return {
        "schema_version": 1,
        "task_id": "P1-03",
        "run_id": "p1-03-20260814T143000Z",
        "generated_at_utc": "2026-08-14T14:30:00Z",
        "target_gpu": {"device": "cuda", "memory_gb": 16},
        "p1_02_evidence_path": "docs/findings/phase1/evidence/target_pipeline.json",
        "p1_02_evidence_sha256": "a" * 64,
        "frozen_inventory_baseline_sha256": screening.FROZEN_INVENTORY_BASELINE_SHA256,
        "pinned_execution_catalog_sha256": screening.PINNED_EXECUTION_CATALOG_SHA256,
        "source_registry": {
            SOURCE_ID: {
                "url_or_path": "https://example.test/model",
                "source_kind": "official_model_card",
                "source_version_or_date": "revision-1",
                "retrieved_at_utc": "2026-08-14T14:30:00Z",
                "stable_locator": "revision-1#memory",
            },
            LOCAL_SOURCE_ID: {
                "url_or_path": ".venv/lib/python3.13/site-packages/timecopilot/models/foundation/chronos.py",
                "source_kind": "observed_local_package_source",
                "source_version_or_date": "timecopilot==0.0.30",
                "retrieved_at_utc": "2026-08-14T14:30:00Z",
                "stable_locator": "timecopilot/models/foundation/chronos.py",
                "sha256": "b" * 64,
            },
            "src:inventory:baseline": {
                "url_or_path": screening.INVENTORY_BASELINE_RELATIVE_PATH.as_posix(),
                "source_kind": "persisted_inventory_baseline",
                "source_version_or_date": "2026-08-14",
                "retrieved_at_utc": screening.EXECUTION_CATALOG_CAPTURED_AT_UTC,
                "stable_locator": screening.INVENTORY_BASELINE_RELATIVE_PATH.as_posix(),
            },
        },
        "official_catalog_snapshot": screening.pinned_catalog_snapshot(),
        "inventory_witnesses": [],
        "local_package_observations": local_observations(),
        "variant_records": rows,
        "derived_counts": counts,
        "eligible_variant_ids": eligible,
        "overall_classification": "pass",
        "checks": {key: True for key in screening.REQUIRED_CHECK_KEYS},
        "errors": [],
        "notes": [],
    }


def validate_unit_record(record: dict[str, Any]) -> None:
    screening.validate_screening_record(record, validate_oracles=False)


def persisted_record() -> dict[str, Any]:
    value = json.loads((REPO_ROOT / screening.EVIDENCE_RELATIVE_PATH).read_text(encoding="utf-8"))
    return cast(dict[str, Any], value)


def test_persisted_inventory_baseline_is_parsed_directly_and_stably() -> None:
    inventory = screening.load_inventory_baseline(BASELINE)
    assert sum(len(ids) for ids in inventory.values()) == 44
    assert inventory["Chronos / Chronos-2"][0] == "amazon/chronos-bolt-tiny"
    assert inventory["Moirai"][-1] == "Salesforce/moirai-1.0-R-large"
    assert inventory["Toto / Toto-2"][-1] == "Datadog/Toto-2.0-Family-and-Friends"


def test_inventory_witness_rejects_missing_duplicate_or_orphan() -> None:
    baseline = {"Family": ("a/model", "b/model")}
    mappings = {
        "Family": [
            {"identifier": "a/model", "disposition": "screened_variant", "canonical_variant_id": "a/model"},
            {"identifier": "b/model", "disposition": "out_of_scope"},
        ]
    }
    witnesses = screening.build_inventory_witnesses(baseline, mappings)
    assert witnesses[0]["checks"]["complete"] is True
    broken = copy.deepcopy(mappings)
    broken["Family"][1]["identifier"] = "a/model"
    with pytest.raises(screening.InventoryError, match="missing=.*duplicate"):
        screening.build_inventory_witnesses(baseline, broken)


def test_baseline_parser_rejects_duplicate_identifiers(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.md"
    baseline.write_text(
        "### Family\n- Identifiers: `vendor/model`, `vendor/model`.\n"
        "## Installed TimeCopilot\n",
        encoding="utf-8",
    )
    with pytest.raises(screening.InventoryError, match="duplicate identifiers"):
        screening.load_inventory_baseline(baseline)


def test_inventory_reverse_closure_rejects_missing_and_extra_variant_records() -> None:
    baseline = {"Family": ("vendor/model", "vendor/bundle")}
    witnesses = screening.build_inventory_witnesses(
        baseline,
        {
            "Family": [
                {
                    "identifier": "vendor/model",
                    "disposition": "screened_variant",
                    "canonical_variant_id": "vendor/model",
                },
                {"identifier": "vendor/bundle", "disposition": "out_of_scope"},
            ]
        },
    )
    closed = {"vendor/model", "theforecastingcompany/t0-alpha", "TimeGPT"}
    screening.validate_inventory_closure(baseline, witnesses, closed)
    with pytest.raises(screening.InventoryError, match="missing=.*vendor/model"):
        screening.validate_inventory_closure(baseline, witnesses, closed - {"vendor/model"})
    with pytest.raises(screening.InventoryError, match="extra=.*vendor/unofficial"):
        screening.validate_inventory_closure(baseline, witnesses, closed | {"vendor/unofficial"})


def test_inventory_closure_requires_one_matching_primary_and_alias_only_extras() -> None:
    baseline = {"Family": ("vendor/model", "vendor/model-alias")}
    valid = screening.build_inventory_witnesses(
        baseline,
        {
            "Family": [
                {
                    "identifier": "vendor/model",
                    "disposition": "screened_variant",
                    "canonical_variant_id": "vendor/model",
                },
                {
                    "identifier": "vendor/model-alias",
                    "disposition": "alias",
                    "canonical_variant_id": "vendor/model",
                },
            ]
        },
    )
    variants = {"vendor/model", "theforecastingcompany/t0-alpha", "TimeGPT"}
    screening.validate_inventory_closure(baseline, valid, variants)

    duplicate_primary = copy.deepcopy(valid)
    duplicate_primary[0]["mappings"][1]["disposition"] = "screened_variant"
    with pytest.raises(screening.InventoryError, match="exactly one matching"):
        screening.validate_inventory_closure(baseline, duplicate_primary, variants)

    mismatched_primary = copy.deepcopy(valid)
    mismatched_primary[0]["mappings"][0]["canonical_variant_id"] = "vendor/model-alias"
    mismatched_primary[0]["mappings"][1]["canonical_variant_id"] = "vendor/model-alias"
    mismatched_variants = {"vendor/model-alias", "theforecastingcompany/t0-alpha", "TimeGPT"}
    with pytest.raises(screening.InventoryError, match="exactly one matching"):
        screening.validate_inventory_closure(baseline, mismatched_primary, mismatched_variants)

    alias_only = copy.deepcopy(valid)
    alias_only[0]["mappings"][0]["disposition"] = "alias"
    with pytest.raises(screening.InventoryError, match="exactly one matching"):
        screening.validate_inventory_closure(baseline, alias_only, variants)


def test_inventory_closure_rejects_cross_family_alias() -> None:
    baseline = {"Primary": ("vendor/model",), "Other": ("vendor/model-alias",)}
    witnesses = screening.build_inventory_witnesses(
        baseline,
        {
            "Primary": [
                {
                    "identifier": "vendor/model",
                    "disposition": "screened_variant",
                    "canonical_variant_id": "vendor/model",
                }
            ],
            "Other": [
                {
                    "identifier": "vendor/model-alias",
                    "disposition": "alias",
                    "canonical_variant_id": "vendor/model",
                }
            ],
        },
    )
    with pytest.raises(screening.InventoryError, match="share the primary witness family"):
        screening.validate_inventory_closure(
            baseline,
            witnesses,
            {"vendor/model", "theforecastingcompany/t0-alpha", "TimeGPT"},
        )


@pytest.mark.parametrize("mutation", ["add", "remove", "duplicate"])
def test_official_catalog_snapshot_blocks_catalog_drift(mutation: str) -> None:
    baseline = {"Family": ("vendor/a", "vendor/b")}
    identifiers = ["vendor/a", "vendor/b"]
    families: list[dict[str, Any]] = [
        {
            "family": "Family",
            "identifiers": identifiers.copy(),
            "official_sources": [
                {
                    "source_ref": "src:official:test",
                    "url": "https://example.test/catalog",
                    "source_version_status": "unknown",
                    "source_version_or_date": "unknown",
                }
            ],
            "retrieved_at_utc": screening.EXECUTION_CATALOG_CAPTURED_AT_UTC,
        }
    ]
    if mutation == "add":
        families[0]["identifiers"].append("vendor/c")
    elif mutation == "remove":
        families[0]["identifiers"].pop()
    else:
        families[0]["identifiers"].append("vendor/a")
    catalog = {
        "schema_version": 1,
        "task_id": "P1-03",
        "captured_at_utc": screening.EXECUTION_CATALOG_CAPTURED_AT_UTC,
        "inventory_baseline_path": screening.INVENTORY_BASELINE_RELATIVE_PATH.as_posix(),
        "inventory_baseline_sha256": "a" * 64,
        "families": families,
        "catalog_content_sha256": hashlib.sha256(
            json.dumps(families, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    with pytest.raises(screening.InventoryError):
        screening.validate_execution_official_catalog(
            catalog, baseline, baseline_sha256="a" * 64
        )


def test_embedded_manifests_are_separately_hashed_and_capture_time_is_fixed() -> None:
    screening.validate_embedded_manifests()
    assert screening.FROZEN_INVENTORY_BASELINE_SHA256 != (
        screening.PINNED_EXECUTION_CATALOG_SHA256
    )
    assert screening.FROZEN_INVENTORY_BASELINE == screening.load_inventory_baseline(BASELINE)
    assert all(
        retrieved_at == screening.EXECUTION_CATALOG_CAPTURED_AT_UTC
        for _, _, retrieved_at in screening.PINNED_EXECUTION_CATALOG.values()
    )


def test_baseline_parser_does_not_silently_inject_missing_moirai_default(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.md"
    baseline.write_text(
        "### Moirai\n"
        "- Current official collection identifiers: `Salesforce/moirai-1.1-R-small`.\n"
        "## Installed TimeCopilot\n",
        encoding="utf-8",
    )
    assert screening.load_inventory_baseline(baseline) == {
        "Moirai": ("Salesforce/moirai-1.1-R-small",)
    }


def test_default_validation_uses_only_embedded_oracles(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> object:
        raise AssertionError("default validation read an evidence-preparation artifact")

    monkeypatch.setattr(screening, "load_inventory_baseline", forbidden)
    screening.validate_screening_record(persisted_record())


@pytest.mark.parametrize(
    "mutation",
    ["inventory_hash", "catalog_hash", "snapshot", "family", "disposition", "url", "version", "retrieved", "source_ref"],
)
def test_embedded_oracle_binding_rejects_ledger_drift(mutation: str) -> None:
    record = persisted_record()
    variant = cast(list[dict[str, Any]], record["variant_records"])[0]
    if mutation == "inventory_hash":
        record["frozen_inventory_baseline_sha256"] = "0" * 64
    elif mutation == "catalog_hash":
        record["pinned_execution_catalog_sha256"] = "0" * 64
    elif mutation == "snapshot":
        record["official_catalog_snapshot"][0]["identifiers"].pop()
    elif mutation == "family":
        variant["family"] = "Chronos"
    elif mutation == "disposition":
        variant["inventory_disposition"] = "alias"
    elif mutation == "url":
        variant["official_source_url"]["value"] = "https://example.test/drift"
    elif mutation == "version":
        variant["source_version_or_date"]["status"] = "known"
        variant["source_version_or_date"]["value"] = "fake-revision"
    elif mutation == "retrieved":
        variant["retrieved_at_utc"]["value"] = "2026-08-14T14:24:45Z"
    else:
        variant["official_source_url"]["source_refs"][0] = "src:official:amazon_chronos_bolt_mini"
    with pytest.raises((screening.InventoryError, screening.ScreeningSchemaError)):
        screening.validate_screening_record(record)


@pytest.mark.parametrize(
    "mutation",
    [
        "official_extra_ref", "official_cross_variant_ref", "adapter_extra_ref",
        "derived_duplicate_ref", "source_kind", "unapproved_registry",
        "blank_license_identifier", "blank_license_terms",
    ],
)
def test_closed_provenance_and_registry_reject_drift(mutation: str) -> None:
    record = persisted_record()
    variant = record["variant_records"][0]
    official_ref = variant["official_source_url"]["source_refs"][0]
    if mutation == "official_extra_ref":
        variant["artifact_size"]["source_refs"].append("src:local:chronos")
    elif mutation == "official_cross_variant_ref":
        variant["artifact_size"]["source_refs"][0] = "src:official:amazon_chronos_bolt_mini"
    elif mutation == "adapter_extra_ref":
        variant["timecopilot_adapter"]["point"]["source_refs"].append(official_ref)
    elif mutation == "derived_duplicate_ref":
        variant["monthly_history_only_60x3_support"]["source_refs"].append(
            "src:inventory:baseline"
        )
    elif mutation == "source_kind":
        record["source_registry"][official_ref]["source_kind"] = "personal_blog"
    elif mutation == "unapproved_registry":
        record["source_registry"]["src:personal_blog"] = {
            "url_or_path": "https://example.test/blog",
            "source_kind": "personal_blog",
            "source_version_or_date": "2026-08-14",
            "retrieved_at_utc": screening.EXECUTION_CATALOG_CAPTURED_AT_UTC,
            "stable_locator": "blog post",
        }
    elif mutation == "blank_license_identifier":
        variant["code_license"]["value"]["identifier"] = "   "
    else:
        variant["code_license"]["value"]["terms"] = ""
    with pytest.raises(screening.ScreeningSchemaError):
        screening.validate_screening_record(record)


@pytest.mark.parametrize(
    "mutation",
    ["official_locator", "local_path", "entry_extra_field", "inventory_path", "inventory_hash"],
)
def test_source_registry_entries_are_exactly_bound(mutation: str) -> None:
    record = persisted_record()
    registry = record["source_registry"]
    official_ref = record["variant_records"][0]["official_source_url"]["source_refs"][0]
    if mutation == "official_locator":
        registry[official_ref]["stable_locator"] = "mutable prose"
    elif mutation == "local_path":
        registry["src:local:chronos"]["url_or_path"] = ".venv/wrong/chronos.py"
    elif mutation == "entry_extra_field":
        registry[official_ref]["source_status"] = "known"
    elif mutation == "inventory_path":
        registry["src:inventory:baseline"]["persisted_inventory_path"] = "other.md"
    else:
        registry["src:inventory:baseline"]["sha256"] = "0" * 64
    with pytest.raises(screening.ScreeningSchemaError):
        screening.validate_screening_record(record)


@pytest.mark.parametrize("mutation", ["missing", "renamed", "extra", "false", "integer_true"])
def test_checks_are_an_exact_closed_all_true_boolean_schema(mutation: str) -> None:
    record = persisted_record()
    checks = record["checks"]
    key = next(iter(screening.REQUIRED_CHECK_KEYS))
    if mutation == "missing":
        checks.pop(key)
    elif mutation == "renamed":
        checks[f"renamed_{key}"] = checks.pop(key)
    elif mutation == "extra":
        checks["extra_check"] = True
    elif mutation == "false":
        checks[key] = False
    else:
        checks[key] = 1
    with pytest.raises(screening.ScreeningSchemaError, match="canonical true boolean keys"):
        screening.validate_screening_record(record)


@pytest.mark.parametrize(
    "mutation", ["generated", "observation", "adapter", "future_adapter", "local_registry"]
)
def test_publication_timestamps_must_be_exactly_coherent(mutation: str) -> None:
    record = persisted_record()
    drift = "2099-01-01T00:00:00Z" if mutation == "future_adapter" else "2026-08-14T14:24:45Z"
    if mutation == "generated":
        record["generated_at_utc"] = drift
    elif mutation == "observation":
        record["local_package_observations"]["observed_at_utc"] = drift
    elif mutation in {"adapter", "future_adapter"}:
        record["local_package_observations"]["adapter_sources"][0]["observed_at_utc"] = drift
    else:
        record["source_registry"]["src:local:chronos"]["retrieved_at_utc"] = drift
    with pytest.raises(screening.ScreeningSchemaError):
        screening.validate_screening_record(record)


def test_static_screen_can_never_derive_60x3_support() -> None:
    variant = valid_variant()
    assert screening.derive_monthly_history_only_60x3(variant) is None
    assert screening.classify_variant_record(variant) == "unknown/ineligible"


@pytest.mark.parametrize(("name", "value"), [("point", True), ("interval", False), ("quantile", True)])
def test_boolean_adapter_exposure_facts_are_rejected(name: str, value: bool) -> None:
    variant = valid_variant()
    variant["timecopilot_adapter"][name] = local_fact(value)  # type: ignore[index]
    record = valid_record([variant])
    with pytest.raises(screening.ScreeningSchemaError, match="must have unknown status and value"):
        validate_unit_record(record)


def test_unknown_precedes_known_failure_and_blocked_precedes_unknown() -> None:
    variant = valid_variant()
    variant["device_status"] = fact("unsupported")
    variant["runtime_auth"] = fact("unknown", status="unknown")
    assert screening.classify_variant_record(variant) == "unknown/ineligible"
    variant["artifact_size"] = fact("unknown", status="blocked")
    assert screening.classify_variant_record(variant) == "blocked"


def test_semantic_unknown_enum_values_remain_unknown_ineligible() -> None:
    variant = valid_variant()
    variant["device_status"] = fact("unknown")
    assert screening.classify_variant_record(variant) == "unknown/ineligible"


def test_fixed_exclusions_win_and_preserve_required_notes() -> None:
    t0 = valid_variant("theforecastingcompany/t0-alpha")
    t0["family"] = "T0"
    t0["notes"] = ["Fixed exclusion retained despite the current source-timing conflict."]
    t0["result"] = "excluded"
    timegpt = valid_variant("TimeGPT")
    timegpt["family"] = "TimeGPT"
    timegpt["notes"] = ["Excluded because the integration is API-backed."]
    timegpt["result"] = "excluded"
    assert screening.classify_variant_record(t0) == "excluded"
    assert screening.classify_variant_record(timegpt) == "excluded"


@pytest.mark.parametrize(
    "memory",
    [
        {"bytes": 1_000_000_000, "assumptions": "artifact bytes"},
        {"parameters": 100_000_000, "assumptions": "parameter count"},
        {"amount": 12, "unit": "GiB", "assumptions": "ambiguous units", "basis": "documented_inference_vram"},
        {"amount": 12, "unit": "GB", "assumptions": "generic CUDA claim", "basis": "generic_cuda"},
    ],
)
def test_artifact_size_parameter_count_and_ambiguous_memory_are_not_fit_proof(
    memory: dict[str, object],
) -> None:
    variant = valid_variant()
    variant["documented_memory_vram_requirement"] = fact(memory)
    assert screening.classify_variant_record(variant) == "unknown/ineligible"


def test_closed_enums_and_fact_provenance_are_enforced() -> None:
    record = valid_record()
    validate_unit_record(record)
    bad_enum = copy.deepcopy(record)
    bad_enum["variant_records"][0]["device_status"] = fact("maybe")  # type: ignore[index]
    with pytest.raises(screening.ScreeningSchemaError, match="unsupported value"):
        validate_unit_record(bad_enum)
    missing_ref = copy.deepcopy(record)
    missing_ref["variant_records"][0]["artifact_size"]["source_refs"] = []  # type: ignore[index]
    with pytest.raises(screening.ScreeningSchemaError, match="non-empty list"):
        validate_unit_record(missing_ref)


@pytest.mark.parametrize(
    "field",
    ["official_source_url", "source_version_or_date", "artifact_identity", "runtime_framework"],
)
def test_known_fact_semantic_unknown_sentinels_are_rejected(field: str) -> None:
    record = valid_record()
    record["variant_records"][0][field] = fact("unknown")  # type: ignore[index]
    with pytest.raises(screening.ScreeningSchemaError, match="unknown or empty sentinel"):
        validate_unit_record(record)


def test_artifact_identity_drift_and_erased_unknown_summary_are_rejected() -> None:
    identity_drift = valid_record()
    identity_drift["variant_records"][0]["artifact_identity"] = fact("vendor/other")  # type: ignore[index]
    with pytest.raises(screening.ScreeningSchemaError, match="canonical_variant_id"):
        validate_unit_record(identity_drift)

    erased = valid_record()
    erased["variant_records"][0]["runtime_auth"] = fact("unknown", status="unknown")  # type: ignore[index]
    erased["variant_records"][0]["result"] = "unknown/ineligible"  # type: ignore[index]
    counts, eligible = screening.derive_eligible_projection(erased["variant_records"])  # type: ignore[arg-type]
    erased["derived_counts"] = counts
    erased["eligible_variant_ids"] = eligible
    with pytest.raises(screening.ScreeningSchemaError, match="unknowns must exactly match"):
        validate_unit_record(erased)


@pytest.mark.parametrize("mutation", ["partial", "unrelated", "duplicate", "order"])
def test_unknown_fact_paths_are_recursive_exact_unique_and_ordered(mutation: str) -> None:
    variant = valid_variant()
    variant["runtime_auth"] = fact("unknown", status="unknown")
    variant["source_version_or_date"] = fact("unknown", status="unknown")
    variant["result"] = "unknown/ineligible"
    expected = ["runtime_auth", "source_version_or_date"]
    variant["unknowns"] = expected.copy()
    unknowns = cast(list[str], variant["unknowns"])
    if mutation == "partial":
        unknowns.pop()
    elif mutation == "unrelated":
        unknowns.append("artifact_size")
    elif mutation == "duplicate":
        unknowns.append("runtime_auth")
    else:
        unknowns.reverse()
    record = valid_record([variant])
    with pytest.raises(screening.ScreeningSchemaError, match="canonical recursively derived"):
        validate_unit_record(record)


def test_known_fact_nested_semantic_unknowns_are_canonical_paths() -> None:
    variant = valid_variant()
    variant["artifact_license"] = fact(
        {
            "status": "known",
            "identifier": "terms",
            "terms": "official terms",
            "poc_use": "unknown",
        }
    )
    variant["code_license"] = fact(
        {
            "status": "unknown",
            "identifier": "terms",
            "terms": "official terms",
            "poc_use": "allowed",
        }
    )
    paths = screening.canonical_unknown_fact_paths(variant)
    assert "artifact_license.value.poc_use" in paths
    assert "code_license.value.status" in paths
    assert paths == sorted(set(paths))


def test_nested_adapter_and_summary_unknown_paths_are_derived() -> None:
    variant = valid_variant()
    variant["timecopilot_adapter"]["artifact_identity"] = local_fact(  # type: ignore[index]
        "unknown", status="unknown"
    )
    variant["monthly_history_only_60x3_support"] = fact("unknown", status="unknown")
    variant["result"] = "unknown/ineligible"
    variant["unknowns"] = [
        "monthly_history_only_60x3_support",
        "timecopilot_adapter.artifact_identity",
        "timecopilot_adapter.interval",
        "timecopilot_adapter.point",
        "timecopilot_adapter.quantile",
    ]
    record = valid_record([variant])
    validate_unit_record(record)


def test_honest_unknown_and_empty_eligible_projection_can_overall_pass() -> None:
    variant = valid_variant()
    variant["runtime_auth"] = fact("unknown", status="unknown")
    variant["result"] = "unknown/ineligible"
    variant["unknowns"] = screening.canonical_unknown_fact_paths(variant)
    record = valid_record([variant])
    validate_unit_record(record)
    assert record["overall_classification"] == "pass"
    assert record["eligible_variant_ids"] == []


def test_blocked_fact_must_propagate_to_variant_and_overall() -> None:
    variant = valid_variant()
    variant["artifact_size"] = fact("unknown", status="blocked")
    variant["result"] = "blocked"
    record = valid_record([variant])
    record["overall_classification"] = "pass"
    with pytest.raises(screening.ScreeningSchemaError, match="propagate"):
        validate_unit_record(record)


def test_markdown_is_deterministic_and_driven_by_json() -> None:
    record = persisted_record()
    first = screening.render_markdown_report(record)
    second = screening.render_markdown_report(json.loads(json.dumps(record)))
    assert first == second
    assert "<https://huggingface.co/amazon/chronos-bolt-tiny>" in first
    assert "source_version_or_date" in first
    assert "fixed exclusion" in first.lower()
    assert "`unknown/ineligible`: 43" in first


def test_publish_order_is_markdown_first_json_last_and_never_roadmap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = valid_record()
    monkeypatch.setattr(screening, "validate_screening_record", lambda *args, **kwargs: None)
    destinations: list[Path] = []

    def replace(source: Path, destination: Path) -> None:
        destinations.append(destination.relative_to(tmp_path))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)

    screening.publish_screening_artifacts(tmp_path, record, replace_file=replace)
    assert destinations == [screening.FINDING_RELATIVE_PATH, screening.EVIDENCE_RELATIVE_PATH]
    assert screening.ROADMAP_RELATIVE_PATH not in destinations


def test_publish_rejects_malformed_curated_facts_before_observation_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = valid_record()
    record["variant_records"][0]["artifact_identity"] = fact("unknown")  # type: ignore[index]
    monkeypatch.setattr(screening, "_load_record", lambda _: record)
    monkeypatch.setattr(screening, "validate_p1_02_binding", lambda *args: "c" * 64)
    validate_record = screening.validate_screening_record
    events: list[str] = []

    def reject_before_refresh(value: dict[str, Any], **_: object) -> None:
        events.append("validate")
        validate_record(value, validate_oracles=False)

    def forbidden(*_: object, **__: object) -> object:
        events.append("observe_or_write")
        raise AssertionError("publish reached refresh or write after malformed curated input")

    monkeypatch.setattr(screening, "validate_screening_record", reject_before_refresh)
    monkeypatch.setattr(screening, "observe_local_packages", forbidden)
    monkeypatch.setattr(screening, "publish_screening_artifacts", forbidden)
    assert not hasattr(screening, "_normalize_legacy_unknown_facts")
    with pytest.raises(screening.ScreeningSchemaError, match="unknown or empty sentinel"):
        screening.publish(REPO_ROOT)
    assert events == ["validate"]


def test_publish_completes_full_oracle_validation_before_live_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = persisted_record()
    validate_record = screening.validate_screening_record
    events: list[str] = []
    monkeypatch.setattr(screening, "_load_record", lambda _: record)
    monkeypatch.setattr(screening, "validate_p1_02_binding", lambda *args: "c" * 64)

    def validate_spy(value: dict[str, Any], **kwargs: object) -> None:
        validate_record(value, **kwargs)  # type: ignore[arg-type]
        events.append("validated")

    def stop_at_observation(*_: object, **__: object) -> object:
        events.append("observe")
        raise RuntimeError("observation stop")

    def preparation_read_forbidden(*_: object, **__: object) -> object:
        raise AssertionError("publish read an ignored .omx preparation artifact")

    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if ".omx" in path.parts:
            raise AssertionError("publish read an ignored .omx preparation artifact")
        return original_read_text(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(screening, "validate_screening_record", validate_spy)
    monkeypatch.setattr(screening, "observe_local_packages", stop_at_observation)
    monkeypatch.setattr(screening, "load_inventory_baseline", preparation_read_forbidden)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    with pytest.raises(RuntimeError, match="observation stop"):
        screening.publish(REPO_ROOT)
    assert events == ["validated", "observe"]


def test_validate_p102_binding_calls_gate_before_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = tmp_path / screening.P1_02_EVIDENCE_RELATIVE_PATH
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")
    calls: list[str] = []

    def gate(root: Path) -> None:
        calls.append("gate")

    monkeypatch.setattr(screening.target_pipeline, "validate_published_state", gate)
    digest = screening.validate_p1_02_binding(tmp_path)
    assert calls == ["gate"]
    assert digest == screening.sha256_file(evidence)


def test_validate_p102_binding_rejects_mismatched_recorded_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = tmp_path / screening.P1_02_EVIDENCE_RELATIVE_PATH
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(screening.target_pipeline, "validate_published_state", lambda _: None)
    with pytest.raises(screening.ScreeningSchemaError, match="hash mismatch"):
        screening.validate_p1_02_binding(
            tmp_path,
            {
                "p1_02_evidence_path": screening.P1_02_EVIDENCE_RELATIVE_PATH.as_posix(),
                "p1_02_evidence_sha256": "0" * 64,
            },
        )


def test_injected_package_observation_never_reads_ambient_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_: str) -> object:
        raise AssertionError("ambient metadata was queried")

    monkeypatch.setattr(screening.importlib.metadata, "distribution", forbidden)
    observed = screening.observe_local_packages(
        tmp_path,
        injected_versions={"timecopilot": "0.0.30", "tabpfn-time-series": None},
        observed_at=NOW,
    )
    assert observed["observation_mode"] == "injected"
    assert observed["distributions"][0]["distribution_version"] == "0.0.30"


@pytest.mark.parametrize(
    "mutation",
    ["version", "hash", "repository_id", "exposure", "missing_adapter"],
)
def test_fresh_local_observation_drift_is_rejected(mutation: str) -> None:
    persisted = local_observations()
    fresh = copy.deepcopy(persisted)
    if mutation == "version":
        fresh["distributions"][0]["distribution_version"] = "0.0.31"  # type: ignore[index]
    elif mutation == "hash":
        fresh["adapter_sources"][0]["adapter_module_sha256"] = "d" * 64  # type: ignore[index]
    elif mutation == "repository_id":
        fresh["adapter_sources"][0]["repository_ids"] = []  # type: ignore[index]
    elif mutation == "exposure":
        fresh["adapter_sources"][0]["point_exposure"] = False  # type: ignore[index]
    else:
        cast(list[dict[str, object]], fresh["adapter_sources"]).pop()
    with pytest.raises(screening.ScreeningSchemaError):
        screening.validate_local_package_observations(
            persisted,
            repo_root=REPO_ROOT,
            fresh_observation=fresh,
        )


@pytest.mark.parametrize("value", [True, False, "maybe"])
def test_adapter_exposure_observation_requires_exact_unknown(value: object) -> None:
    observation = local_observations()
    observation["adapter_sources"][0]["point_exposure"] = value  # type: ignore[index]
    with pytest.raises(screening.ScreeningSchemaError, match="must be unknown"):
        screening.validate_local_package_observations(observation)


def test_unknown_observation_and_adapter_fact_validate_together() -> None:
    record = valid_record()
    validate_unit_record(record)


@pytest.mark.parametrize("mutation", ["package_version", "source_hash", "exposure"])
def test_variant_adapter_facts_are_bound_to_local_observations(mutation: str) -> None:
    record = valid_record()
    if mutation == "package_version":
        record["variant_records"][0]["applicable_installed_package_versions"]["value"][  # type: ignore[index]
            "timecopilot"
        ] = "0.0.29"
    elif mutation == "source_hash":
        record["source_registry"][LOCAL_SOURCE_ID]["sha256"] = "d" * 64  # type: ignore[index]
    else:
        record["variant_records"][0]["timecopilot_adapter"]["point"]["value"] = False  # type: ignore[index]
        record["variant_records"][0]["monthly_history_only_60x3_support"] = fact(False)  # type: ignore[index]
        record["variant_records"][0]["result"] = "ineligible"  # type: ignore[index]
        counts, eligible = screening.derive_eligible_projection(record["variant_records"])  # type: ignore[arg-type]
        record["derived_counts"] = counts
        record["eligible_variant_ids"] = eligible
    with pytest.raises(screening.ScreeningSchemaError):
        validate_unit_record(record)


def test_boolean_exposure_is_rejected_even_when_adapter_identity_is_unknown() -> None:
    variant = valid_variant()
    variant["timecopilot_adapter"]["artifact_identity"] = local_fact(  # type: ignore[index]
        "unknown", status="unknown"
    )
    variant["timecopilot_adapter"]["point"] = local_fact(False)  # type: ignore[index]
    variant["monthly_history_only_60x3_support"] = fact("unknown", status="unknown")
    variant["result"] = "unknown/ineligible"
    variant["unknowns"] = screening.canonical_unknown_fact_paths(variant)
    record = valid_record([variant])
    with pytest.raises(screening.ScreeningSchemaError, match="must have unknown status and value"):
        validate_unit_record(record)


def test_static_adapter_inspection_uses_distribution_files_without_imports(tmp_path: Path) -> None:
    package = tmp_path / "site" / "timecopilot" / "models" / "foundation"
    package.mkdir(parents=True)
    adapter = package / "chronos.py"
    adapter.write_text(
        'REPOSITORIES = ["vendor/model"]\n'
        'DOCS = "https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html"\n'
        "def forecast(level=None, quantiles=None):\n"
        "    return {\"mean\": 1.0, \"level\": level, \"quantiles\": quantiles}\n",
        encoding="utf-8",
    )

    class FakeDistribution:
        files = (importlib.metadata.PackagePath("timecopilot/models/foundation/chronos.py"),)
        version = "0.0.30"
        metadata = {"Name": "timecopilot"}

        def locate_file(self, path: object) -> Path:
            return tmp_path / "site" / str(path)

    before = {name for name in sys.modules if name == "timecopilot" or name.startswith("timecopilot.")}
    result = screening.inspect_timecopilot_adapter_source(
        FakeDistribution(), "timecopilot/models/foundation/chronos.py", observed_at=NOW  # type: ignore[arg-type]
    )
    after = {name for name in sys.modules if name == "timecopilot" or name.startswith("timecopilot.")}
    assert result["repository_ids"] == ["vendor/model"]
    assert result["point_exposure"] == "unknown"
    assert result["interval_exposure"] == "unknown"
    assert result["quantile_exposure"] == "unknown"
    assert result["exposure_rationale"] == screening.STATIC_EXPOSURE_UNKNOWN_RATIONALE
    assert after == before


def test_tabpfn_static_inspection_does_not_mistake_documentation_paths_for_model_ids(
    tmp_path: Path,
) -> None:
    package = tmp_path / "site" / "timecopilot" / "models" / "foundation"
    package.mkdir(parents=True)
    adapter = package / "tabpfn.py"
    adapter.write_text(
        'DOC = "https://github.com/PriorLabs/tabpfn-time-series/tree/main"\n',
        encoding="utf-8",
    )

    class FakeDistribution:
        files = (importlib.metadata.PackagePath("timecopilot/models/foundation/tabpfn.py"),)
        version = "0.0.30"
        metadata = {"Name": "timecopilot"}

        def locate_file(self, path: object) -> Path:
            return tmp_path / "site" / str(path)

    result = screening.inspect_timecopilot_adapter_source(
        FakeDistribution(), "timecopilot/models/foundation/tabpfn.py", observed_at=NOW  # type: ignore[arg-type]
    )
    assert result["repository_ids"] == []


def test_repository_id_extraction_uses_only_closed_semantic_symbol_names() -> None:
    tree = ast.parse(
        "repo_id = 'vendor/primary'\n"
        "repository_ids = ['vendor/secondary']\n"
        "model_ids = ['vendor/third']\n"
        "report = 'vendor/report'\n"
        "report_path = 'vendor/report-path'\n"
        "def helper():\n"
        "    consume(report_path='vendor/call-report')\n"
    )
    assert screening._semantic_repository_ids(tree) == [
        "vendor/primary",
        "vendor/secondary",
        "vendor/third",
    ]


def test_repository_id_extraction_pairs_destructuring_and_comparisons() -> None:
    tree = ast.parse(
        "repo_id, report_path = 'vendor/tuple-good', 'vendor/tuple-bad'\n"
        "if repo_id == 'vendor/compare-good': pass\n"
        "if repo_id == ('vendor/tuple-compare-a', 'vendor/tuple-compare-b'): pass\n"
        "if report_path == 'vendor/report-bad': pass\n"
    )
    assert screening._semantic_repository_ids(tree) == [
        "vendor/compare-good",
        "vendor/tuple-good",
    ]


def test_repository_id_extraction_pairs_only_exact_dict_keys_and_keywords() -> None:
    tree = ast.parse(
        "config = {'repo_id': 'vendor/mapping-good', 'report_path': 'vendor/mapping-bad'}\n"
        "consume(repository_id='vendor/keyword-good', report_path='vendor/keyword-bad')\n"
        "consume(repo_id={'other': 'vendor/keyword-sibling'})\n"
    )
    assert screening._semantic_repository_ids(tree) == [
        "vendor/keyword-good",
        "vendor/mapping-good",
    ]


def test_prose_only_adapter_terms_do_not_create_exposure_or_repository_facts(
    tmp_path: Path,
) -> None:
    package = tmp_path / "site" / "timecopilot" / "models" / "foundation"
    package.mkdir(parents=True)
    adapter = package / "chronos.py"
    adapter.write_text(
        'DOC = "forecast interval quantile vendor/prose-model"\n',
        encoding="utf-8",
    )

    class FakeDistribution:
        files = (importlib.metadata.PackagePath("timecopilot/models/foundation/chronos.py"),)
        version = "0.0.30"
        metadata = {"Name": "timecopilot"}

        def locate_file(self, path: object) -> Path:
            return tmp_path / "site" / str(path)

    result = screening.inspect_timecopilot_adapter_source(
        FakeDistribution(),  # type: ignore[arg-type]
        "timecopilot/models/foundation/chronos.py",
        observed_at=NOW,
    )
    assert result["repository_ids"] == []
    assert result["point_exposure"] == "unknown"
    assert result["interval_exposure"] == "unknown"
    assert result["quantile_exposure"] == "unknown"


def test_static_inspection_does_not_infer_exposure_from_function_signatures(
    tmp_path: Path,
) -> None:
    package = tmp_path / "site" / "timecopilot" / "models" / "foundation"
    package.mkdir(parents=True)
    adapter = package / "chronos.py"
    adapter.write_text(
        "def helper(level=None, quantiles=None):\n    return level, quantiles\n"
        "def forecast(level=None, quantiles=None):\n    return {\"point\": 1.0}\n",
        encoding="utf-8",
    )

    class FakeDistribution:
        files = (importlib.metadata.PackagePath("timecopilot/models/foundation/chronos.py"),)
        version = "0.0.30"
        metadata = {"Name": "timecopilot"}

        def locate_file(self, path: object) -> Path:
            return tmp_path / "site" / str(path)

    result = screening.inspect_timecopilot_adapter_source(
        FakeDistribution(),  # type: ignore[arg-type]
        "timecopilot/models/foundation/chronos.py",
        observed_at=NOW,
    )
    assert result["point_exposure"] == "unknown"
    assert result["interval_exposure"] == "unknown"
    assert result["quantile_exposure"] == "unknown"


def test_static_inspection_does_not_infer_exposure_from_return_shape(tmp_path: Path) -> None:
    package = tmp_path / "site" / "timecopilot" / "models" / "foundation"
    package.mkdir(parents=True)
    adapter = package / "chronos.py"
    adapter.write_text(
        "def forecast():\n    return {\"intervals\": [(0.0, 1.0)]}\n",
        encoding="utf-8",
    )

    class FakeDistribution:
        files = (importlib.metadata.PackagePath("timecopilot/models/foundation/chronos.py"),)
        version = "0.0.30"
        metadata = {"Name": "timecopilot"}

        def locate_file(self, path: object) -> Path:
            return tmp_path / "site" / str(path)

    result = screening.inspect_timecopilot_adapter_source(
        FakeDistribution(),  # type: ignore[arg-type]
        "timecopilot/models/foundation/chronos.py",
        observed_at=NOW,
    )
    assert result["point_exposure"] == "unknown"
    assert result["interval_exposure"] == "unknown"
    assert result["quantile_exposure"] == "unknown"


def test_static_inspection_does_not_infer_exposure_from_function_bodies(
    tmp_path: Path,
) -> None:
    package = tmp_path / "site" / "timecopilot" / "models" / "foundation"
    package.mkdir(parents=True)
    adapter = package / "chronos.py"
    adapter.write_text(
        "def forecast():\n    point_mean = 1.0\n    return {\"mean\": point_mean}\n"
        "def _predict_debug():\n    return {\"quantiles\": [0.5]}\n",
        encoding="utf-8",
    )

    class FakeDistribution:
        files = (importlib.metadata.PackagePath("timecopilot/models/foundation/chronos.py"),)
        version = "0.0.30"
        metadata = {"Name": "timecopilot"}

        def locate_file(self, path: object) -> Path:
            return tmp_path / "site" / str(path)

    result = screening.inspect_timecopilot_adapter_source(
        FakeDistribution(),  # type: ignore[arg-type]
        "timecopilot/models/foundation/chronos.py",
        observed_at=NOW,
    )
    assert result["point_exposure"] == "unknown"
    assert result["quantile_exposure"] == "unknown"


def test_exposure_inference_engine_is_deleted() -> None:
    assert not hasattr(screening, "_forecast_output_exposures")


def test_static_moirai_inspection_includes_installed_gluonts_base(tmp_path: Path) -> None:
    foundation = tmp_path / "site" / "timecopilot" / "models" / "foundation"
    utilities = tmp_path / "site" / "timecopilot" / "models" / "utils"
    foundation.mkdir(parents=True)
    utilities.mkdir(parents=True)
    (foundation / "moirai.py").write_text(
        'class GluonTSForecaster: ...\n'
        'REPO_ID = "Salesforce/moirai-1.0-R-large"\n'
        'class Moirai(GluonTSForecaster): ...\n',
        encoding="utf-8",
    )
    (utilities / "gluonts_forecaster.py").write_text(
        "def forecast(level=None, quantiles=None):\n    return level, quantiles\n",
        encoding="utf-8",
    )

    class FakeDistribution:
        files = (
            importlib.metadata.PackagePath("timecopilot/models/foundation/moirai.py"),
            importlib.metadata.PackagePath("timecopilot/models/utils/gluonts_forecaster.py"),
        )
        version = "0.0.30"
        metadata = {"Name": "timecopilot"}

        def locate_file(self, path: object) -> Path:
            return tmp_path / "site" / str(path)

    result = screening.inspect_timecopilot_adapter_source(
        FakeDistribution(),  # type: ignore[arg-type]
        "timecopilot/models/foundation/moirai.py",
        observed_at=NOW,
    )
    assert result["repository_ids"] == ["Salesforce/moirai-1.0-R-large"]
    assert result["interval_exposure"] == "unknown"
    assert result["quantile_exposure"] == "unknown"
    assert result["supporting_sources"][0]["stable_locator"].endswith(
        "models/utils/gluonts_forecaster.py"
    )


def test_cli_requires_absolute_repo_root() -> None:
    assert screening.main(["validate", "--repo-root", "relative"]) == 1
    parsed = screening._parser().parse_args(
        ["check-roadmap", "--repo-root", str(REPO_ROOT), "--expect", "planned", "--require-update-eligible"]
    )
    assert parsed.command == "check-roadmap"
    assert parsed.require_update_eligible is True


def _planned_roadmap_text() -> str:
    current = (REPO_ROOT / screening.ROADMAP_RELATIVE_PATH).read_text(encoding="utf-8")
    planned = current.replace("- [x] **P1-03", "- [ ] **P1-03", 1)
    assert hashlib.sha256(planned.encode("utf-8")).hexdigest() == screening.ROADMAP_PLANNED_SHA256
    return planned


def test_roadmap_guard_accepts_only_planned_to_complete_p103_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roadmap = tmp_path / screening.ROADMAP_RELATIVE_PATH
    roadmap.parent.mkdir(parents=True)
    monkeypatch.setattr(
        screening,
        "validate_published_state",
        lambda _: {"overall_classification": "pass"},
    )
    planned = _planned_roadmap_text()
    roadmap.write_text(planned, encoding="utf-8")
    screening.validate_roadmap_consistency(
        tmp_path, expect="planned", require_update_eligible=True
    )
    roadmap.write_text(
        planned.replace("- [ ] **P1-03", "- [x] **P1-03", 1),
        encoding="utf-8",
    )
    screening.validate_roadmap_consistency(tmp_path, expect="complete")


def test_roadmap_guard_rejects_unauthorized_edit_and_wrong_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roadmap = tmp_path / screening.ROADMAP_RELATIVE_PATH
    roadmap.parent.mkdir(parents=True)
    monkeypatch.setattr(
        screening,
        "validate_published_state",
        lambda _: {"overall_classification": "pass"},
    )
    planned = _planned_roadmap_text()
    roadmap.write_text(planned.replace("Execution plan:", "Changed execution plan:"), encoding="utf-8")
    with pytest.raises(screening.RoadmapConsistencyError, match="outside the authorized"):
        screening.validate_roadmap_consistency(tmp_path, expect="planned")
    roadmap.write_text(planned, encoding="utf-8")
    with pytest.raises(screening.RoadmapConsistencyError, match="not complete"):
        screening.validate_roadmap_consistency(tmp_path, expect="complete")


def test_schema_and_static_inspection_never_use_network_models_or_gpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_: object, **__: object) -> object:
        raise AssertionError("forbidden external/runtime operation")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    before = {
        name
        for name in sys.modules
        if name == "torch" or name.startswith(("torch.", "transformers.", "timecopilot."))
    }
    validate_unit_record(valid_record())
    assert screening.classify_variant_record(valid_variant()) == "unknown/ineligible"
    after = {
        name
        for name in sys.modules
        if name == "torch" or name.startswith(("torch.", "transformers.", "timecopilot."))
    }
    assert after == before
