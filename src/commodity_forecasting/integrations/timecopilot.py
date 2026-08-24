"""Lazy TimeCopilot bridge for the package forecast-only protocol."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Any, Mapping, Sequence

from commodity_forecasting.forecasting.contracts import RollingOriginError
from commodity_forecasting.forecasting.responses import (
    adapter_payload_digest,
    response_records,
)
from commodity_forecasting.forecasting.schedule import add_months


class LiveDependencyError(RollingOriginError):
    """Raised when the configured live adapter cannot load its dependencies."""


@dataclass(frozen=True)
class TimeCopilotIntegrationConfig:
    """Runtime configuration needed to construct and attest a TimeCopilot model."""

    model_id: str
    model_alias: str
    adapter_class: str
    package_distributions: tuple[str, ...]
    frequency: str = "MS"
    batch_size: int = 1
    point_request_kind: str = "point"
    interval_request_kind: str = "interval"
    quantile_request_kind: str = "quantiles"


@dataclass(frozen=True)
class ForecastCallReceipt:
    origin: str
    request_kind: str
    input_digest: str
    output_sha256: str
    output_rows: int
    status: str = "success"

    def as_record(self) -> dict[str, object]:
        return {
            "origin": self.origin,
            "request_kind": self.request_kind,
            "input_digest": self.input_digest,
            "output_sha256": self.output_sha256,
            "output_rows": self.output_rows,
            "status": self.status,
        }


@dataclass(frozen=True)
class LiveExecutionReceipt:
    runner_kind: str
    execution_mode: str
    adapter_class: str
    model_id: str
    model_alias: str
    package_versions: tuple[tuple[str, str], ...]
    network_policy: str
    cache_policy: str
    call_receipts: tuple[ForecastCallReceipt, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "runner_kind": self.runner_kind,
            "execution_mode": self.execution_mode,
            "adapter_class": self.adapter_class,
            "model_id": self.model_id,
            "model_alias": self.model_alias,
            "package_versions": dict(self.package_versions),
            "network_policy": self.network_policy,
            "cache_policy": self.cache_policy,
            "call_receipts": [receipt.as_record() for receipt in self.call_receipts],
        }


def _required_package_version(distribution: str) -> str:
    try:
        return package_version(distribution)
    except PackageNotFoundError as exc:  # pragma: no cover - environment-dependent
        raise LiveDependencyError(
            f"required live distribution is unavailable: {distribution}"
        ) from exc


def _network_policy() -> str:
    proxy_names = (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
    )
    proxies_present = any(os.environ.get(name) for name in proxy_names)
    offline = (
        os.environ.get("HF_HUB_OFFLINE") == "1"
        and os.environ.get("TRANSFORMERS_OFFLINE") == "1"
    )
    if offline and not proxies_present:
        return "offline_cache_only"
    if proxies_present:
        return "connected_http_proxy"
    return "connected_runtime_default"


def _cache_policy() -> str:
    if os.environ.get("HF_HUB_CACHE"):
        return "explicit_hf_hub_cache"
    return "default_huggingface_cache"


def _response_sha256(response: object) -> tuple[str, int]:
    records = response_records(response)
    payload = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: value.isoformat() if isinstance(value, date) else str(value),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), len(records)


class TimeCopilotForecastAdapter:
    """Adapt TimeCopilot's DataFrame API to the package forecast-only protocol."""

    def __init__(self, model: Any, config: TimeCopilotIntegrationConfig) -> None:
        self._model = model
        self._config = config
        self._call_receipts: list[ForecastCallReceipt] = []

    def forecast(
        self,
        payload: Sequence[Mapping[str, str]],
        *,
        h: int,
        level: Sequence[int] | None = None,
        quantiles: Sequence[float] | None = None,
    ) -> object:
        try:
            import pandas as pd
        except Exception as exc:  # pragma: no cover - environment-dependent
            raise LiveDependencyError("pandas is required for the TimeCopilot adapter") from exc
        frame = pd.DataFrame(
            {
                "unique_id": [row["unique_id"] for row in payload],
                "ds": pd.to_datetime([row["ds"] for row in payload]),
                "y": [float(row["y"]) for row in payload],
            }
        )
        request: dict[str, object] = {}
        if level is not None:
            request["level"] = list(level)
        if quantiles is not None:
            request["quantiles"] = list(quantiles)
        result = self._model.forecast(
            df=frame,
            h=h,
            freq=self._config.frequency,
            **request,
        )
        if level is not None:
            request_kind = self._config.interval_request_kind
        elif quantiles is not None:
            request_kind = self._config.quantile_request_kind
        else:
            request_kind = self._config.point_request_kind
        output_sha256, output_rows = _response_sha256(result)
        self._call_receipts.append(
            ForecastCallReceipt(
                origin=add_months(date.fromisoformat(payload[-1]["ds"]), 1).isoformat(),
                request_kind=request_kind,
                input_digest=adapter_payload_digest(payload),
                output_sha256=output_sha256,
                output_rows=output_rows,
            )
        )
        return result

    def execution_receipt(self) -> LiveExecutionReceipt:
        return LiveExecutionReceipt(
            runner_kind="timecopilot_live",
            execution_mode="zero_shot_forecast_only",
            adapter_class=self._config.adapter_class,
            model_id=self._config.model_id,
            model_alias=self._config.model_alias,
            package_versions=tuple(
                (distribution, _required_package_version(distribution))
                for distribution in self._config.package_distributions
            ),
            network_policy=_network_policy(),
            cache_policy=_cache_policy(),
            call_receipts=tuple(self._call_receipts),
        )


def load_timecopilot_chronos_adapter(
    config: TimeCopilotIntegrationConfig,
) -> TimeCopilotForecastAdapter:
    """Construct a Chronos model while keeping TimeCopilot an optional dependency."""

    try:
        from timecopilot.models.foundation.chronos import Chronos
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise LiveDependencyError(f"reference adapter import failed: {type(exc).__name__}") from exc
    try:
        model = Chronos(
            repo_id=config.model_id,
            batch_size=config.batch_size,
            alias=config.model_alias,
        )
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise LiveDependencyError(
            f"reference adapter construction failed: {type(exc).__name__}"
        ) from exc
    return TimeCopilotForecastAdapter(model, config)
