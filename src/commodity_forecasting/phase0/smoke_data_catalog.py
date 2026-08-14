"""SM-05 initial monthly Arabica metadata catalog assembly."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import CATALOG_REQUIRED_FIELDS
from .evidence import utc_timestamp, write_evidence
from .fixtures import FIXTURE_ID
from .paths import phase0_evidence_dir, phase0_findings_dir, repo_root
from .smoke_datasources import PINK_SHEET_DATASET_ID, datasource_candidates

RAW_PAYLOAD_KEYS = {"data", "observations", "prices", "rows", "values"}


def build_catalog() -> list[dict[str, Any]]:
    entries = []
    for candidate in datasource_candidates():
        candidate_id = candidate["candidate_id"]
        is_selected_source = candidate_id == PINK_SHEET_DATASET_ID
        is_deferred_target_candidate = (
            candidate["continuous_series_kind"]
            in {"provider_continuous_front_month", "raw_contracts_for_later_construction", "unknown"}
        )
        read_outcome = candidate["programmatic_read"].get("outcome", "unknown")
        entries.append(
            {
                "dataset_id": candidate_id,
                "category": (
                    "target"
                    if is_selected_source
                    else "deferred_futures_or_api_candidate"
                    if is_deferred_target_candidate
                    else "supporting_covariate_candidate"
                ),
                "name": f"{candidate['provider']} data source",
                "source_provider": candidate["provider"],
                "source_locator": candidate["source_locator"],
                "access_method": candidate["access_method"],
                "native_frequency": candidate["native_frequency"],
                "fields": candidate["required_fields"],
                "programmatic_access": candidate["programmatic_access"],
                "auth_required": candidate["credential_requirement"],
                "status": (
                    "selected_static_source"
                    if is_selected_source
                    else "future_work_deferred"
                    if is_deferred_target_candidate
                    else "supporting_read_proven"
                    if read_outcome == "success"
                    else "supporting_access_unproven"
                ),
                "history_start": candidate["history_start"],
                "history_end": candidate["history_end"],
                "unit": "$/kg" if is_selected_source else "US cents per pound" if candidate_id.startswith("ice_") else "unknown",
                "availability_rule": (
                    "monthly observations are usable only after workbook publication; historical release timestamps are not embedded"
                    if is_selected_source
                    else "provider entitlement or publication timing unknown"
                ),
                "revision_behavior": "unknown",
                "roll_methodology": candidate["roll_methodology"],
                "license_or_usage_note": candidate["usage_limits"],
                "continuous_series_kind": candidate["continuous_series_kind"],
                "raw_path": candidate["local_raw_path"],
                "standardized_path": candidate["local_standardized_path"],
                "model_ready_path": f"data/model_ready/{candidate_id}/",
                "metadata_evidence": "docs/findings/phase0/evidence/datasource_metadata.json",
                "notes": candidate["metadata_probe"],
            }
        )
    return entries


def validate_catalog(entries: list[dict[str, Any]]) -> None:
    if len(entries) < 3:
        raise ValueError("catalog must represent the primary, fallback, and supporting candidate")
    for entry in entries:
        missing = [field for field in CATALOG_REQUIRED_FIELDS if field not in entry]
        if missing:
            raise ValueError(f"{entry.get('dataset_id', 'unknown')} missing: {', '.join(missing)}")
        if RAW_PAYLOAD_KEYS.intersection(entry):
            raise ValueError(f"{entry['dataset_id']} contains a raw-provider payload key")
        paths = {entry["raw_path"], entry["standardized_path"], entry["model_ready_path"]}
        if len(paths) != 3:
            raise ValueError(f"{entry['dataset_id']} does not separate data layers")


def run_probe(*, root: Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    active_root = root or repo_root()
    entries = build_catalog()
    validate_catalog(entries)
    serialized = json.dumps(entries, indent=2, sort_keys=True) + "\n"
    catalog_path = active_root / "data/catalog/phase0/world_bank_arabica_catalog.json"
    evidence_path = phase0_evidence_dir(active_root) / "data_catalog.json"
    finding_path = phase0_findings_dir(active_root) / "data_catalog.md"
    record = {
        "run_id": f"SM-05-{utc_timestamp()}",
        "test_id": "SM-05",
        "work_item": "initial monthly Arabica data catalog assembly",
        "timestamp_utc": utc_timestamp(),
        "mode": "offline-unit",
        "command": ".venv/bin/python -m pytest tests/smoke/test_data_catalog.py",
        "tool": "catalog schema validator",
        "timecopilot_version": "not_applicable",
        "model_or_adapter": "not_applicable",
        "fixture_id": FIXTURE_ID,
        "data_origin": "verified SM-04 selected workbook metadata only",
        "credential_state": "not_required",
        "network_state": "not_required",
        "observed_result": "An initial monthly Arabica catalog was assembled from SM-04 metadata. The selected World Bank Pink Sheet workbook is the active target source, and futures/API candidates remain deferred future work.",
        "classification": "pass",
        "leakage_controls": [
            "catalog contains metadata only and rejects raw payload keys",
            "raw, standardized, and model-ready paths are distinct",
            "unverified source behavior remains unknown",
        ],
        "artifact_paths": [str(catalog_path), str(evidence_path), str(finding_path)],
        "catalog_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "entry_count": len(entries),
        "dataset_ids": [entry["dataset_id"] for entry in entries],
        "required_catalog_fields": list(CATALOG_REQUIRED_FIELDS),
        "source_evidence": "docs/findings/phase0/evidence/datasource_metadata.json",
        "selected_dataset_id": PINK_SHEET_DATASET_ID,
    }
    return record, entries


def write_outputs(record: dict[str, Any], entries: list[dict[str, Any]], *, root: Path | None = None) -> None:
    active_root = root or repo_root()
    catalog_path = active_root / "data/catalog/phase0/world_bank_arabica_catalog.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_evidence(phase0_evidence_dir(active_root) / "data_catalog.json", record)
    finding_path = phase0_findings_dir(active_root) / "data_catalog.md"
    finding_path.write_text(
        "\n".join(
            [
                "# Phase 0 Initial Data Catalog",
                "",
                f"- Classification: `{record['classification']}`",
                f"- Entries: `{record['entry_count']}`",
                f"- SHA-256: `{record['catalog_sha256']}`",
                f"- Dataset IDs: `{', '.join(record['dataset_ids'])}`",
                "",
                str(record["observed_result"]),
                "",
                "No raw provider observations or derived features are present. Unknown metadata remains explicit.",
                "",
                "Catalog: `data/catalog/phase0/world_bank_arabica_catalog.json`",
                "Evidence: `docs/findings/phase0/evidence/data_catalog.json`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    record, entries = run_probe()
    write_outputs(record, entries)
    print(f"SM-05 {record['classification']}: {record['observed_result']}")
    return 0 if record["classification"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
