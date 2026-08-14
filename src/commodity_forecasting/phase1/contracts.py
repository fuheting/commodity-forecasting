"""Stable contracts for the Phase 1 dependency/readiness gate."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Final, Literal

EvidenceClassification = Literal["pass", "fail", "blocked", "unsupported"]

TASK_ID: Final = "P1-01"
EVIDENCE_SCHEMA_VERSION: Final = 1
READER_PACKAGE: Final = "openpyxl"
READER_REQUIREMENT: Final = "openpyxl>=3.1,<4"
WORKSHEET_NAME: Final = "Monthly Prices"
TARGET_COLUMN: Final = "Coffee, Arabica"
EXPECTED_RAW_SHA256: Final = "7902a77505ebdc5d202ce65f666c2ee1b04b626f042d7738ed3e6f7d112c8433"
EXPECTED_PERIOD_START: Final = "1960M01"
EXPECTED_PERIOD_END: Final = "2026M07"
EXPECTED_PERIOD_COUNT: Final = 799

ALLOWED_CLASSIFICATIONS: Final[tuple[str, ...]] = ("pass", "fail", "blocked", "unsupported")
REQUIRED_PASS_CHECKS: Final[tuple[str, ...]] = (
    "dependency_declared",
    "phase0_complete",
    "host_bootstrap_explicit",
    "repo_root_explicit",
    "install_non_editable",
    "pip_check",
    "child_outside_repo",
    "child_pythonpath_absent",
    "reader_version_supported",
    "workbook_exists",
    "raw_hash_before_matches",
    "sheet_found",
    "target_found_once",
    "periods_parse",
    "publication_policy_present",
    "raw_hash_after_matches",
    "cleanup_completed",
)


@dataclass(frozen=True)
class PublicationAvailabilityPolicy:
    """Conservative period-only availability policy for the revised workbook."""

    evaluation_label: str = "revised_workbook_pseudo_real_time"
    historical_release_timestamps_available: bool = False
    historical_vintages_available: bool = False
    availability_proxy: str = "strict_prior_month"
    limitation: str = (
        "Historical release timestamps and vintages are not available in the preserved workbook. "
        "Strict prior-month eligibility is a conservative simulation assumption, not a verified "
        "historical publication date; the latest workbook can contain revisions."
    )
    prohibited_claim: str = "Do not describe this evaluation as vintage-real-time."

    def is_available(self, observation_period: date, forecast_origin_period: date) -> bool:
        observation = (observation_period.year, observation_period.month)
        origin = (forecast_origin_period.year, forecast_origin_period.month)
        return observation < origin

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


PUBLICATION_POLICY: Final = PublicationAvailabilityPolicy()


def reader_version_supported(version: str) -> bool:
    """Return whether a final release satisfies the authorized reader range."""

    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", version)
    if match is None:
        return False
    major, minor = int(match.group(1)), int(match.group(2))
    return major == 3 and minor >= 1
