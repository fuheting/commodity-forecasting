"""Credential handling and isolated live-provider execution for P1-08."""

from __future__ import annotations

import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, cast

from commodity_forecasting.analysis import (
    AnalysisOutputError,
    build_agent_frame,
    extract_analysis_output,
)

from . import runtime_compatibility
from . import natural_language_publication as publication


def load_deepseek_api_key(
    env_path: Path,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> str:
    """Load exactly ``DEEPSEEK_API_KEY`` with strict, dependency-free semantics."""

    target = os.environ if environ is None else environ
    existing = target.get(publication.ENV_KEY, "")
    if existing.strip():
        return existing
    try:
        handle = env_path.open("r", encoding="utf-8")
    except OSError as exc:
        raise publication.CredentialUnavailable("credential is unavailable") from exc
    declarations: list[str] = []
    try:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export"):
                remainder = line[len("export"):]
                if remainder and remainder[0].isspace():
                    line = remainder.strip()
            if "=" not in line:
                if re.match(rf"^{re.escape(publication.ENV_KEY)}(?:\s|$)", line):
                    raise publication.EnvContractError(
                        "environment file violates the one-key contract"
                    )
                continue
            key, raw_value = line.split("=", 1)
            if key.strip() != publication.ENV_KEY:
                continue
            value = raw_value.strip()
            if not value:
                raise publication.EnvContractError(
                    "environment file violates the one-key contract"
                )
            if value[0] in {"'", '"'}:
                quote = value[0]
                if len(value) < 2 or value[-1] != quote:
                    raise publication.EnvContractError(
                        "environment file violates the one-key contract"
                    )
                value = value[1:-1]
            elif "'" in value or '"' in value:
                raise publication.EnvContractError(
                    "environment file violates the one-key contract"
                )
            if not value:
                raise publication.EnvContractError(
                    "environment file violates the one-key contract"
                )
            declarations.append(value)
    except UnicodeError as exc:
        raise publication.EnvContractError(
            "environment file violates the one-key contract"
        ) from exc
    finally:
        handle.close()
    if not declarations:
        raise publication.CredentialUnavailable("credential is unavailable")
    if len(declarations) != 1:
        raise publication.EnvContractError(
            "environment file violates the one-key contract"
        )
    target[publication.ENV_KEY] = declarations[0]
    return declarations[0]


def external_diagnostic(exc: Exception, *, stage: str) -> dict[str, str]:
    """Map external failures to the closed, sanitized diagnostic vocabulary."""

    name = type(exc).__name__
    detail = str(exc).casefold()
    if name in {"UserError", "AuthenticationError", "PermissionDeniedError"}:
        return publication.diagnostic(stage, name, "authentication_rejected")
    if name == "RateLimitError":
        return publication.diagnostic(stage, name, "rate_limited")
    if name == "ProxyError":
        return publication.diagnostic(stage, name, "proxy_unavailable")
    if name in {"APITimeoutError", "TimeoutException"}:
        return publication.diagnostic(stage, name, "timeout")
    if name in {"APIConnectionError", "ConnectError"}:
        return publication.diagnostic(stage, name, "network_unavailable")
    if name == "ModelAPIError":
        if "proxy" in detail or "socks" in detail:
            return publication.diagnostic(stage, name, "proxy_unavailable")
        if "timeout" in detail:
            return publication.diagnostic(stage, name, "timeout")
        if "connect" in detail or "network" in detail:
            return publication.diagnostic(stage, name, "network_unavailable")
        error_kind = "provider_request_failed" if stage == "request" else "provider_unavailable"
        return publication.diagnostic(stage, name, error_kind)
    if name == "ModelHTTPError":
        status_code = getattr(exc, "status_code", None)
        if status_code in {401, 403}:
            return publication.diagnostic(stage, name, "authentication_rejected")
        if status_code == 429:
            return publication.diagnostic(stage, name, "rate_limited")
        return publication.diagnostic(stage, name, "provider_request_failed")
    if name in {"ImportError", "ModuleNotFoundError"}:
        error_kind = (
            "proxy_unavailable"
            if "proxy" in detail or "socks" in detail
            else "runtime_dependency_unavailable"
        )
        return publication.diagnostic(stage, name, error_kind)
    if name == "OSError":
        return publication.diagnostic(stage, name, "runtime_dependency_unavailable")
    if name == "UnexpectedModelBehavior":
        return publication.diagnostic("response", name, "provider_response_invalid")
    return publication.diagnostic(
        stage, "ExternalRuntimeError", "unexpected_runtime_failure"
    )


def _failure_record(
    *,
    binding: Mapping[str, str],
    checks: dict[str, bool],
    item: Mapping[str, str],
    now: datetime | None,
) -> dict[str, object]:
    record = publication.build_evidence(
        source_binding=binding,
        classification=item["classification"],
        checks=checks,
        diagnostics=(item,),
        now=now,
    )
    publication.validate_evidence(record)
    return record


def _captured_failure(
    exc: Exception,
    *,
    stage: str,
    binding: Mapping[str, str],
    checks: dict[str, bool],
    secret: str,
    stdout: io.StringIO,
    stderr: io.StringIO,
    now: datetime | None,
    output_contract: bool = False,
) -> dict[str, object]:
    try:
        publication.assert_no_secret_material(stdout.getvalue(), exact_secret=secret)
        publication.assert_no_secret_material(stderr.getvalue(), exact_secret=secret)
    except publication.LocalContractError:
        item = publication.diagnostic(stage, "OutputContractError", "secret_detected")
    else:
        checks["secret_free"] = True
        item = (
            publication.diagnostic(stage, "OutputContractError", "output_contract_failed")
            if output_contract
            else external_diagnostic(exc, stage=stage)
        )
    return _failure_record(
        binding=binding, checks=checks, item=item, now=now
    )


def run_live_exercise(
    root: Path | None = None,
    *,
    timecopilot_factory: Callable[..., object] | None = None,
    forecaster_factory: Callable[[], object] | None = None,
    environ: MutableMapping[str, str] | None = None,
    env_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Execute the fixed request once and return a validated secret-free record."""

    active_root = (root or Path.cwd()).resolve()
    checks = publication.empty_checks()
    try:
        binding, context_rows = publication.load_validated_input(active_root)
        checks.update(
            dependency_gate_pass=True,
            input_window_valid=True,
            no_future_leakage=True,
        )
    except publication.DependencyGateError:
        checks["secret_free"] = True
        return _failure_record(
            binding=publication.fallback_source_binding(active_root),
            checks=checks,
            item=publication.diagnostic(
                "dependency_gate", "DependencyGateError", "prerequisite_not_pass"
            ),
            now=now,
        )
    except publication.InputContractError:
        checks["secret_free"] = True
        return _failure_record(
            binding=publication.fallback_source_binding(active_root),
            checks=checks,
            item=publication.diagnostic(
                "input", "InputContractError", "invalid_input_window"
            ),
            now=now,
        )

    try:
        secret = load_deepseek_api_key(
            env_path or active_root / ".env", environ=environ
        )
        checks["env_key_loaded"] = True
    except publication.CredentialUnavailable:
        checks["secret_free"] = True
        return _failure_record(
            binding=binding,
            checks=checks,
            item=publication.diagnostic(
                "credential", "CredentialUnavailable", "missing_credential"
            ),
            now=now,
        )
    except publication.EnvContractError:
        checks["secret_free"] = True
        return _failure_record(
            binding=binding,
            checks=checks,
            item=publication.diagnostic("credential", "EnvContractError", "malformed_env"),
            now=now,
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            frame = build_agent_frame(context_rows)
    except Exception as exc:
        return _captured_failure(
            exc, stage="dataframe_construction", binding=binding, checks=checks,
            secret=secret, stdout=stdout, stderr=stderr, now=now,
        )
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            if forecaster_factory is None:
                from timecopilot.models.foundation.chronos import Chronos

                forecaster_factory = lambda: Chronos(
                    repo_id=publication.REFERENCE_MODEL_ID, batch_size=1, alias="P105"
                )
            forecaster = forecaster_factory()
    except Exception as exc:
        return _captured_failure(
            exc, stage="forecaster_construction", binding=binding, checks=checks,
            secret=secret, stdout=stdout, stderr=stderr, now=now,
        )
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            if timecopilot_factory is None:
                from timecopilot import TimeCopilot

                timecopilot_factory = TimeCopilot
            agent = timecopilot_factory(
                llm=publication.REQUESTED_LLM, forecasters=[forecaster]
            )
    except Exception as exc:
        return _captured_failure(
            exc, stage="provider_resolution", binding=binding, checks=checks,
            secret=secret, stdout=stdout, stderr=stderr, now=now,
        )
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = cast(Any, agent).forecast(
                df=frame, h=3, freq="MS", seasonality=12, query=publication.QUERY
            )
    except Exception as exc:
        return _captured_failure(
            exc, stage="request", binding=binding, checks=checks, secret=secret,
            stdout=stdout, stderr=stderr, now=now,
        )
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            history = publication.extract_message_history(result)
            output = extract_analysis_output(result)
    except (publication.OutputContractError, AnalysisOutputError) as exc:
        return _captured_failure(
            exc, stage="response", binding=binding, checks=checks, secret=secret,
            stdout=stdout, stderr=stderr, now=now, output_contract=True,
        )

    calls = cast(list[str], history["tool_calls"])
    structured = history["structured_output_tool"]
    analysis = output.forecast_analysis
    response = output.user_query_response
    checks.update(
        provider_resolved=history["observed_provider"] == "deepseek",
        model_resolved=history["observed_model"] == "deepseek-v4-flash",
        provider_model_consistent=(
            history["observed_provider"] == "deepseek"
            and history["observed_model"] == "deepseek-v4-flash"
        ),
        required_tool_calls_exact=calls == list(publication.REQUIRED_TOOL_CALLS),
        analysis_nonempty=analysis is not None,
        query_response_nonempty=response is not None,
        query_anchors_present=publication.query_anchors_present(response),
    )
    failures: list[dict[str, str]] = []
    if history["response_count"] == 0 or not checks["provider_model_consistent"]:
        failures.append(
            publication.diagnostic(
                "response", "UnexpectedModelBehavior", "provider_response_invalid"
            )
        )
    if history["response_count"] != 0 and (
        structured != publication.DEFAULT_OUTPUT_TOOL_NAME
        or not checks["analysis_nonempty"]
        or not checks["query_response_nonempty"]
        or not checks["query_anchors_present"]
    ):
        failures.append(
            publication.diagnostic(
                "response", "OutputContractError", "output_contract_failed"
            )
        )
    record = publication.build_evidence(
        source_binding=binding,
        classification="fail" if failures else "pass",
        checks=checks,
        diagnostics=failures,
        observed_provider=cast(str | None, history["observed_provider"]),
        observed_model=cast(str | None, history["observed_model"]),
        tool_calls=calls,
        structured_output_tool=structured if isinstance(structured, str) else None,
        forecast_analysis=analysis,
        user_query_response=response,
        now=now,
    )
    try:
        publication.assert_no_secret_material(record, exact_secret=secret)
        publication.assert_no_secret_material(stdout.getvalue(), exact_secret=secret)
        publication.assert_no_secret_material(stderr.getvalue(), exact_secret=secret)
        checks["secret_free"] = True
    except publication.LocalContractError:
        return _failure_record(
            binding=binding,
            checks=checks,
            item=publication.diagnostic(
                "response", "OutputContractError", "secret_detected"
            ),
            now=now,
        )
    if not failures:
        checks["roadmap_eligible"] = True
    record["checks"] = dict(checks)
    publication.validate_evidence(record, exact_secret=secret)
    return record


def build_live_child_environment(
    runtime_dir: Path,
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the isolated runtime required before importing TimeCopilot."""

    source = dict(os.environ if environ is None else environ)
    try:
        configured = runtime_compatibility.configure_cuda_environment(source)
    except runtime_compatibility.RuntimePreflightError as exc:
        raise OSError("required runtime dependency is unavailable") from exc
    cache_dirs = {
        "MPLCONFIGDIR": runtime_dir.resolve() / "matplotlib",
        "HF_HOME": runtime_dir.resolve() / "huggingface",
        "TORCH_HOME": runtime_dir.resolve() / "torch",
        "XDG_CACHE_HOME": runtime_dir.resolve() / "xdg",
    }
    for path in cache_dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    configured.update({name: str(path) for name, path in cache_dirs.items()})
    configured["HF_HUB_CACHE"] = str(cache_dirs["HF_HOME"] / "hub")
    configured["PYTHONPATH"] = str((root / "src").resolve())
    configured[publication.RUNTIME_PREPARED_ENV] = "1"
    for name in ("ALL_PROXY", "all_proxy", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        configured.pop(name, None)
    return configured


def run_live_child(
    root: Path,
    *,
    publish: bool,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run the live exercise once in a prepared child process."""

    with tempfile.TemporaryDirectory(prefix="p1-08-runtime.", dir="/tmp") as directory:
        environment = build_live_child_environment(Path(directory), root, environ=environ)
        command = [
            sys.executable,
            "-m",
            "tools.workflows.natural_language_exercise",
            "--repo-root",
            str(root),
            "--live",
        ]
        if publish:
            command.append("--publish")
        completed = subprocess.run(command, cwd=root, env=environment, check=False)
    return completed.returncode
