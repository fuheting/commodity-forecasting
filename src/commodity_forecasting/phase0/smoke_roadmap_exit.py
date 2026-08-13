"""SM-07 evidence-backed roadmap and Phase 0 exit audit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence import utc_timestamp, validate_evidence_record, write_evidence
from .fixtures import FIXTURE_ID
from .paths import phase0_evidence_dir, phase0_findings_dir, repo_root

REQUIRED_EVIDENCE = [
    "covariate_support.json",
    "probabilistic_adapters.json",
    "natural_language.json",
    "datasource_selection.json",
    "datasource_metadata.json",
    "data_catalog.json",
    "decision_rollup.json",
]


def run_audit(*, root: Path | None = None) -> dict[str, Any]:
    active_root = root or repo_root()
    roadmap = (active_root / "docs/roadmap.md").read_text(encoding="utf-8")
    phase0 = roadmap.split("## Phase 0:", 1)[1].split("## Phase 1:", 1)[0]
    phase0_tasks = [line for line in phase0.splitlines() if line.startswith("- [")]
    evidence_dir = phase0_evidence_dir(active_root)
    records = {}
    for filename in REQUIRED_EVIDENCE:
        path = evidence_dir / filename
        if not path.exists():
            raise ValueError(f"missing required evidence: {path}")
        record = json.loads(path.read_text(encoding="utf-8"))
        validate_evidence_record(record)
        records[filename] = record

    checks = {
        "all_phase0_tasks_checked": bool(phase0_tasks) and all(line.startswith("- [x]") for line in phase0_tasks),
        "all_checked_tasks_cite_evidence": all(
            "Evidence:" in line for line in phase0_tasks if line.startswith("- [x]")
        ),
        "all_required_records_pass": all(record["classification"] == "pass" for record in records.values()),
        "covariate_gap_roadmapped": (
            records["covariate_support.json"]["gate_result"] == "adapter_gap_proven"
            and "compatible T0 adapter path" in roadmap
        ),
        "catalog_exists": (active_root / "data/catalog/phase0/world_bank_arabica_catalog.json").exists(),
        "monthly_contract_recorded": all(
            text in roadmap for text in ("Coffee, Arabica", "60-month", "3-month")
        ),
        "unknowns_preserved": bool(records["decision_rollup.json"]["unknowns"]),
    }
    classification = "pass" if all(checks.values()) else "blocked"
    finding_path = phase0_findings_dir(active_root) / "roadmap_exit.md"
    evidence_path = evidence_dir / "roadmap_exit.json"
    return {
        "run_id": f"SM-07-{utc_timestamp()}",
        "test_id": "SM-07",
        "work_item": "evidence-backed roadmap update and Phase 0 exit audit",
        "timestamp_utc": utc_timestamp(),
        "mode": "offline-unit",
        "command": ".venv/bin/python -m pytest tests/smoke/test_roadmap_exit.py",
        "tool": "roadmap/evidence exit auditor",
        "timecopilot_version": records["covariate_support.json"]["timecopilot_version"],
        "model_or_adapter": "Phase 0 aggregate",
        "fixture_id": FIXTURE_ID,
        "data_origin": "roadmap and SM-01 through SM-06 evidence",
        "credential_state": "not_required",
        "network_state": "not_required",
        "observed_result": "All Phase 0 roadmap tasks are checked with evidence links and every required exit artifact validates." if classification == "pass" else f"Phase 0 exit remains blocked by unmet prerequisite gates: {checks}",
        "classification": classification,
        "leakage_controls": [
            "roadmap completion is derived from accepted evidence artifacts",
            "covariate adapter gap requires explicit downstream roadmap work",
            "unknowns and real-data validation limits remain open",
        ],
        "artifact_paths": [str(active_root / "docs/roadmap.md"), str(evidence_path), str(finding_path)],
        "checks": checks,
        "phase0_task_count": len(phase0_tasks),
        "required_evidence": [f"docs/findings/phase0/evidence/{name}" for name in REQUIRED_EVIDENCE],
    }


def write_outputs(record: dict[str, Any], *, root: Path | None = None) -> None:
    active_root = root or repo_root()
    write_evidence(phase0_evidence_dir(active_root) / "roadmap_exit.json", record)
    phase0_findings_dir(active_root).joinpath("roadmap_exit.md").write_text(
        "\n".join(
            [
                "# Phase 0 Roadmap Exit Audit",
                "",
                f"- Classification: `{record['classification']}`",
                f"- Phase 0 tasks checked: `{record['phase0_task_count']}`",
                "",
                *[f"- `{name}`: `{value}`" for name, value in record["checks"].items()],
                "",
                str(record["observed_result"]),
                "",
                "Evidence: `docs/findings/phase0/evidence/roadmap_exit.json`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    record = run_audit()
    write_outputs(record)
    print(f"SM-07 {record['classification']}: {record['observed_result']}")
    return 0 if record["classification"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
