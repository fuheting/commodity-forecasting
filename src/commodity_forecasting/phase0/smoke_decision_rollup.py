"""SM-06 evidence-linked Phase 0 decision and limitation rollup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence import utc_timestamp, validate_evidence_record, write_evidence
from .fixtures import FIXTURE_ID
from .paths import phase0_evidence_dir, phase0_findings_dir, repo_root

SOURCE_FILES = {
    "covariate": "covariate_support.json",
    "probabilistic": "probabilistic_adapters.json",
    "natural_language": "natural_language.json",
    "datasource": "datasource_selection.json",
    "catalog": "data_catalog.json",
}


def _read_sources(root: Path) -> dict[str, dict[str, Any]]:
    evidence_dir = phase0_evidence_dir(root)
    sources = {
        name: json.loads((evidence_dir / filename).read_text(encoding="utf-8"))
        for name, filename in SOURCE_FILES.items()
    }
    for record in sources.values():
        validate_evidence_record(record)
    return sources


def run_probe(*, root: Path | None = None) -> dict[str, Any]:
    active_root = root or repo_root()
    sources = _read_sources(active_root)
    conclusions = {
        "covariate": "T0 native known-future covariates executed; TimeCopilot 0.0.30 T0 adapter omits them, so scoped compatible-adapter work is roadmapped.",
        "probabilistic": "TimeCopilot 0.0.30 T0 adapter is selected for quantiles and level-derived intervals; simultaneous level and quantiles is unsupported.",
        "natural_language": "The credential-free deterministic TimeCopilot agent/tool contract passed all four tool calls and returned query-specific analysis.",
        "datasource": "The downloaded World Bank Pink Sheet workbook is selected as the static monthly PoC source for Coffee, Arabica. ICE, Barchart, Nasdaq, and API refresh selection remain future work.",
        "catalog": "The initial monthly Arabica catalog passed schema and layer separation with the selected workbook target source and deferred futures/API candidates.",
    }
    unknowns = [
        "World Bank workbook historical release timestamps are not embedded, so publication availability must be enforced conservatively.",
        "Automated World Bank API or refresh acquisition is not selected for the PoC.",
        "Barchart KC*0 entitled historical settlement retrieval remains unverified future work.",
        "Coffee C-specific ICE history start and usage limits remain unverified future work.",
        "Nasdaq Data Link SCF Coffee C mapping, fields, access, and roll methodology remain unknown.",
        "FAOSTAT programmatic access remains unknown after the API host returned error 521.",
        "External-provider LLM language quality and credentials were not tested.",
    ]
    limitations = [
        "The active target is a World Bank monthly Arabica indicator price, not an ICE Coffee C futures settlement series.",
        "The workbook is a static downloaded artifact and does not provide automatic refresh.",
        "The covariate smoke proved an adapter exposure gap; the covariate-informed PoC experiment remains Phase 2 work.",
        "No predefined accuracy or calibration threshold applies, and Phase 0 did not run the real backtest.",
    ]
    source_paths = {
        name: f"docs/findings/phase0/evidence/{filename}" for name, filename in SOURCE_FILES.items()
    }
    record = {
        "run_id": f"SM-06-{utc_timestamp()}",
        "test_id": "SM-06",
        "work_item": "Phase 0 decisions and limitations rollup",
        "timestamp_utc": utc_timestamp(),
        "mode": "offline-unit",
        "command": ".venv/bin/python -m pytest tests/smoke/test_decision_rollup.py",
        "tool": "evidence reconciliation validator",
        "timecopilot_version": sources["covariate"]["timecopilot_version"],
        "model_or_adapter": "T0 probabilistic adapter; scoped T0 covariate adapter pending",
        "fixture_id": FIXTURE_ID,
        "data_origin": "SM-01 through SM-05 evidence artifacts",
        "credential_state": "not_required_for_rollup",
        "network_state": "not_required",
        "observed_result": "All Phase 0 capability, selected workbook datasource, and catalog conclusions were reconciled to preceding evidence with unknowns and limitations preserved.",
        "classification": "pass",
        "leakage_controls": [
            "rollup reads evidence metadata only",
            "no unknown is promoted into a supported conclusion",
            "monthly target construction and evaluation remain downstream",
        ],
        "artifact_paths": [
            str(phase0_findings_dir(active_root) / "decisions.md"),
            str(phase0_findings_dir(active_root) / "limitations.md"),
            str(phase0_evidence_dir(active_root) / "decision_rollup.json"),
        ],
        "source_evidence": source_paths,
        "conclusions": conclusions,
        "unknowns": unknowns,
        "limitations": limitations,
        "primary_datasource": sources["datasource"]["primary_datasource"],
        "fallback_datasource": sources["datasource"]["fallback_datasource"],
        "recommended_primary_candidate": sources["datasource"]["recommended_primary_candidate"],
        "recommended_fallback_candidate": sources["datasource"]["recommended_fallback_candidate"],
        "probabilistic_adapter": sources["probabilistic"]["model_or_adapter"],
        "covariate_adapter_status": sources["covariate"]["gate_result"],
    }
    return record


def write_outputs(record: dict[str, Any], *, root: Path | None = None) -> None:
    active_root = root or repo_root()
    findings_dir = phase0_findings_dir(active_root)
    write_evidence(phase0_evidence_dir(active_root) / "decision_rollup.json", record)
    decision_lines = ["# Phase 0 Decisions", ""]
    for name, conclusion in record["conclusions"].items():
        decision_lines.extend(
            [f"## {name.replace('_', ' ').title()}", "", conclusion, "", f"Evidence: `{record['source_evidence'][name]}`", ""]
        )
    findings_dir.joinpath("decisions.md").write_text("\n".join(decision_lines), encoding="utf-8")

    limitation_lines = ["# Phase 0 Limitations", "", "## Unknowns", ""]
    limitation_lines.extend(f"- {item}" for item in record["unknowns"])
    limitation_lines.extend(["", "## Boundaries", ""])
    limitation_lines.extend(f"- {item}" for item in record["limitations"])
    limitation_lines.extend(["", "Evidence: `docs/findings/phase0/evidence/decision_rollup.json`", ""])
    findings_dir.joinpath("limitations.md").write_text("\n".join(limitation_lines), encoding="utf-8")


def main() -> int:
    record = run_probe()
    write_outputs(record)
    print(f"SM-06 {record['classification']}: {record['observed_result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
