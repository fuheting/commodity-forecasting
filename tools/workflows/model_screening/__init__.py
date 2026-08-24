"""Conservative, documentation-only feasibility screening for Phase 1.

This package coordinates validation, static local observation, and publication
without importing forecasting packages, contacting model hubs, or executing models.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .. import target_publication as target_pipeline
from . import publication as _publication
from .observer import (
    ADAPTER_MANIFEST,
    INSTALLED_DISTRIBUTIONS,
    STATIC_EXPOSURE_UNKNOWN_RATIONALE,
    ScreeningError,
    _semantic_repository_ids,
    inspect_timecopilot_adapter_source,
    observe_local_packages,
)
from .publication import (
    EVIDENCE_RELATIVE_PATH,
    FINDING_RELATIVE_PATH,
    ROADMAP_RELATIVE_PATH,
    PublicationError,
    RoadmapConsistencyError,
)
from .schema import (
    ADAPTER_FIELDS,
    AUTH_STATUSES,
    BASE_SOURCE_FIELDS,
    COLD_START_STATUSES,
    DEVICE_STATUSES,
    DISPOSITIONS,
    EXECUTION_CATALOG_CAPTURED_AT_UTC,
    FACT_STATUSES,
    FROZEN_INVENTORY_BASELINE,
    FROZEN_INVENTORY_BASELINE_SHA256,
    INVENTORY_BASELINE_RELATIVE_PATH,
    INVENTORY_SOURCE_FIELDS,
    INVENTORY_SOURCE_STABLE_LOCATOR,
    INVENTORY_SOURCE_VERSION_OR_DATE,
    LICENSE_STATUSES,
    LOCAL_SOURCE_FIELDS,
    MODEL_NATIVE_FIELDS,
    OFFICIAL_SOURCE_FIELDS,
    OFFICIAL_SOURCE_KINDS,
    OFFLINE_STATUSES,
    OVERALL_CLASSIFICATIONS,
    P1_02_EVIDENCE_RELATIVE_PATH,
    PINNED_LOCAL_LOCATORS,
    PINNED_LOCAL_SOURCE_BY_FAMILY,
    PINNED_EXECUTION_CATALOG,
    PINNED_EXECUTION_CATALOG_SHA256,
    POC_USE_STATUSES,
    PROBABILISTIC_FIELDS,
    REQUIRED_TOP_LEVEL_FIELDS,
    REQUIRED_VARIANT_FIELDS,
    REQUIRED_CHECK_KEYS,
    RESULTS,
    SCHEMA_VERSION,
    SOURCE_KINDS,
    TARGET_GPU_GB,
    TASK_ID,
    UTC_PATTERN,
    InventoryError,
    ScreeningSchemaError,
    _timestamp,
    _utc_now,
    build_inventory_witnesses,
    canonical_unknown_fact_paths,
    classify_variant_record,
    derive_eligible_projection,
    derive_monthly_history_only_60x3,
    frozen_inventory_snapshot,
    load_inventory_baseline,
    load_source_registry,
    pinned_catalog_snapshot,
    sha256_file,
    validate_embedded_manifests,
    validate_execution_official_catalog,
    validate_inventory_closure,
    validate_local_package_observations,
    validate_official_catalog_snapshot,
    validate_screening_record,
    validate_source_registry,
    validate_variant_oracle_bindings,
    validate_variant_provenance,
)

render_markdown_report = _publication.render_markdown_report
_load_record = _publication._load_record
_refresh_derived = _publication._refresh_derived
_refresh_local_source_registry = _publication._refresh_local_source_registry


def validate_p1_02_binding(repo_root: Path, record: dict[str, Any] | None = None) -> str:
    """Validate P1-02 first, then return/check the exact canonical evidence hash."""

    root = repo_root.resolve()
    target_pipeline.validate_published_state(root)
    path = root / P1_02_EVIDENCE_RELATIVE_PATH
    digest = sha256_file(path)
    if record is not None:
        if record.get("p1_02_evidence_path") != P1_02_EVIDENCE_RELATIVE_PATH.as_posix():
            raise ScreeningSchemaError("P1-02 binding path mismatch")
        if record.get("p1_02_evidence_sha256") != digest:
            raise ScreeningSchemaError("P1-02 binding hash mismatch")
    return digest


def publish_screening_artifacts(
    repo_root: Path,
    record: dict[str, Any],
    *,
    replace_file: _publication.ReplaceFile = _publication._replace_file,
) -> None:
    _publication.publish_screening_artifacts(
        repo_root,
        record,
        replace_file=replace_file,
        validate_record=validate_screening_record,
    )


def publish(repo_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Refresh local/binding/derived fields of an externally curated ledger and publish it."""

    root = repo_root.resolve()
    record = _load_record(root / EVIDENCE_RELATIVE_PATH)
    validate_p1_02_binding(root, record)
    validate_screening_record(record)
    publication_time = now or _utc_now()
    record["local_package_observations"] = observe_local_packages(
        root, observed_at=publication_time
    )
    _refresh_local_source_registry(record, record["local_package_observations"])
    record["generated_at_utc"] = _timestamp(publication_time)
    _refresh_derived(record)
    publish_screening_artifacts(root, record)
    validate_published_state(root)
    return record


def validate_published_state(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    record = _load_record(root / EVIDENCE_RELATIVE_PATH)
    validate_screening_record(record, repo_root=root)
    validate_p1_02_binding(root, record)
    finding = root / FINDING_RELATIVE_PATH
    if not finding.is_file() or finding.read_text(encoding="utf-8") != render_markdown_report(record):
        raise ScreeningSchemaError("screening Markdown does not match canonical JSON")
    return record


def validate(repo_root: Path) -> dict[str, Any]:
    return validate_published_state(repo_root)


def validate_roadmap_consistency(
    repo_root: Path,
    *,
    expect: str,
    require_update_eligible: bool = False,
) -> None:
    _publication.validate_roadmap_consistency(
        repo_root,
        expect=expect,
        require_update_eligible=require_update_eligible,
        validate_published=validate_published_state,
    )


def check_roadmap(repo_root: Path, *, expect: str, require_update_eligible: bool = False) -> None:
    validate_roadmap_consistency(
        repo_root, expect=expect, require_update_eligible=require_update_eligible
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("publish", "validate"):
        item = subparsers.add_parser(command)
        item.add_argument("--repo-root", type=Path, required=True)
    roadmap = subparsers.add_parser("check-roadmap")
    roadmap.add_argument("--repo-root", type=Path, required=True)
    roadmap.add_argument("--expect", choices=("planned", "complete"), required=True)
    roadmap.add_argument("--require-update-eligible", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.repo_root.is_absolute():
        print("--repo-root must be an absolute path", file=sys.stderr)
        return 1
    try:
        if arguments.command == "publish":
            result = publish(arguments.repo_root)
            print(json.dumps(result, sort_keys=True))
        elif arguments.command == "validate":
            result = validate(arguments.repo_root)
            print(json.dumps(result, sort_keys=True))
        else:
            check_roadmap(
                arguments.repo_root,
                expect=arguments.expect,
                require_update_eligible=arguments.require_update_eligible,
            )
    except (ScreeningError, target_pipeline.TargetPipelineError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
