"""Run and validate the P1-05 runtime-compatibility matrix."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import selection
from .target_pipeline import MODEL_READY_RELATIVE_PATH, TargetRow, parse_target_csv

TASK_ID = "P1-05"
SCHEMA_VERSION = 1
EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/runtime_compatibility.json")
FINDING_RELATIVE_PATH = Path("docs/findings/phase1/runtime_compatibility.md")
ROADMAP_RELATIVE_PATH = Path("docs/roadmap.md")
APPROVED_VARIANT_IDS = (
    "amazon/chronos-2",
    "autogluon/chronos-2-synth",
    "autogluon/chronos-2-small",
    "google/timesfm-1.0-200m-pytorch",
    "google/timesfm-2.5-200m-transformers",
)
STAGE_NAMES = (
    "connected_point",
    "connected_interval",
    "connected_quantiles",
    "offline_point",
    "offline_interval",
    "offline_quantiles",
)
STAGE_OUTCOMES = {"success", "failed", "unsupported", "not_run_due_to_prior_failure"}
EXPECTED_HISTORY_START = "2021-08-01"
EXPECTED_HISTORY_END = "2026-07-01"
EXPECTED_FORECAST_TIMESTAMPS = ("2026-08-01", "2026-09-01", "2026-10-01")
INTERVAL_REQUEST = {"level": [80]}
QUANTILE_REQUEST = {"quantiles": [round(value / 10, 1) for value in range(1, 10)]}
P1_05_ROADMAP_PATTERN = re.compile(r"(?m)^- \[([ x-])\] \*\*P1-05\b.*$")
SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|access[_-]?token|password|secret|token)"
    r"(\s*[:=]\s*|\s+)([^\s,;]+)"
)
AUTHORIZATION_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]\s*)(?:(?:bearer|basic)\s+)?[^\s,;]+"
)
URL_CREDENTIAL_PATTERN = re.compile(r"(?i)(://)[^/@\s:]+:[^/@\s]+@")
QUERY_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|secret)=)[^&\s]+"
)
QUOTED_SECRET_PATTERN = re.compile(
    r"(?i)(['\"](?:authorization|api[_-]?key|access[_-]?token|password|secret|token)"
    r"['\"]\s*:\s*['\"])([^'\"]*)(['\"])"
)
FAILURE_CLASSIFICATIONS = {
    "none",
    "environment_blocked",
    "adapter_unsupported",
    "runtime_failed",
    "not_run_due_to_prior_failure",
}
REQUIRED_CUDA_MAJOR_MINOR = "13.0"
CUDA_HOME_OVERRIDE = "P1_05_CUDA_HOME"


class RuntimeCompatibilityError(RuntimeError):
    """Base error for P1-05 contract failures."""


class RuntimePreflightError(RuntimeCompatibilityError):
    """Raised when the live process is not the exact project environment."""


class RuntimeEvidenceError(RuntimeCompatibilityError):
    """Raised when runtime evidence is missing, stale, or inconsistent."""


class OutputContractError(RuntimeCompatibilityError):
    """Raised when an adapter result violates the fixed output contract."""


@dataclass(frozen=True)
class RuntimeWindow:
    rows: tuple[TargetRow, ...]
    digest: str
    history_start: str
    history_end: str
    expected_forecast_timestamps: tuple[str, ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_record(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "history_start": self.history_start,
            "history_end": self.history_end,
            "row_count": self.row_count,
            "expected_forecast_timestamps": list(self.expected_forecast_timestamps),
        }


ReplaceFile = Callable[[Path, Path], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sanitize_error(value: object, *, limit: int = 2000) -> str | None:
    """Return bounded single-line diagnostic text with common secrets redacted."""

    if value is None:
        return None
    text = str(value)
    text = AUTHORIZATION_PATTERN.sub(r"\1<redacted>", text)
    text = QUOTED_SECRET_PATTERN.sub(r"\1<redacted>\3", text)
    text = URL_CREDENTIAL_PATTERN.sub(r"\1<redacted>@", text)
    text = QUERY_SECRET_PATTERN.sub(r"\1<redacted>", text)
    text = " ".join(text.split())
    text = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text)
    return text[:limit]


def _cuda_home_candidates() -> tuple[Path, ...]:
    configured = os.environ.get(CUDA_HOME_OVERRIDE) or os.environ.get("CUDA_HOME")
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        (
            Path.home() / ".local" / "cuda-13.0",
            Path("/usr/local/cuda-13.0"),
            Path("/usr/local/cuda"),
        )
    )
    return tuple(dict.fromkeys(path.expanduser().resolve() for path in candidates))


def find_cuda_home() -> Path | None:
    """Return the first CUDA 13.0 toolkit root with compiler, headers, and runtime."""

    for root in _cuda_home_candidates():
        if all(
            path.exists()
            for path in (
                root / "bin" / "nvcc",
                root / "targets" / "x86_64-linux" / "include" / "cuda.h",
                root / "targets" / "x86_64-linux" / "lib" / "libcudart.so",
            )
        ):
            return root
    return None


def _prepend_path(environment: dict[str, str], name: str, values: Sequence[Path]) -> None:
    existing = environment.get(name)
    prefix = os.pathsep.join(str(value) for value in values)
    environment[name] = prefix if not existing else f"{prefix}{os.pathsep}{existing}"


def configure_cuda_environment(
    environment: Mapping[str, str] | None = None,
    *,
    cuda_home: Path | None = None,
) -> dict[str, str]:
    """Return an environment configured for the verified local CUDA toolkit."""

    configured = dict(os.environ if environment is None else environment)
    cuda_home = cuda_home.resolve() if cuda_home is not None else find_cuda_home()
    if cuda_home is None:
        raise RuntimePreflightError(
            "CUDA 13.0 toolkit not found; set P1_05_CUDA_HOME to a toolkit root "
            "containing nvcc, cuda.h, and libcudart.so"
        )
    configured["CUDA_HOME"] = str(cuda_home)
    configured[CUDA_HOME_OVERRIDE] = str(cuda_home)
    _prepend_path(configured, "PATH", (cuda_home / "bin",))
    _prepend_path(
        configured,
        "LD_LIBRARY_PATH",
        (cuda_home / "lib", cuda_home / "lib64", cuda_home / "targets" / "x86_64-linux" / "lib"),
    )
    configured.pop("CUDA_VISIBLE_DEVICES", None)
    return configured


def observe_runtime_environment() -> dict[str, Any]:
    """Observe and exercise CUDA/toolkit availability without importing TimeCopilot."""

    cuda_home = find_cuda_home()
    nvcc_path = cuda_home / "bin" / "nvcc" if cuda_home is not None else None

    observation: dict[str, Any] = {
        "python_executable": str(Path(sys.executable).absolute()),
        "torch_version": None,
        "torch_cuda_version": None,
        "torch_cuda_available": False,
        "cuda_device_names": [],
        "cuda_home": str(cuda_home) if cuda_home is not None else None,
        "nvcc_path": str(nvcc_path) if nvcc_path is not None else shutil.which("nvcc"),
        "nvcc_release": None,
        "cuda_toolkit_available": False,
        "cuda_allocation_verified": False,
        "selected_device_policy": "gpu_required",
    }
    if nvcc_path is not None:
        completed = subprocess.run(
            [str(nvcc_path), "--version"], text=True, capture_output=True, check=False
        )
        match = re.search(r"release\s+(\d+\.\d+)", completed.stdout)
        observation["nvcc_release"] = match.group(1) if match else None
    try:
        configured = configure_cuda_environment()
        os.environ.update(configured)
        import torch
        from torch.utils.cpp_extension import CUDA_HOME

        available = bool(torch.cuda.is_available())
        observation.update(
            {
                "torch_version": str(torch.__version__),
                "torch_cuda_version": torch.version.cuda,
                "torch_cuda_available": available,
                "cuda_device_names": [
                    torch.cuda.get_device_name(index)
                    for index in range(torch.cuda.device_count())
                ]
                if available
                else [],
                "cuda_home": str(CUDA_HOME) if CUDA_HOME is not None else None,
            }
        )
        if available:
            probe = torch.ones(1, device="cuda")
            observation["cuda_allocation_verified"] = bool(probe.item() == 1)
            del probe
    except Exception:
        pass
    observation["cuda_toolkit_available"] = bool(
        observation["cuda_home"]
        and observation["nvcc_path"]
        and observation["nvcc_release"] == REQUIRED_CUDA_MAJOR_MINOR
    )
    return observation


def require_gpu_runtime() -> dict[str, Any]:
    """Require the CUDA 13.0 toolkit and a usable GPU before any adapter attempt."""

    observation = observe_runtime_environment()
    failures = []
    if observation["torch_cuda_version"] != REQUIRED_CUDA_MAJOR_MINOR:
        failures.append(f"PyTorch CUDA build is {observation['torch_cuda_version']!r}")
    if not observation["cuda_toolkit_available"]:
        failures.append(f"CUDA {REQUIRED_CUDA_MAJOR_MINOR} toolkit is unavailable")
    if not observation["torch_cuda_available"]:
        failures.append("PyTorch cannot see a CUDA device")
    if not observation["cuda_allocation_verified"]:
        failures.append("a real CUDA tensor allocation did not succeed")
    if failures:
        raise RuntimePreflightError("GPU-required preflight failed: " + "; ".join(failures))
    return observation


def require_timecopilot_adapter_imports() -> None:
    """Prove that both approved TimeCopilot adapter families load locally."""

    try:
        from timecopilot.models.foundation.chronos import Chronos  # noqa: F401
        from timecopilot.models.foundation.timesfm import TimesFM  # noqa: F401
    except Exception as exc:
        raise RuntimePreflightError(
            f"TimeCopilot foundation adapter import failed: {sanitize_error(exc)}"
        ) from exc


def _window_digest(rows: Sequence[TargetRow]) -> str:
    payload = "".join(f"{row.unique_id},{row.ds.isoformat()},{row.y}\n" for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_runtime_window(repo_root: Path) -> RuntimeWindow:
    """Load the immutable history-only suffix from the canonical P1-02 target."""

    rows = parse_target_csv(repo_root.resolve() / MODEL_READY_RELATIVE_PATH)
    suffix = tuple(row for row in rows if EXPECTED_HISTORY_START <= row.ds.isoformat() <= EXPECTED_HISTORY_END)
    if len(suffix) != 60:
        raise RuntimePreflightError(f"runtime history must contain exactly 60 rows, found {len(suffix)}")
    dates = tuple(row.ds.isoformat() for row in suffix)
    if dates[0] != EXPECTED_HISTORY_START or dates[-1] != EXPECTED_HISTORY_END:
        raise RuntimePreflightError("runtime history boundaries differ from the approved window")
    expected = tuple(_next_month(suffix[-1].ds, offset).isoformat() for offset in range(1, 4))
    if expected != EXPECTED_FORECAST_TIMESTAMPS:
        raise RuntimePreflightError("derived forecast timestamps differ from the approved horizon")
    return RuntimeWindow(suffix, _window_digest(suffix), dates[0], dates[-1], expected)


def _next_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def assert_project_venv(repo_root: Path) -> None:
    expected = (repo_root.resolve() / ".venv").resolve()
    executable = Path(sys.executable).absolute()
    prefix = Path(sys.prefix).resolve()
    expected_executable_parent = repo_root.resolve() / ".venv" / "bin"
    if prefix != expected or executable.parent != expected_executable_parent:
        raise RuntimePreflightError(
            f"P1-05 live execution requires {expected / 'bin/python'}; observed {executable}"
        )


def _memory_observation() -> dict[str, Any]:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    multiplier = 1 if sys.platform == "darwin" else 1024
    observation: dict[str, Any] = {
        "source": "process_ru_maxrss",
        "unit": "bytes",
        "device_class": "process",
        "peak": int(peak * multiplier),
    }
    try:
        import torch

        if torch.cuda.is_available():
            observation = {
                "source": "torch_cuda_max_memory_allocated",
                "unit": "bytes",
                "device_class": "cuda",
                "peak": int(torch.cuda.max_memory_allocated()),
            }
    except Exception:
        pass
    return observation


def _device_observation(memory: Mapping[str, Any]) -> str:
    try:
        import torch

        if (
            torch.cuda.is_available()
            and memory.get("device_class") == "cuda"
            and int(memory.get("peak", 0)) > 0
        ):
            return f"cuda:{torch.cuda.current_device()}:{torch.cuda.get_device_name(torch.cuda.current_device())}"
        if torch.cuda.is_available():
            return "unknown:cuda_visible_without_observed_allocation"
    except Exception:
        pass
    return "unknown:no_cuda_observation"


def _stage_template(
    variant_id: str,
    stage: str,
    window: RuntimeWindow,
    request_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    offline = stage.startswith("offline_")
    return {
        "stage": stage,
        "variant_id": variant_id,
        "window": window.as_record(),
        "request_parameters": dict(request_parameters),
        "started_at_utc": None,
        "ended_at_utc": None,
        "duration_seconds": None,
        "outcome": "not_run_due_to_prior_failure",
        "load_success": False,
        "output_columns": [],
        "output_shape": None,
        "output_timestamps": [],
        "device": None,
        "device_policy": os.environ.get("P1_05_DEVICE_POLICY", "runtime_default"),
        "network_policy": os.environ.get("P1_05_NETWORK_POLICY", "runtime_default"),
        "memory": None,
        "acquisition_provenance": None if offline else "unknown",
        "offline_flags": {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        if offline
        else {},
        "local_only_mechanism": "environment_flags" if offline else None,
        "exception_class": None,
        "error": None,
        "failure_classification": "not_run_due_to_prior_failure",
    }


def _request_for_stage(stage: str) -> dict[str, Any]:
    if stage.endswith("_interval"):
        return dict(INTERVAL_REQUEST)
    if stage.endswith("_quantiles"):
        return dict(QUANTILE_REQUEST)
    return {}


def not_run_stage(variant_id: str, stage: str, window: RuntimeWindow, reason: str) -> dict[str, Any]:
    entry = _stage_template(variant_id, stage, window, _request_for_stage(stage))
    entry["error"] = sanitize_error(reason)
    return entry


def _classify_failure(exc: Exception, message: str | None) -> tuple[str, str]:
    normalized = (message or "").lower()
    adapter_unsupported = isinstance(exc, NotImplementedError) or (
        isinstance(exc, ValueError)
        and any(
            token in normalized
            for token in ("only supports", "not supported", "valid model id")
        )
    )
    if adapter_unsupported:
        return "unsupported", "adapter_unsupported"
    environment_markers = (
        "cuda_home",
        "cuda install root",
        "socksio",
        "proxy",
        "connection timed out",
        "couldn't connect",
        "could not connect",
        "name resolution",
        "no module named",
        "not installed",
    )
    if isinstance(exc, (RuntimePreflightError, ImportError, ModuleNotFoundError)) or any(
        marker in normalized for marker in environment_markers
    ):
        return "failed", "environment_blocked"
    return "failed", "runtime_failed"


def _adapter_for_variant(variant_id: str) -> Any:
    if variant_id.startswith(("amazon/chronos", "autogluon/chronos")):
        from timecopilot.models.foundation.chronos import Chronos

        return Chronos(repo_id=variant_id, batch_size=1, alias="P105")
    if variant_id.startswith("google/timesfm"):
        from timecopilot.models.foundation.timesfm import TimesFM

        return TimesFM(repo_id=variant_id, context_length=60, batch_size=1, alias="P105")
    raise RuntimeCompatibilityError(f"no approved adapter binding exists for {variant_id}")


def _validate_output(result: Any, stage: str, window: RuntimeWindow) -> tuple[list[str], list[int], list[str]]:
    columns = [str(column) for column in result.columns]
    shape = [int(result.shape[0]), int(result.shape[1])]
    timestamps = [value.date().isoformat() if hasattr(value, "date") else str(value)[:10] for value in result["ds"]]
    if shape[0] != 3 or timestamps != list(window.expected_forecast_timestamps):
        raise OutputContractError(
            f"forecast output must be 3 rows at {window.expected_forecast_timestamps}; "
            f"observed shape={shape}, timestamps={timestamps}"
        )
    if "unique_id" not in columns or "ds" not in columns or "P105" not in columns:
        raise OutputContractError(f"point output columns are incomplete: {columns}")
    expected_unique_id = window.rows[0].unique_id
    unique_ids = {str(value) for value in result["unique_id"]}
    if unique_ids != {expected_unique_id}:
        raise OutputContractError(
            f"forecast unique_id must be {expected_unique_id!r}; observed {sorted(unique_ids)}"
        )
    try:
        point_values = [float(value) for value in result["P105"]]
    except (TypeError, ValueError) as exc:
        raise OutputContractError("point output must be numeric") from exc
    if len(point_values) != 3 or not all(math.isfinite(value) for value in point_values):
        raise OutputContractError("point output must contain three finite values")
    interval_columns = {
        "P105-lo-80",
        "P105-hi-80",
    }
    if stage.endswith("_interval") and not interval_columns.issubset(columns):
        raise OutputContractError(f"interval request returned no lower/upper columns: {columns}")
    expected_quantiles = {f"P105-q-{value}" for value in range(10, 100, 10)}
    if stage.endswith("_quantiles") and not expected_quantiles.issubset(columns):
        missing = sorted(expected_quantiles - set(columns))
        raise OutputContractError(f"quantile request omitted columns: {missing}")
    requested_probabilistic = (
        interval_columns
        if stage.endswith("_interval")
        else expected_quantiles
        if stage.endswith("_quantiles")
        else set()
    )
    for column in requested_probabilistic:
        try:
            values = [float(value) for value in result[column]]
        except (TypeError, ValueError) as exc:
            raise OutputContractError(f"{column} output must be numeric") from exc
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            raise OutputContractError(f"{column} output must contain three finite values")
    return columns, shape, timestamps


def run_worker_attempt(repo_root: Path, variant_id: str, stage: str) -> dict[str, Any]:
    """Execute one adapter request. This entrypoint is called only in a fresh child."""

    selection.require_variant_approved(repo_root, variant_id)
    require_gpu_runtime()
    if stage not in STAGE_NAMES:
        raise RuntimeCompatibilityError(f"unknown stage: {stage}")
    window = load_runtime_window(repo_root)
    request = _request_for_stage(stage)
    entry = _stage_template(variant_id, stage, window, request)
    entry["started_at_utc"] = _utc_now()
    started = time.monotonic()
    try:
        import pandas as pd

        frame = pd.DataFrame(
            {
                "unique_id": [row.unique_id for row in window.rows],
                "ds": pd.to_datetime([row.ds.isoformat() for row in window.rows]),
                "y": [float(row.y) for row in window.rows],
            }
        )
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass
        adapter = _adapter_for_variant(variant_id)
        entry["load_success"] = True
        result = adapter.forecast(df=frame, h=3, freq="MS", **request)
        columns, shape, timestamps = _validate_output(result, stage, window)
        memory = _memory_observation()
        if memory.get("device_class") != "cuda" or int(memory.get("peak", 0)) <= 0:
            raise OutputContractError("forecast completed without an observed CUDA allocation")
        entry.update(
            {
                "outcome": "success",
                "load_success": True,
                "output_columns": columns,
                "output_shape": shape,
                "output_timestamps": timestamps,
                "failure_classification": "none",
            }
        )
    except Exception as exc:
        message = sanitize_error(exc)
        outcome, failure_classification = _classify_failure(exc, message)
        entry.update(
            {
                "outcome": outcome,
                "exception_class": type(exc).__name__,
                "error": message,
                "failure_classification": failure_classification,
            }
        )
    entry["ended_at_utc"] = _utc_now()
    entry["duration_seconds"] = round(time.monotonic() - started, 6)
    entry["memory"] = _memory_observation()
    entry["device"] = _device_observation(entry["memory"])
    return entry


def _cache_manifest(cache_root: Path) -> dict[str, int]:
    if not cache_root.exists():
        return {}
    return {
        path.relative_to(cache_root).as_posix(): path.stat().st_size
        for path in sorted(cache_root.rglob("*"))
        if path.is_file()
    }


def derive_acquisition_provenance(before: Mapping[str, int], after: Mapping[str, int]) -> str:
    if after != before and after:
        return "downloaded"
    if before and after == before:
        return "cache_hit"
    return "unknown"


def _child_environment(
    cache_root: Path,
    *,
    offline: bool,
    cuda_home: Path | None = None,
) -> dict[str, str]:
    environment = configure_cuda_environment(cuda_home=cuda_home)
    environment.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "HF_HOME": str(cache_root / "huggingface"),
            "HF_HUB_CACHE": str(cache_root / "huggingface" / "hub"),
            "TORCH_HOME": str(cache_root / "torch"),
            "XDG_CACHE_HOME": str(cache_root / "xdg"),
            "MPLCONFIGDIR": str(cache_root / "matplotlib"),
            "P1_05_DEVICE_POLICY": "gpu_required",
        }
    )
    if offline:
        for name in (
            "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
            "HTTPS_PROXY", "https_proxy",
        ):
            environment.pop(name, None)
        environment["HF_HUB_OFFLINE"] = "1"
        environment["TRANSFORMERS_OFFLINE"] = "1"
        environment["P1_05_NETWORK_POLICY"] = "offline_flags_no_proxy"
    else:
        environment.pop("ALL_PROXY", None)
        environment.pop("all_proxy", None)
        environment.pop("HF_HUB_OFFLINE", None)
        environment.pop("TRANSFORMERS_OFFLINE", None)
        environment["P1_05_NETWORK_POLICY"] = "http_proxy_without_socks_fallback"
    return environment


def _run_attempt_child(
    repo_root: Path,
    variant_id: str,
    stage: str,
    cache_root: Path,
    *,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    offline = stage.startswith("offline_")
    acquisition_cache = cache_root / "huggingface" / "hub"
    before = _cache_manifest(acquisition_cache)
    command = [
        sys.executable,
        "-m",
        "commodity_forecasting.phase1.runtime_compatibility",
        "--repo-root",
        str(repo_root),
        "--live",
        "--worker-variant",
        variant_id,
        "--worker-stage",
        stage,
    ]
    window = load_runtime_window(repo_root)
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=_child_environment(cache_root, offline=offline),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        entry = _stage_template(variant_id, stage, window, _request_for_stage(stage))
        entry.update(
            {
                "started_at_utc": _utc_now(),
                "ended_at_utc": _utc_now(),
                "duration_seconds": float(timeout_seconds),
                "outcome": "failed",
                "exception_class": type(exc).__name__,
                "error": sanitize_error(f"attempt exceeded {timeout_seconds} seconds"),
                "failure_classification": "runtime_failed",
            }
        )
        return entry
    marker = "P1_05_RESULT="
    payload_lines = [line[len(marker) :] for line in completed.stdout.splitlines() if line.startswith(marker)]
    if completed.returncode == 0 and len(payload_lines) == 1:
        try:
            entry = json.loads(payload_lines[0])
        except json.JSONDecodeError as exc:
            entry = not_run_stage(variant_id, stage, window, str(exc))
            entry["outcome"] = "failed"
            entry["exception_class"] = type(exc).__name__
            entry["failure_classification"] = "runtime_failed"
    else:
        entry = _stage_template(variant_id, stage, window, _request_for_stage(stage))
        entry.update(
            {
                "started_at_utc": _utc_now(),
                "ended_at_utc": _utc_now(),
                "duration_seconds": 0.0,
                "outcome": "failed",
                "exception_class": "ChildProcessError",
                "error": sanitize_error(completed.stderr or completed.stdout or f"child exit {completed.returncode}"),
                "failure_classification": "runtime_failed",
                "child_exit_code": completed.returncode,
            }
        )
    if not offline:
        entry["acquisition_provenance"] = derive_acquisition_provenance(
            before, _cache_manifest(acquisition_cache)
        )
    return entry


def _required_successful_stages(stages: Sequence[Mapping[str, Any]]) -> list[str]:
    by_name = {stage["stage"]: stage for stage in stages}
    required = ["connected_point", "offline_point"]
    for kind in ("interval", "quantiles"):
        if by_name[f"connected_{kind}"]["outcome"] == "success":
            required.extend((f"connected_{kind}", f"offline_{kind}"))
    return required


def derive_candidate_summary(
    variant_id: str,
    approved_order: int,
    stages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_name = {stage["stage"]: stage for stage in stages}
    connected_probabilistic = [
        kind for kind in ("interval", "quantiles") if by_name[f"connected_{kind}"]["outcome"] == "success"
    ]
    required = _required_successful_stages(stages)
    complete = (
        by_name["connected_point"]["outcome"] == "success"
        and by_name["connected_point"]["acquisition_provenance"] in {"downloaded", "cache_hit"}
        and bool(connected_probabilistic)
        and all(by_name[name]["outcome"] == "success" for name in required)
    )
    if complete:
        classification = "pass"
    elif by_name["connected_point"]["outcome"] == "unsupported":
        classification = "unsupported"
    elif (
        by_name["connected_point"].get("failure_classification") == "environment_blocked"
        or all(stage["outcome"] == "not_run_due_to_prior_failure" for stage in stages)
    ):
        classification = "blocked"
    else:
        classification = "fail"
    successful = [stage for stage in stages if stage["outcome"] == "success"]
    columns = sorted({column for stage in successful for column in stage["output_columns"]})
    errors = [
        {"stage": stage["stage"], "exception_class": stage["exception_class"], "error": stage["error"]}
        for stage in stages
        if stage["error"]
    ]
    memory = _aggregate_candidate_memory(stages, required) if complete else None
    return {
        "variant_id": variant_id,
        "approved_order": approved_order,
        "contract_completeness": complete,
        "connected_acquisition_result": by_name["connected_point"]["acquisition_provenance"],
        "offline_replay_result": "success" if complete else "incomplete",
        "point_output": by_name["connected_point"]["outcome"] == "success",
        "probabilistic_output_kind": (
            "both" if len(connected_probabilistic) == 2 else connected_probabilistic[0] if connected_probabilistic else "none"
        ),
        "output_columns": columns,
        "output_shape": by_name["connected_point"]["output_shape"],
        "device_observation": sorted({stage["device"] for stage in successful if stage["device"]}),
        "memory_observation": memory,
        "duration_seconds": round(
            sum(float(stage["duration_seconds"] or 0.0) for stage in stages), 6
        ),
        "classification": classification,
        "errors": errors,
        "selection_key": None,
    }


def _aggregate_candidate_memory(
    stages: Sequence[Mapping[str, Any]], required: Sequence[str]
) -> dict[str, Any] | None:
    by_name = {stage["stage"]: stage for stage in stages}
    observations = [by_name[name].get("memory") for name in required]
    valid_observations: list[dict[str, Any]] = []
    for item in observations:
        if not isinstance(item, dict) or not isinstance(item.get("peak"), int):
            return None
        valid_observations.append(item)
    classes = {
        (item["source"], item["unit"], item["device_class"])
        for item in valid_observations
    }
    if len(classes) != 1:
        return None
    source, unit, device_class = classes.pop()
    return {
        "source": source,
        "unit": unit,
        "device_class": device_class,
        "peak": max(item["peak"] for item in valid_observations),
        "required_stages": list(required),
    }


def validate_candidate(candidate: Mapping[str, Any], window: RuntimeWindow) -> None:
    variant_id = candidate.get("variant_id")
    if variant_id not in APPROVED_VARIANT_IDS:
        raise RuntimeEvidenceError(f"candidate is not approved: {variant_id}")
    stages = candidate.get("stage_history")
    if not isinstance(stages, list) or [stage.get("stage") for stage in stages] != list(STAGE_NAMES):
        raise RuntimeEvidenceError("stage_history must contain the six ordered attempt slots")
    for stage in stages:
        if stage.get("variant_id") != variant_id or stage.get("window") != window.as_record():
            raise RuntimeEvidenceError("stage identity or immutable window differs")
        if stage.get("outcome") not in STAGE_OUTCOMES:
            raise RuntimeEvidenceError("stage outcome is invalid")
        if stage.get("failure_classification") not in FAILURE_CLASSIFICATIONS:
            raise RuntimeEvidenceError("stage failure classification is invalid")
        request = stage.get("request_parameters")
        if request != _request_for_stage(stage["stage"]):
            raise RuntimeEvidenceError("stage request parameters differ from the independent request contract")
        if stage["stage"].startswith("offline_"):
            if stage.get("offline_flags") != {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}:
                raise RuntimeEvidenceError("offline flags are incomplete")
        elif stage.get("acquisition_provenance") not in {"downloaded", "cache_hit", "unknown"}:
            raise RuntimeEvidenceError("connected acquisition provenance is invalid")
        if stage.get("device_policy") not in {"runtime_default", "gpu_required"}:
            raise RuntimeEvidenceError("device policy is invalid")
        if stage.get("network_policy") not in {
            "runtime_default",
            "http_proxy_without_socks_fallback",
            "offline_flags_no_proxy",
        }:
            raise RuntimeEvidenceError("network policy is invalid")
        if stage["outcome"] == "success":
            expected_columns, expected_shape, expected_timestamps = (
                stage.get("output_columns"),
                stage.get("output_shape"),
                stage.get("output_timestamps"),
            )
            if (
                stage.get("load_success") is not True
                or not isinstance(expected_columns, list)
                or not expected_columns
                or not isinstance(expected_shape, list)
                or len(expected_shape) != 2
                or expected_shape[0] != 3
                or expected_shape[1] != len(expected_columns)
                or expected_timestamps != list(window.expected_forecast_timestamps)
                or stage.get("failure_classification") != "none"
                or stage.get("exception_class") is not None
                or stage.get("error") is not None
            ):
                raise RuntimeEvidenceError("successful stage output evidence is incomplete")
            if not str(stage.get("device", "")).startswith("cuda:"):
                raise RuntimeEvidenceError("successful stage lacks observed CUDA execution")
            memory = stage.get("memory")
            if (
                not isinstance(memory, dict)
                or memory.get("device_class") != "cuda"
                or not isinstance(memory.get("peak"), int)
                or memory["peak"] <= 0
            ):
                raise RuntimeEvidenceError("successful stage lacks positive CUDA peak memory")
            if stage["stage"].endswith("_interval") and not (
                {"P105-lo-80", "P105-hi-80"}.issubset(expected_columns)
            ):
                raise RuntimeEvidenceError("successful interval stage lacks interval columns")
            required_quantiles = {f"P105-q-{value}" for value in range(10, 100, 10)}
            if stage["stage"].endswith("_quantiles") and not required_quantiles.issubset(
                expected_columns
            ):
                raise RuntimeEvidenceError("successful quantile stage lacks quantile columns")
        elif stage["outcome"] == "unsupported":
            if stage.get("failure_classification") != "adapter_unsupported":
                raise RuntimeEvidenceError("unsupported stage is not adapter-classified")
        elif stage["outcome"] == "failed":
            if stage.get("failure_classification") not in {"environment_blocked", "runtime_failed"}:
                raise RuntimeEvidenceError("failed stage classification is inconsistent")
        elif stage.get("failure_classification") != "not_run_due_to_prior_failure":
            raise RuntimeEvidenceError("not-run stage classification is inconsistent")
    expected = derive_candidate_summary(variant_id, APPROVED_VARIANT_IDS.index(variant_id), stages)
    comparable_keys = set(expected) - {"selection_key"}
    summary = {key: candidate.get(key) for key in comparable_keys}
    expected_summary = {key: expected[key] for key in comparable_keys}
    if summary != expected_summary:
        raise RuntimeEvidenceError("candidate summary differs from authoritative stage_history")


def select_reference(candidates: Sequence[dict[str, Any]]) -> tuple[str | None, str, list[dict[str, Any]]]:
    passing = [candidate for candidate in candidates if candidate["contract_completeness"]]
    if not passing:
        return None, "no_full_contract_pass", list(candidates)
    observations = [candidate["memory_observation"] for candidate in passing]
    comparable = all(isinstance(item, dict) for item in observations)
    metric_classes = {
        (item["source"], item["unit"], item["device_class"])
        for item in observations
        if isinstance(item, dict)
    }
    use_footprint = comparable and len(metric_classes) == 1
    ranked = list(candidates)
    for candidate in ranked:
        if not candidate["contract_completeness"]:
            candidate["selection_key"] = None
        elif use_footprint:
            candidate["selection_key"] = [
                0,
                candidate["memory_observation"]["peak"],
                candidate["approved_order"],
            ]
        else:
            candidate["selection_key"] = [0, candidate["approved_order"]]
    selected = min(passing, key=lambda item: item["selection_key"])
    basis = "smallest_verified_common_peak_then_p1_04_order" if use_footprint else "p1_04_order_no_common_footprint"
    return selected["variant_id"], basis, ranked


def build_record(
    candidates: Sequence[dict[str, Any]],
    window: RuntimeWindow,
    *,
    approval_decision_id: str,
    approval_sha256: str,
    generated_at_utc: str | None = None,
    global_error: str | None = None,
) -> dict[str, Any]:
    complete = len(candidates) == len(APPROVED_VARIANT_IDS)
    selected, basis, ranked = select_reference([dict(candidate) for candidate in candidates]) if complete else (None, "selector_not_run", list(candidates))
    task_outcome = "pass" if complete and selected else "fail" if complete else "blocked"
    record = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": f"P1-05-{(generated_at_utc or _utc_now()).replace('-', '').replace(':', '')}",
        "generated_at_utc": generated_at_utc or _utc_now(),
        "approval_decision_id": approval_decision_id,
        "approval_evidence_sha256": approval_sha256,
        "approved_variant_ids": list(APPROVED_VARIANT_IDS),
        "window": window.as_record(),
        "matrix_completeness": "complete" if complete else "partial",
        "task_outcome": task_outcome,
        "selector_executed": complete,
        "selected_reference": selected,
        "selection_basis": basis,
        "candidate_records": ranked,
        "checks": {
            "approval_gate_enforced": True,
            "exact_60x3_window": True,
            "history_only": True,
            "serial_candidate_execution": True,
            "independent_probabilistic_requests": True,
            "offline_replay_flags": True,
            "selector_deterministic": complete,
        },
        "errors": [sanitize_error(global_error)] if global_error else [],
    }
    validate_record(record, window=window)
    return record


def validate_record(record: Mapping[str, Any], *, window: RuntimeWindow | None = None) -> dict[str, Any]:
    required = {
        "schema_version", "task_id", "run_id", "generated_at_utc", "approval_decision_id",
        "approval_evidence_sha256", "approved_variant_ids", "window", "matrix_completeness",
        "task_outcome", "selector_executed", "selected_reference", "selection_basis",
        "candidate_records", "checks", "errors",
    }
    if not isinstance(record, dict) or set(record) != required:
        raise RuntimeEvidenceError("runtime evidence fields differ from the closed schema")
    if record["schema_version"] != SCHEMA_VERSION or record["task_id"] != TASK_ID:
        raise RuntimeEvidenceError("runtime evidence version or task ID is invalid")
    if record["approved_variant_ids"] != list(APPROVED_VARIANT_IDS):
        raise RuntimeEvidenceError("runtime evidence does not preserve the approved order")
    if window is None:
        window_record = record["window"]
        if not isinstance(window_record, dict):
            raise RuntimeEvidenceError("window must be an object")
        window = RuntimeWindow(
            rows=tuple(
                TargetRow("validation_placeholder", date.min, "0")
                for _ in range(window_record.get("row_count", 0))
            ),
            digest=window_record.get("digest", ""),
            history_start=window_record.get("history_start", ""),
            history_end=window_record.get("history_end", ""),
            expected_forecast_timestamps=tuple(window_record.get("expected_forecast_timestamps", [])),
        )
        if window_record.get("row_count") != 60:
            raise RuntimeEvidenceError("runtime window must contain 60 rows")
    if record["window"] != {**window.as_record(), "row_count": record["window"]["row_count"]}:
        raise RuntimeEvidenceError("top-level runtime window is inconsistent")
    candidates = record["candidate_records"]
    if not isinstance(candidates, list):
        raise RuntimeEvidenceError("candidate_records must be a list")
    if [candidate.get("variant_id") for candidate in candidates] != list(APPROVED_VARIANT_IDS[: len(candidates)]):
        raise RuntimeEvidenceError("candidate records must preserve the approved prefix order")
    for candidate in candidates:
        validate_candidate(candidate, window)
    complete = len(candidates) == len(APPROVED_VARIANT_IDS)
    if record["matrix_completeness"] != ("complete" if complete else "partial"):
        raise RuntimeEvidenceError("matrix completeness disagrees with terminal records")
    expected_selected, expected_basis, expected_candidates = (
        select_reference([dict(candidate) for candidate in candidates]) if complete else (None, "selector_not_run", candidates)
    )
    expected_outcome = "pass" if complete and expected_selected else "fail" if complete else "blocked"
    if (
        record["selector_executed"] is not complete
        or record["selected_reference"] != expected_selected
        or record["selection_basis"] != expected_basis
        or record["task_outcome"] != expected_outcome
        or record["candidate_records"] != expected_candidates
    ):
        raise RuntimeEvidenceError("lifecycle or selector summary is not deterministic")
    checks = record["checks"]
    if not isinstance(checks, dict) or set(checks) != {
        "approval_gate_enforced", "exact_60x3_window", "history_only",
        "serial_candidate_execution", "independent_probabilistic_requests",
        "offline_replay_flags", "selector_deterministic",
    }:
        raise RuntimeEvidenceError("runtime checks differ from the closed schema")
    if any(value is not True for key, value in checks.items() if key != "selector_deterministic"):
        raise RuntimeEvidenceError("required runtime checks must be true")
    if checks["selector_deterministic"] is not complete:
        raise RuntimeEvidenceError("selector check disagrees with matrix completeness")
    return dict(record)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_markdown(record: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 1 Runtime Compatibility and Reference Selection",
        "",
        f"- Run: `{record['run_id']}`",
        f"- Matrix: `{record['matrix_completeness']}`",
        f"- Outcome: `{record['task_outcome']}`",
        f"- Selected reference: `{record['selected_reference'] or 'none'}`",
        f"- Selection basis: `{record['selection_basis']}`",
        f"- History: `{record['window']['history_start']}..{record['window']['history_end']}` (`{record['window']['row_count']}` rows)",
        f"- Forecast timestamps: `{', '.join(record['window']['expected_forecast_timestamps'])}`",
        "",
        "## Candidate matrix",
        "",
        "| Order | Variant | Classification | Point | Probabilistic | Offline replay | Peak memory | Duration (s) |",
        "| ---: | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for candidate in record["candidate_records"]:
        memory = candidate["memory_observation"]
        peak = "unmeasured" if memory is None else f"{memory['peak']} {memory['unit']} ({memory['source']})"
        lines.append(
            f"| {candidate['approved_order'] + 1} | `{candidate['variant_id']}` | `{candidate['classification']}` | "
            f"`{candidate['point_output']}` | `{candidate['probabilistic_output_kind']}` | "
            f"`{candidate['offline_replay_result']}` | {peak} | {candidate['duration_seconds']:.6f} |"
        )
    lines.extend(["", "## Attempt evidence", ""])
    for candidate in record["candidate_records"]:
        lines.append(f"### `{candidate['variant_id']}`")
        lines.append("")
        for stage in candidate["stage_history"]:
            detail = stage["error"] or ", ".join(stage["output_columns"]) or "no output"
            lines.append(
                f"- `{stage['stage']}`: `{stage['outcome']}`; device `{stage['device'] or 'unobserved'}`; "
                f"device policy `{stage['device_policy']}`; network policy `{stage['network_policy']}`; "
                f"acquisition `{stage['acquisition_provenance']}`; {detail}"
            )
        lines.append("")
    lines.extend(
        [
            "## Limits",
            "",
            "This is one history-only 60-month/3-month runtime smoke on the local machine. It is not an accuracy ranking, tuned evaluation, training run, or backtest. Unknown device or unavailable peak-memory observations remain unknown rather than inferred.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: bytes, replace_file: ReplaceFile = os.replace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sanitize_record_errors(record: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = copy.deepcopy(dict(record))
    sanitized["errors"] = [sanitize_error(error) for error in sanitized.get("errors", [])]
    for candidate in sanitized.get("candidate_records", []):
        for error in candidate.get("errors", []):
            error["error"] = sanitize_error(error.get("error"))
        for stage in candidate.get("stage_history", []):
            stage["error"] = sanitize_error(stage.get("error"))
    return sanitized


def publish_record(
    repo_root: Path,
    record: Mapping[str, Any],
    *,
    replace_file: ReplaceFile = os.replace,
) -> dict[str, Any]:
    validated = validate_record(_sanitize_record_errors(record))
    markdown = render_markdown(validated).encode("utf-8")
    evidence = (json.dumps(validated, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(repo_root / FINDING_RELATIVE_PATH, markdown, replace_file)
    _atomic_write(repo_root / EVIDENCE_RELATIVE_PATH, evidence, replace_file)
    return validated


def validate_published_state(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    approval = selection.validate_published_state(root)
    path = root / EVIDENCE_RELATIVE_PATH
    if not path.is_file():
        raise RuntimeEvidenceError("P1-05 runtime evidence is missing; use --live to run the matrix")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeEvidenceError("P1-05 runtime evidence is unreadable") from exc
    validated = validate_record(record)
    if validated["approval_decision_id"] != approval["decision_id"]:
        raise RuntimeEvidenceError("P1-05 evidence is stale against the P1-04 decision")
    approval_path = root / selection.EVIDENCE_RELATIVE_PATH
    if validated["approval_evidence_sha256"] != _sha256_file(approval_path):
        raise RuntimeEvidenceError("P1-05 evidence is stale against P1-04 bytes")
    finding = root / FINDING_RELATIVE_PATH
    if not finding.is_file() or finding.read_text(encoding="utf-8") != render_markdown(validated):
        raise RuntimeEvidenceError("P1-05 Markdown differs from canonical JSON")
    return validated


def roadmap_ready(record: Mapping[str, Any]) -> bool:
    return (
        record.get("matrix_completeness") == "complete"
        and record.get("task_outcome") == "pass"
        and isinstance(record.get("selected_reference"), str)
        and bool(record["selected_reference"])
    )


def update_roadmap(repo_root: Path, record: Mapping[str, Any]) -> None:
    if not roadmap_ready(record):
        raise RuntimeEvidenceError("P1-05 roadmap completion requires a complete pass and selected reference")
    path = repo_root.resolve() / ROADMAP_RELATIVE_PATH
    text = path.read_text(encoding="utf-8")
    matches = P1_05_ROADMAP_PATTERN.findall(text)
    if matches not in ([" "], ["x"]):
        raise RuntimeEvidenceError("P1-05 roadmap line is missing, duplicated, or invalid")
    if matches == ["x"]:
        return
    updated = P1_05_ROADMAP_PATTERN.sub(lambda match: match.group(0).replace("[ ]", "[x]", 1), text)
    _atomic_write(path, updated.encode("utf-8"))


def _candidate_record(variant_id: str, order: int, stages: list[dict[str, Any]]) -> dict[str, Any]:
    record = derive_candidate_summary(variant_id, order, stages)
    record["stage_history"] = stages
    return record


def run_live_matrix(
    repo_root: Path,
    *,
    timeout_seconds: int = 1800,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    """Run the five approved candidates serially and publish canonical evidence."""

    root = repo_root.resolve()
    assert_project_venv(root)
    approval = selection.validate_published_state(root)
    approved = selection.require_runtime_approval(root, APPROVED_VARIANT_IDS)
    if approved != APPROVED_VARIANT_IDS:
        raise RuntimePreflightError("P1-04 returned a different approved shortlist")
    window = load_runtime_window(root)
    candidates: list[dict[str, Any]] = []
    approval_sha256 = _sha256_file(root / selection.EVIDENCE_RELATIVE_PATH)

    def publish_current(global_error: str | None = None) -> dict[str, Any]:
        record = build_record(
            candidates,
            window,
            approval_decision_id=approval["decision_id"],
            approval_sha256=approval_sha256,
            global_error=global_error,
        )
        return publish_record(root, record)

    try:
        os.environ.update(configure_cuda_environment())
        require_gpu_runtime()
        require_timecopilot_adapter_imports()
    except RuntimeCompatibilityError as exc:
        return publish_current(f"{type(exc).__name__}: {exc}")
    matrix_cache = (
        cache_root.resolve()
        if cache_root is not None
        else Path(tempfile.gettempdir()) / "commodity-forecasting-p1-05-cache"
    )
    matrix_cache.mkdir(parents=True, exist_ok=True)
    publish_current()
    try:
        for order, variant_id in enumerate(APPROVED_VARIANT_IDS):
            candidate_cache = matrix_cache / f"candidate-{order}"
            stages: list[dict[str, Any]] = []
            for stage in STAGE_NAMES[:3]:
                stages.append(
                    _run_attempt_child(
                        root, variant_id, stage, candidate_cache, timeout_seconds=timeout_seconds
                    )
                )
            connected = {stage["stage"]: stage for stage in stages}
            for stage in STAGE_NAMES[3:]:
                connected_name = stage.replace("offline_", "connected_", 1)
                if connected[connected_name]["outcome"] == "success":
                    stages.append(
                        _run_attempt_child(
                            root, variant_id, stage, candidate_cache, timeout_seconds=timeout_seconds
                        )
                    )
                else:
                    stages.append(
                        not_run_stage(
                            variant_id,
                            stage,
                            window,
                            f"{connected_name} did not succeed",
                        )
                    )
            candidate = _candidate_record(variant_id, order, stages)
            validate_candidate(candidate, window)
            candidates.append(candidate)
            publish_current()
            print(
                f"P1-05 candidate {order + 1}/{len(APPROVED_VARIANT_IDS)} "
                f"{variant_id}: {candidate['classification']}",
                file=sys.stderr,
                flush=True,
            )
    except KeyboardInterrupt:
        publish_current("KeyboardInterrupt: live matrix interrupted")
        raise
    except Exception as exc:
        return publish_current(f"{type(exc).__name__}: {exc}")
    published = publish_current()
    if roadmap_ready(published):
        update_roadmap(root, published)
    return published


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="run the live model matrix")
    parser.add_argument("--worker-variant", choices=APPROVED_VARIANT_IDS, help=argparse.SUPPRESS)
    parser.add_argument("--worker-stage", choices=STAGE_NAMES, help=argparse.SUPPRESS)
    parser.add_argument("--timeout-seconds", type=int, default=1800, help=argparse.SUPPRESS)
    parser.add_argument("--cache-root", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.repo_root.is_absolute():
        print("--repo-root must be absolute", file=sys.stderr)
        return 1
    if (args.worker_variant is None) != (args.worker_stage is None):
        print("worker variant and stage must be supplied together", file=sys.stderr)
        return 1
    try:
        if args.worker_variant is not None:
            if not args.live:
                raise RuntimePreflightError("worker execution requires --live")
            assert_project_venv(args.repo_root)
            result = run_worker_attempt(args.repo_root, args.worker_variant, args.worker_stage)
            print("P1_05_RESULT=" + json.dumps(result, sort_keys=True))
            return 0
        record = (
            run_live_matrix(
                args.repo_root,
                timeout_seconds=args.timeout_seconds,
                cache_root=args.cache_root,
            )
            if args.live
            else validate_published_state(args.repo_root)
        )
    except (RuntimeCompatibilityError, selection.SelectionError) as exc:
        print(sanitize_error(exc), file=sys.stderr)
        return 1
    print(json.dumps(record, sort_keys=True))
    return 0 if record["task_outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
