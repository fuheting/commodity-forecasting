"""Shared contracts for Phase 0 evidence and fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

EvidenceMode = Literal["offline-unit", "network-smoke"]
EvidenceClassification = Literal["pass", "fail", "blocked", "unsupported"]
CovariateCapability = Literal["past_only", "known_future", "both", "neither", "unknown"]
CovariateGateResult = Literal[
    "native_path_selected",
    "adapter_gap_proven",
    "model_unsupported",
    "blocked_or_unknown",
]
ProbabilisticOutputKind = Literal["intervals", "quantiles", "both", "none", "unknown"]
ProbabilisticGateResult = Literal[
    "compatible_adapter_selected",
    "adapter_gap_proven",
    "model_unsupported",
    "blocked_or_unknown",
]
CatalogUnknown = Literal["unknown"]
ContinuousSeriesKind = Literal[
    "static_monthly_workbook",
    "provider_continuous_front_month",
    "raw_contracts_for_later_construction",
    "unknown",
    "unsupported",
]

REQUIRED_EVIDENCE_FIELDS: Final[tuple[str, ...]] = (
    "run_id",
    "test_id",
    "work_item",
    "timestamp_utc",
    "mode",
    "command",
    "tool",
    "timecopilot_version",
    "model_or_adapter",
    "fixture_id",
    "data_origin",
    "credential_state",
    "network_state",
    "observed_result",
    "classification",
    "leakage_controls",
    "artifact_paths",
)

SM01_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "model_native_capability",
    "adapter_exposure",
    "gate_result",
)

SM02_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "model_native_capability",
    "adapter_exposure",
    "gate_result",
    "probabilistic_output_kind",
    "output_columns",
    "unsupported_combinations",
)

SM03_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "llm_provider",
    "llm_model",
    "tool_calls",
    "forecast_analysis",
    "user_query_response",
)

SM04_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "candidates",
    "primary_datasource",
    "fallback_datasource",
    "continuous_series_kind",
    "roll_methodology",
)

CATALOG_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "dataset_id",
    "category",
    "name",
    "source_provider",
    "source_locator",
    "access_method",
    "native_frequency",
    "fields",
    "programmatic_access",
    "auth_required",
    "status",
)


@dataclass(frozen=True)
class ForecastWindow:
    """A leakage-safe walk-forward window."""

    cutoff: str
    train_start: str
    train_end: str
    forecast_start: str
    forecast_end: str
