"""CUDA discovery and child-process environment construction for P1-05."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

REQUIRED_CUDA_MAJOR_MINOR = "13.0"
CUDA_HOME_OVERRIDE = "P1_05_CUDA_HOME"


class RuntimeCompatibilityError(RuntimeError):
    """Base error for P1-05 contract failures."""


class RuntimePreflightError(RuntimeCompatibilityError):
    """Raised when the live process is not the exact project environment."""


def assert_project_venv(repo_root: Path) -> None:
    """Require execution from the repository's exact virtual environment."""

    expected = (repo_root.resolve() / ".venv").resolve()
    executable = Path(sys.executable).absolute()
    prefix = Path(sys.prefix).resolve()
    expected_executable_parent = repo_root.resolve() / ".venv" / "bin"
    if prefix != expected or executable.parent != expected_executable_parent:
        raise RuntimePreflightError(
            f"P1-05 live execution requires {expected / 'bin/python'}; observed {executable}"
        )


def cuda_home_candidates(environment: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Return configured and conventional CUDA toolkit locations in priority order."""

    source = os.environ if environment is None else environment
    configured = source.get(CUDA_HOME_OVERRIDE) or source.get("CUDA_HOME")
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

    for root in cuda_home_candidates():
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
        (
            cuda_home / "lib",
            cuda_home / "lib64",
            cuda_home / "targets" / "x86_64-linux" / "lib",
        ),
    )
    configured.pop("CUDA_VISIBLE_DEVICES", None)
    return configured


ConfigureCudaEnvironment = Callable[..., dict[str, str]]


def build_child_environment(
    cache_root: Path,
    *,
    offline: bool,
    repo_root: Path,
    cuda_home: Path | None = None,
    configure_cuda: ConfigureCudaEnvironment = configure_cuda_environment,
) -> dict[str, str]:
    """Build the isolated cache, CUDA, and network environment for one worker."""

    environment = configure_cuda(cuda_home=cuda_home)
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join((str(repo_root / "src"), str(repo_root))),
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
            "ALL_PROXY",
            "all_proxy",
            "HTTP_PROXY",
            "http_proxy",
            "HTTPS_PROXY",
            "https_proxy",
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
