"""Provider-configurable helpers for natural-language forecast analysis."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Collection, Mapping, Sequence, TypedDict, cast


class AnalysisOutputError(RuntimeError):
    """Raised when an agent result does not expose the required safe shape."""


class MessageHistory(TypedDict):
    """Sanitized observations extracted from an agent's message history."""

    tool_calls: list[str]
    structured_output_tool: str | None
    observed_provider: str | None
    observed_model: str | None
    response_count: int


@dataclass(frozen=True)
class AnalysisOutput:
    """Normalized natural-language fields returned by an analysis agent."""

    forecast_analysis: str | None
    user_query_response: str | None


def build_agent_frame(context_rows: Sequence[Any]) -> Any:
    """Convert target rows into the public ``unique_id / ds / y`` contract."""

    try:
        import pandas as pd
    except (ImportError, ModuleNotFoundError) as exc:
        raise ImportError("required runtime dependency is unavailable") from exc
    return pd.DataFrame(
        {
            "unique_id": [row.unique_id for row in context_rows],
            "ds": pd.to_datetime([row.ds.isoformat() for row in context_rows]),
            "y": [float(row.y) for row in context_rows],
        }
    )


def normalize_query_tokens(value: str) -> tuple[str, ...]:
    """Return NFKC-normalized, case-folded word tokens from query text."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(
        part
        for part in re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE).split(" ")
        if part
    )


def query_anchors_present(value: object, *, required_anchors: Collection[str]) -> bool:
    """Return whether text contains every explicitly supplied normalized anchor."""

    if not isinstance(value, str):
        return False
    tokens = set(normalize_query_tokens(value))
    anchors = {
        token
        for anchor in required_anchors
        for token in normalize_query_tokens(anchor)
    }
    return anchors.issubset(tokens)


def extract_message_history(
    result: object,
    *,
    expected_provider: str,
    expected_model: str,
    structured_output_tool: str,
) -> MessageHistory:
    """Extract tool names and canonical provider/model observations only."""

    canonical_provider = expected_provider.strip().casefold()
    canonical_model = _normalize_model(expected_model, canonical_provider)
    if not canonical_provider or not canonical_model or not structured_output_tool.strip():
        raise ValueError("message extraction configuration must be non-empty")

    try:
        all_messages = getattr(result, "all_messages", None)
        if not callable(all_messages):
            raise AnalysisOutputError("agent message history is unavailable")
        messages = all_messages()
        if not _is_object_sequence(messages):
            raise AnalysisOutputError("agent message history is unavailable")

        response_count = 0
        metadata_valid = True
        calls: list[str] = []
        for message in cast(Sequence[object], messages):
            if _is_invalid_object(message):
                raise AnalysisOutputError("agent message history is unavailable")
            kind = getattr(message, "kind", None)
            parts = getattr(message, "parts", None)
            if not isinstance(kind, str) or not kind or not _is_object_sequence(parts):
                raise AnalysisOutputError("agent message history is unavailable")
            for part in cast(Sequence[object], parts):
                if _is_invalid_object(part):
                    raise AnalysisOutputError("agent message history is unavailable")
                part_kind = getattr(part, "part_kind", None)
                if not isinstance(part_kind, str) or not part_kind:
                    raise AnalysisOutputError("agent message history is unavailable")
                if kind == "response" and part_kind == "tool-call":
                    name = getattr(part, "tool_name", None)
                    if not isinstance(name, str) or not name.strip():
                        raise AnalysisOutputError("agent message history is unavailable")
                    calls.append(name.strip())
            if kind != "response":
                continue
            response_count += 1
            provider = getattr(message, "provider_name", None)
            model = getattr(message, "model_name", None)
            if not isinstance(provider, str) or not isinstance(model, str):
                metadata_valid = False
            elif (
                provider.strip().casefold() != canonical_provider
                or _normalize_model(model, canonical_provider) != canonical_model
            ):
                metadata_valid = False

        observed_provider: str | None
        observed_model: str | None
        if response_count == 0 or not metadata_valid:
            observed_provider = None
            observed_model = None
        else:
            observed_provider = canonical_provider
            observed_model = canonical_model

        output_tool = structured_output_tool.strip()
        observed_output_tool = output_tool if calls.count(output_tool) == 1 else None
        return {
            "tool_calls": [name for name in calls if name != observed_output_tool],
            "structured_output_tool": observed_output_tool,
            "observed_provider": observed_provider,
            "observed_model": observed_model,
            "response_count": response_count,
        }
    except AnalysisOutputError:
        raise
    except Exception:
        raise AnalysisOutputError("agent message history is unavailable") from None


def extract_analysis_output(
    result: object,
    *,
    analysis_field: str = "forecast_analysis",
    response_field: str = "user_query_response",
) -> AnalysisOutput:
    """Read and whitespace-normalize the configured structured output fields."""

    if not analysis_field or not response_field:
        raise ValueError("analysis output field names must be non-empty")
    try:
        output = getattr(result, "output", None)
        analysis = _nonempty_text(getattr(output, analysis_field, None))
        response = _nonempty_text(getattr(output, response_field, None))
    except Exception:
        raise AnalysisOutputError("agent structured output is unavailable") from None
    return AnalysisOutput(
        forecast_analysis=analysis,
        user_query_response=response,
    )


def _normalize_model(value: str, provider: str) -> str:
    normalized = value.strip().casefold()
    prefix = f"{provider}:"
    return normalized[len(prefix):] if normalized.startswith(prefix) else normalized


def _is_object_sequence(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and not isinstance(value, Mapping)
    )


def _is_invalid_object(value: object) -> bool:
    return value is None or isinstance(
        value, (str, bytes, bytearray, Mapping, int, float, bool)
    )


def _nonempty_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
