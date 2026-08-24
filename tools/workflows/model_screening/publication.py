"""Deterministic evidence rendering, artifact publication, and roadmap checks."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from .observer import ScreeningError
from .schema import (
    ScreeningSchemaError,
    classify_variant_record,
    derive_eligible_projection,
    derive_monthly_history_only_60x3,
    validate_screening_record,
)

FINDING_RELATIVE_PATH = Path("docs/findings/phase1/model_screening.md")
EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/model_screening.json")
ROADMAP_RELATIVE_PATH = Path("docs/roadmap.md")
P1_03_ROADMAP_PLANNED_LINE = (
    "- [ ] **P1-03 — Official-document edge-feasibility screen.** Depends on P1-02. "
    "Screen every documented local-capable Time Series Foundation Model family at the "
    "artifact-variant level against official evidence and the recorded 16 GB GPU target; "
    "required unknowns are not eligible. Evidence: "
    "`docs/findings/phase1/model_screening.md` and "
    "`docs/findings/phase1/evidence/model_screening.json`."
)
P1_03_ROADMAP_PATTERN = re.compile(r"(?m)^- \[([ x-])\] \*\*P1-03\b.*$")
P1_03_ROADMAP_LINE_PATTERN = re.compile(r"(?m)^- \[[ x-]\] \*\*P1-03\b.*$")


class PublicationError(ScreeningError):
    """Raised when screening artifacts cannot be safely published."""


class RoadmapConsistencyError(ScreeningError):
    """Raised when evidence does not authorize the requested roadmap state."""

def render_markdown_report(record: dict[str, Any]) -> str:
    """Render deterministic human-readable output from canonical JSON only."""

    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    rows = "\n".join(
        "| "
        f"`{cell(item['family'])}` | `{cell(item['canonical_variant_id'])}` | "
        f"`{cell(item['result'])}` | "
        f"<{cell(item['official_source_url']['value'])}>; "
        f"version `{cell(item['source_version_or_date']['value'])}`; "
        f"retrieved `{cell(item['retrieved_at_utc']['value'])}` | "
        f"{cell(', '.join(item['unknowns']) or 'None')} | "
        f"{cell('<br>'.join(str(note) for note in item['notes']) or 'None')} |"
        for item in record["variant_records"]
    )
    counts = "\n".join(
        f"- `{result}`: {count}" for result, count in sorted(record["derived_counts"].items())
    )
    eligible = "\n".join(f"- `{identifier}`" for identifier in record["eligible_variant_ids"]) or "- None"
    errors = "\n".join(f"- {error}" for error in record["errors"]) or "- None"
    return (
        "# Phase 1 Model Screening\n\n"
        f"- Run ID: `{record['run_id']}`\n"
        f"- Overall classification: `{record['overall_classification']}`\n"
        f"- Target GPU: `{record['target_gpu']['memory_gb']} GB {record['target_gpu']['device']}`\n"
        f"- P1-02 evidence SHA-256: `{record['p1_02_evidence_sha256']}`\n\n"
        "## Variant results\n\n"
        "| Family | Variant | Result | Official source anchor | Exact unknown facts | Notes / exclusion reason |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"{rows}\n\n## Result counts\n\n{counts}\n\n"
        f"## Eligible variants\n\n{eligible}\n\n## Errors\n\n{errors}\n\n"
        "Machine-readable evidence: `docs/findings/phase1/evidence/model_screening.json`\n"
    )


ReplaceFile = Callable[[Path, Path], None]


def _replace_file(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _stage(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def publish_screening_artifacts(
    repo_root: Path,
    record: dict[str, Any],
    *,
    replace_file: ReplaceFile = _replace_file,
    validate_record: Callable[..., None] = validate_screening_record,
) -> None:
    """Publish Markdown first and canonical JSON last; never write the roadmap."""

    root = repo_root.resolve()
    validate_record(
        record,
        repo_root=root,
    )
    if record["overall_classification"] != "pass":
        raise PublicationError("only overall-pass screening evidence may be published")
    markdown_bytes = render_markdown_report(record).encode("utf-8")
    json_bytes = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if json.loads(json_bytes) != record:
        raise PublicationError("canonical JSON does not round-trip")
    staged: list[tuple[Path, Path]] = []
    try:
        for destination, content in (
            (root / FINDING_RELATIVE_PATH, markdown_bytes),
            (root / EVIDENCE_RELATIVE_PATH, json_bytes),
        ):
            staged.append((_stage(destination, content), destination))
        for temporary, destination in staged:
            replace_file(temporary, destination)
    except OSError as exc:
        raise PublicationError(f"screening publication failed: {exc}") from exc
    finally:
        for temporary, _ in staged:
            if temporary.exists():
                temporary.unlink()


def _load_record(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScreeningSchemaError(f"canonical screening ledger is unavailable: {exc}") from exc
    if not isinstance(value, dict):
        raise ScreeningSchemaError("canonical screening ledger must be an object")
    return value


def _refresh_derived(record: dict[str, Any]) -> None:
    for variant in record["variant_records"]:
        support = derive_monthly_history_only_60x3(variant)
        summary = variant["monthly_history_only_60x3_support"]
        summary["status"] = "known" if support is not None else "unknown"
        summary["value"] = support if support is not None else "unknown"
        variant["result"] = classify_variant_record(variant)
    counts, eligible = derive_eligible_projection(record["variant_records"])
    record["derived_counts"] = counts
    record["eligible_variant_ids"] = eligible
    if any(variant["result"] == "blocked" for variant in record["variant_records"]):
        record["overall_classification"] = "blocked"


def _refresh_local_source_registry(
    record: dict[str, Any], observation: Mapping[str, Any]
) -> None:
    observed_by_locator = {
        item["stable_locator"]: item for item in observation["adapter_sources"]
    }
    for source in record["source_registry"].values():
        if source.get("source_kind") != "observed_local_package_source":
            continue
        observed = observed_by_locator.get(source.get("stable_locator"))
        if observed is None:
            raise ScreeningSchemaError("local source registry contains an unmanifested adapter")
        source["sha256"] = observed["adapter_module_sha256"]
        source["source_version_or_date"] = f"timecopilot=={observed['distribution_version']}"
        source["retrieved_at_utc"] = observed["observed_at_utc"]
        source["url_or_path"] = str(
            Path(observed["adapter_module_path"]).relative_to(record["local_package_observations"]["project_root"])
        )


def validate_roadmap_consistency(
    repo_root: Path,
    *,
    expect: str,
    require_update_eligible: bool = False,
    validate_published: Callable[[Path], dict[str, Any]],
) -> None:
    """Read-only roadmap guard; it never reconciles or edits the roadmap."""

    if expect not in {"planned", "complete"}:
        raise RoadmapConsistencyError("expect must be planned or complete")
    root = repo_root.resolve()
    record = validate_published(root)
    if record["overall_classification"] != "pass":
        raise RoadmapConsistencyError("roadmap checks require canonical overall-pass evidence")
    roadmap_path = root / ROADMAP_RELATIVE_PATH
    roadmap = roadmap_path.read_text(encoding="utf-8")
    matches = P1_03_ROADMAP_PATTERN.findall(roadmap)
    expected_marker = " " if expect == "planned" else "x"
    if matches != [expected_marker]:
        raise RoadmapConsistencyError(f"P1-03 roadmap state is not {expect}")
    lines = P1_03_ROADMAP_LINE_PATTERN.findall(roadmap)
    if len(lines) != 1:
        raise RoadmapConsistencyError("roadmap must contain exactly one P1-03 entry")
    planned_line = re.sub(r"^- \[[ x-]\]", "- [ ]", lines[0])
    if planned_line != P1_03_ROADMAP_PLANNED_LINE:
        raise RoadmapConsistencyError("P1-03 roadmap entry contains an unauthorized edit")
    if require_update_eligible and expect != "planned":
        raise RoadmapConsistencyError("update eligibility is meaningful only for planned state")
