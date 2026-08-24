"""Sanitized CUDA preflight and runtime telemetry for P1-05."""

from __future__ import annotations

import os
import re
import resource
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from .runtime_environment import (
    REQUIRED_CUDA_MAJOR_MINOR,
    RuntimeCompatibilityError,
    RuntimePreflightError,
    configure_cuda_environment,
    find_cuda_home,
)

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
    text = SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text
    )
    return text[:limit]


def observation_error(label: str, exc: BaseException) -> str:
    """Render a bounded, sanitized observation failure with its exception class."""

    detail = sanitize_error(exc) or "no diagnostic detail"
    return f"{label}: {type(exc).__name__}: {detail}"


FindCudaHome = Callable[[], Path | None]
ConfigureCudaEnvironment = Callable[..., dict[str, str]]


def observe_runtime_environment(
    *,
    find_cuda: FindCudaHome = find_cuda_home,
    configure_cuda: ConfigureCudaEnvironment = configure_cuda_environment,
) -> dict[str, Any]:
    """Observe and exercise CUDA/toolkit availability without importing TimeCopilot."""

    cuda_home = find_cuda()
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
        "observation_errors": [],
    }
    if nvcc_path is not None:
        completed = subprocess.run(
            [str(nvcc_path), "--version"], text=True, capture_output=True, check=False
        )
        match = re.search(r"release\s+(\d+\.\d+)", completed.stdout)
        observation["nvcc_release"] = match.group(1) if match else None
    try:
        configured = configure_cuda()
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
    except Exception as exc:
        observation["observation_errors"].append(
            observation_error("CUDA runtime observation failed", exc)
        )
    observation["cuda_toolkit_available"] = bool(
        observation["cuda_home"]
        and observation["nvcc_path"]
        and observation["nvcc_release"] == REQUIRED_CUDA_MAJOR_MINOR
    )
    return observation


def require_gpu_runtime(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Require the CUDA 13.0 toolkit and a usable GPU observation."""

    failures = []
    if observation["torch_cuda_version"] != REQUIRED_CUDA_MAJOR_MINOR:
        failures.append(f"PyTorch CUDA build is {observation['torch_cuda_version']!r}")
    if not observation["cuda_toolkit_available"]:
        failures.append(f"CUDA {REQUIRED_CUDA_MAJOR_MINOR} toolkit is unavailable")
    if not observation["torch_cuda_available"]:
        failures.append("PyTorch cannot see a CUDA device")
    if not observation["cuda_allocation_verified"]:
        failures.append("a real CUDA tensor allocation did not succeed")
    failures.extend(observation["observation_errors"])
    if failures:
        raise RuntimePreflightError("GPU-required preflight failed: " + "; ".join(failures))
    return dict(observation)


def require_timecopilot_adapter_imports() -> None:
    """Prove that both approved TimeCopilot adapter families load locally."""

    try:
        from timecopilot.models.foundation.chronos import Chronos  # noqa: F401
        from timecopilot.models.foundation.timesfm import TimesFM  # noqa: F401
    except Exception as exc:
        raise RuntimePreflightError(
            f"TimeCopilot foundation adapter import failed: {sanitize_error(exc)}"
        ) from exc


def memory_observation() -> dict[str, Any]:
    """Return process or CUDA peak memory, retaining sanitized observation failures."""

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    multiplier = 1 if sys.platform == "darwin" else 1024
    observation: dict[str, Any] = {
        "source": "process_ru_maxrss",
        "unit": "bytes",
        "device_class": "process",
        "peak": int(peak * multiplier),
        "observation_error": None,
    }
    try:
        import torch

        if torch.cuda.is_available():
            observation = {
                "source": "torch_cuda_max_memory_allocated",
                "unit": "bytes",
                "device_class": "cuda",
                "peak": int(torch.cuda.max_memory_allocated()),
                "observation_error": None,
            }
    except Exception as exc:
        observation["observation_error"] = observation_error(
            "CUDA memory observation failed", exc
        )
    return observation


def device_observation(memory: Mapping[str, Any]) -> str:
    """Describe the CUDA device only when execution evidence supports it."""

    try:
        import torch

        if (
            torch.cuda.is_available()
            and memory.get("device_class") == "cuda"
            and int(memory.get("peak", 0)) > 0
        ):
            current = torch.cuda.current_device()
            return f"cuda:{current}:{torch.cuda.get_device_name(current)}"
        if torch.cuda.is_available():
            return "unknown:cuda_visible_without_observed_allocation"
    except Exception as exc:
        return "unknown:" + observation_error("CUDA device observation failed", exc)
    return "unknown:no_cuda_observation"


def reset_cuda_peak_memory() -> None:
    """Reset the CUDA peak counter or fail the stage with sanitized evidence."""

    try:
        import torch

        if not torch.cuda.is_available():
            return
        torch.cuda.reset_peak_memory_stats()
    except Exception as exc:
        raise RuntimeCompatibilityError(
            observation_error("CUDA peak-memory reset failed", exc)
        ) from exc
