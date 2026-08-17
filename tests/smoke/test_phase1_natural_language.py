from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast

import pytest

from commodity_forecasting.phase1 import natural_language as subject


NOW = datetime(2026, 8, 17, 6, 7, 8, tzinfo=timezone.utc)


def _binding() -> dict[str, str]:
    return {
        "p1_06_evidence_path": "docs/findings/phase1/evidence/rolling_origin.json",
        "p1_06_run_id": "P1-06-20260816142818Z",
        "p1_06_classification": "pass",
        "p1_06_marker_state": "pass_final",
        "p1_06_reference_model_id": "autogluon/chronos-2-small",
        "p1_07_evidence_path": "docs/findings/phase1/evidence/evaluation.json",
        "p1_07_run_id": "P1-07-20260816T154620Z",
        "p1_07_classification": "pass",
        "p1_07_source_p1_06_run_id": "P1-06-20260816142818Z",
        "target_path": "data/model_ready/world_bank_pink_sheet_monthly_arabica/target.csv",
    }


class FakePart:
    part_kind = "tool-call"

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self.args = {"not": "recorded"}


class FakeResponse:
    kind = "response"

    def __init__(
        self,
        calls: list[str],
        *,
        provider_name: str | None = " DeepSeek ",
        model_name: str | None = "deepseek:DeepSeek-V4-Flash",
    ) -> None:
        self.parts = [FakePart(name) for name in calls]
        self.provider_name = provider_name
        self.model_name = model_name
        self.provider_details = {"authorization": "must not be recorded"}


class FakeResult:
    _output_tool_name = "final_result"

    def __init__(self, messages: list[object] | None = None) -> None:
        default_messages: list[object] = [
            FakeResponse([subject.REQUIRED_TOOL_CALLS[0]]),
            FakeResponse([subject.REQUIRED_TOOL_CALLS[1]]),
            FakeResponse([subject.REQUIRED_TOOL_CALLS[2]]),
            FakeResponse([subject.REQUIRED_TOOL_CALLS[3], "final_result"]),
        ]
        self._messages = messages if messages is not None else default_messages
        self.output = SimpleNamespace(
            forecast_analysis="A non-empty historical-pattern and uncertainty analysis.",
            user_query_response=(
                "Coffee Arabica history through April 2026 informs the May, June, and July outlook."
            ),
        )

    def all_messages(self) -> list[object]:
        return self._messages


class FakeAgent:
    def __init__(self, result: object | BaseException) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def forecast(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _pass_record() -> dict[str, object]:
    return subject.build_evidence(
        source_binding=_binding(),
        classification="pass",
        checks={key: True for key in subject.CHECK_KEYS},
        diagnostics=(),
        observed_provider="deepseek",
        observed_model="deepseek-v4-flash",
        tool_calls=subject.REQUIRED_TOOL_CALLS,
        structured_output_tool="final_result",
        forecast_analysis="History shows a pattern and uncertainty.",
        user_query_response="Coffee Arabica April 2026 outlook for May June July.",
        now=NOW,
    )


def _nonpass_checks(stage: str) -> dict[str, bool]:
    checks = {key: False for key in subject.CHECK_KEYS}
    checks["secret_free"] = True
    if stage == "credential":
        checks.update(
            dependency_gate_pass=True,
            input_window_valid=True,
            no_future_leakage=True,
        )
    elif stage not in {"dependency_gate", "input"}:
        checks.update(
            dependency_gate_pass=True,
            env_key_loaded=True,
            input_window_valid=True,
            no_future_leakage=True,
        )
    return checks


def _diagnostics(record: dict[str, object]) -> list[dict[str, str]]:
    return cast(list[dict[str, str]], record["diagnostics"])


def _source_binding(record: dict[str, object]) -> dict[str, str]:
    return cast(dict[str, str], record["source_binding"])


def test_loader_prefers_existing_value_without_reading_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.env"
    environ = {subject.ENV_KEY: " existing value "}
    assert subject.load_deepseek_api_key(missing, environ=environ) == " existing value "
    assert environ == {subject.ENV_KEY: " existing value "}


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("  export   DEEPSEEK_API_KEY  =  value#kept  \n", "value#kept"),
        ("DEEPSEEK_API_KEY='  quoted value  '\n", "  quoted value  "),
        ('DEEPSEEK_API_KEY = "two=parts"\n', "two=parts"),
        ("OTHER=value\nDEEPSEEK_API_KEY=chosen\n", "chosen"),
    ],
)
def test_loader_accepts_only_the_exact_one_key(
    tmp_path: Path, content: str, expected: str
) -> None:
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    environ = {"OTHER": "untouched"}
    assert subject.load_deepseek_api_key(path, environ=environ) == expected
    assert environ == {"OTHER": "untouched", subject.ENV_KEY: expected}


@pytest.mark.parametrize(
    "content",
    [
        "DEEPSEEK_API_KEY\n",
        "DEEPSEEK_API_KEY=\n",
        "DEEPSEEK_API_KEY=one\nDEEPSEEK_API_KEY=two\n",
        "DEEPSEEK_API_KEY='unterminated\n",
        "DEEPSEEK_API_KEY='closed' trailing\n",
        'DEEPSEEK_API_KEY=unquoted"quote\n',
    ],
)
def test_loader_rejects_malformed_declarations(tmp_path: Path, content: str) -> None:
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(subject.EnvContractError):
        subject.load_deepseek_api_key(path, environ={})


def test_loader_missing_file_or_key_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(subject.CredentialUnavailable):
        subject.load_deepseek_api_key(tmp_path / "missing", environ={})
    path = tmp_path / ".env"
    path.write_text("OTHER=value\n", encoding="utf-8")
    with pytest.raises(subject.CredentialUnavailable):
        subject.load_deepseek_api_key(path, environ={})


def test_history_extraction_uses_all_responses_and_records_no_raw_metadata() -> None:
    extracted = subject.extract_message_history(FakeResult())
    assert extracted == {
        "tool_calls": list(subject.REQUIRED_TOOL_CALLS),
        "structured_output_tool": "final_result",
        "observed_provider": "deepseek",
        "observed_model": "deepseek-v4-flash",
        "response_count": 4,
    }
    assert "provider_details" not in extracted
    assert "args" not in extracted


def test_private_output_declaration_without_observed_final_call_does_not_pass() -> None:
    result = FakeResult([FakeResponse(list(subject.REQUIRED_TOOL_CALLS))])
    extracted = subject.extract_message_history(result)
    assert extracted["structured_output_tool"] is None
    assert extracted["tool_calls"] == list(subject.REQUIRED_TOOL_CALLS)


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [FakeResponse([], provider_name=None)],
        [FakeResponse([], model_name=None)],
        [FakeResponse([], provider_name="other")],
        [FakeResponse([], model_name="other")],
        [FakeResponse([]), FakeResponse([], model_name="other")],
    ],
)
def test_history_extraction_fails_closed_on_provider_metadata(
    messages: list[object],
) -> None:
    extracted = subject.extract_message_history(FakeResult(messages))
    assert extracted["observed_provider"] is None
    assert extracted["observed_model"] is None


@pytest.mark.parametrize(
    "history",
    [None, "raw-secret", {"message": "raw-secret"}, [None], ["raw-secret"], [{}], [7]],
)
def test_history_extraction_rejects_malformed_history_shapes(history: object) -> None:
    class MalformedHistoryResult:
        def all_messages(self) -> object:
            return history

    with pytest.raises(subject.OutputContractError) as caught:
        subject.extract_message_history(MalformedHistoryResult())
    assert str(caught.value) == "agent message history is unavailable"
    assert "raw-secret" not in str(caught.value)


@pytest.mark.parametrize("parts", [None, "raw-secret", {"part": "raw-secret"}, [None], ["raw-secret"], [{}], [7]])
def test_history_extraction_rejects_missing_or_invalid_parts(parts: object) -> None:
    message = SimpleNamespace(
        kind="response",
        parts=parts,
        provider_name="deepseek",
        model_name="deepseek-v4-flash",
    )
    with pytest.raises(subject.OutputContractError) as caught:
        subject.extract_message_history(FakeResult(cast(list[object], [message])))
    assert str(caught.value) == "agent message history is unavailable"
    assert "raw-secret" not in str(caught.value)


def test_query_anchor_normalization_is_nfkc_casefolded_and_punctuation_agnostic() -> None:
    assert subject.query_anchors_present(
        "ＣＯＦＦＥＥ / ARABICA: APRIL—2026; MAY, JUNE & JULY"
    )
    assert not subject.query_anchors_present("Coffee Arabica April 2026 May June")


def test_secret_guard_rejects_exact_and_generic_material() -> None:
    subject.assert_no_secret_material("token is discussed without an assignment")
    with pytest.raises(subject.LocalContractError):
        subject.assert_no_secret_material("authorization: Bearer value")
    with pytest.raises(subject.LocalContractError):
        subject.assert_no_secret_material("otherwise safe", exact_secret="safe")


def test_evidence_schema_rejects_extra_keys_and_mixed_diagnostic_classification() -> None:
    record = _pass_record()
    subject.validate_evidence(record)
    record["extra"] = True
    with pytest.raises(subject.LocalContractError):
        subject.validate_evidence(record)
    blocked = subject.build_evidence(
        source_binding=_binding(),
        classification="blocked",
        checks=_nonpass_checks("credential"),
        diagnostics=(subject.diagnostic("credential", "CredentialUnavailable", "missing_credential"),),
        now=NOW,
    )
    blocked["diagnostics"][0]["error_kind"] = "tool_contract_failed"  # type: ignore[index]
    with pytest.raises(subject.LocalContractError):
        subject.validate_evidence(blocked)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_provider", "other"),
        ("observed_model", "other"),
        ("structured_output_tool", "other"),
        ("tool_calls", list(reversed(subject.REQUIRED_TOOL_CALLS))),
        ("forecast_analysis", None),
        ("user_query_response", "Coffee Arabica April 2026 May June"),
    ],
)
def test_pass_validation_derives_invariants_instead_of_trusting_checks(
    field: str, value: object
) -> None:
    record = _pass_record()
    record[field] = value
    with pytest.raises(subject.LocalContractError):
        subject.validate_evidence(record)


def test_nonpass_validation_rejects_forged_derived_check() -> None:
    item = subject.diagnostic("response", "OutputContractError", "output_contract_failed")
    record = subject.build_evidence(
        source_binding=_binding(),
        classification="fail",
        checks=_nonpass_checks("response"),
        diagnostics=(item,),
        observed_provider="deepseek",
        now=NOW,
    )
    with pytest.raises(subject.LocalContractError):
        subject.validate_evidence(record)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_provider", "other-provider"),
        ("observed_model", "other-model"),
        ("structured_output_tool", "other-output-tool"),
    ],
)
def test_nonpass_validation_rejects_unknown_observation_domains(field: str, value: object) -> None:
    item = subject.diagnostic("credential", "CredentialUnavailable", "missing_credential")
    record = subject.build_evidence(
        source_binding=_binding(),
        classification="blocked",
        checks=_nonpass_checks("credential"),
        diagnostics=(item,),
        now=NOW,
    )
    record[field] = value
    with pytest.raises(subject.LocalContractError):
        subject.validate_evidence(record)


def test_live_runner_calls_forecast_exactly_once_with_fixed_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subject, "load_validated_input", lambda root: (_binding(), (object(),)))
    monkeypatch.setattr(subject, "build_agent_frame", lambda rows: "history-only-frame")
    agent = FakeAgent(FakeResult())
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> FakeAgent:
        captured.update(kwargs)
        return agent

    record = subject.run_live_exercise(
        tmp_path,
        timecopilot_factory=factory,
        forecaster_factory=lambda: "chronos",
        environ={subject.ENV_KEY: "test-only-exact-secret"},
        now=NOW,
    )
    assert record["classification"] == "pass"
    assert captured == {"llm": "deepseek:deepseek-v4-flash", "forecasters": ["chronos"]}
    assert len(agent.calls) == 1
    assert agent.calls[0] == {
        "df": "history-only-frame",
        "h": 3,
        "freq": "MS",
        "seasonality": 12,
        "query": subject.QUERY,
    }


def test_success_with_zero_model_responses_is_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subject, "load_validated_input", lambda root: (_binding(), (object(),)))
    monkeypatch.setattr(subject, "build_agent_frame", lambda rows: "frame")
    record = subject.run_live_exercise(
        tmp_path,
        timecopilot_factory=lambda **kwargs: FakeAgent(FakeResult([])),
        forecaster_factory=lambda: "chronos",
        environ={subject.ENV_KEY: "test-secret"},
        now=NOW,
    )
    assert record["classification"] == "fail"
    assert record["observed_provider"] is None
    assert record["observed_model"] is None
    assert [item["error_kind"] for item in _diagnostics(record)] == [
        "provider_response_invalid",
    ]
    assert cast(dict[str, bool], record["checks"])["secret_free"] is True
    subject.validate_evidence(record, exact_secret="test-secret")


@pytest.mark.parametrize(
    ("emit_secret", "expected_error", "expected_secret_free"),
    [
        (False, "output_contract_failed", True),
        (True, "secret_detected", False),
    ],
)
def test_exploding_output_accessor_is_a_sanitized_response_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    emit_secret: bool,
    expected_error: str,
    expected_secret_free: bool,
) -> None:
    monkeypatch.setattr(subject, "load_validated_input", lambda root: (_binding(), (object(),)))
    monkeypatch.setattr(subject, "build_agent_frame", lambda rows: "frame")

    class ExplodingOutputResult:
        def all_messages(self) -> list[object]:
            return FakeResult().all_messages()

        @property
        def output(self) -> object:
            if emit_secret:
                print("test-secret")
            raise RuntimeError("raw output accessor detail")

    record = subject.run_live_exercise(
        tmp_path,
        timecopilot_factory=lambda **kwargs: FakeAgent(ExplodingOutputResult()),
        forecaster_factory=lambda: "chronos",
        environ={subject.ENV_KEY: "test-secret"},
        now=NOW,
    )
    assert record["classification"] == "fail"
    assert _diagnostics(record)[0]["error_kind"] == expected_error
    assert cast(dict[str, bool], record["checks"])["secret_free"] is expected_secret_free
    assert "raw output accessor detail" not in json.dumps(record)
    assert "test-secret" not in json.dumps(record)
    subject.validate_evidence(record, exact_secret="test-secret")


def test_input_failure_returns_publishable_fail_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subject,
        "load_validated_input",
        lambda root: (_ for _ in ()).throw(subject.InputContractError("raw detail")),
    )
    record = subject.run_live_exercise(tmp_path, environ={}, now=NOW)
    assert record["classification"] == "fail"
    assert _diagnostics(record)[0]["error_kind"] == "invalid_input_window"
    assert _source_binding(record)["p1_06_classification"] == "unavailable"
    assert _source_binding(record)["p1_07_classification"] == "unavailable"
    subject.validate_evidence(record)


def test_malformed_message_iterable_returns_publishable_fail_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subject, "load_validated_input", lambda root: (_binding(), (object(),)))
    monkeypatch.setattr(subject, "build_agent_frame", lambda rows: "frame")

    class MalformedResult:
        output = SimpleNamespace()

        def all_messages(self) -> None:
            return None

    record = subject.run_live_exercise(
        tmp_path,
        timecopilot_factory=lambda **kwargs: FakeAgent(MalformedResult()),
        forecaster_factory=lambda: "chronos",
        environ={subject.ENV_KEY: "test-secret"},
        now=NOW,
    )
    assert record["classification"] == "fail"
    assert _diagnostics(record)[0]["error_kind"] == "output_contract_failed"


@pytest.mark.parametrize(
    ("failing_component", "expected_stage", "expected_classification", "expected_error"),
    [
        (
            "dataframe",
            "dataframe_construction",
            "fail",
            "unexpected_runtime_failure",
        ),
        (
            "forecaster",
            "forecaster_construction",
            "fail",
            "unexpected_runtime_failure",
        ),
        ("provider", "provider_resolution", "fail", "unexpected_runtime_failure"),
    ],
)
def test_setup_failures_report_their_exact_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failing_component: str,
    expected_stage: str,
    expected_classification: str,
    expected_error: str,
) -> None:
    monkeypatch.setattr(subject, "load_validated_input", lambda root: (_binding(), (object(),)))

    def fail_if(component: str) -> object:
        if failing_component == component:
            raise RuntimeError("raw setup detail")
        return "frame" if component == "dataframe" else "chronos"

    monkeypatch.setattr(subject, "build_agent_frame", lambda rows: fail_if("dataframe"))

    def provider_factory(**kwargs: object) -> FakeAgent:
        if failing_component == "provider":
            raise RuntimeError("raw setup detail")
        return FakeAgent(FakeResult())

    record = subject.run_live_exercise(
        tmp_path,
        timecopilot_factory=provider_factory,
        forecaster_factory=lambda: fail_if("forecaster"),
        environ={subject.ENV_KEY: "test-secret"},
        now=NOW,
    )
    assert record["classification"] == expected_classification
    assert _diagnostics(record)[0]["stage"] == expected_stage
    assert _diagnostics(record)[0]["error_kind"] == expected_error


def test_message_extraction_failure_returns_publishable_fail_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subject, "load_validated_input", lambda root: (_binding(), (object(),)))
    monkeypatch.setattr(subject, "build_agent_frame", lambda rows: "frame")
    result = SimpleNamespace(output=SimpleNamespace())
    record = subject.run_live_exercise(
        tmp_path,
        timecopilot_factory=lambda **kwargs: FakeAgent(result),
        forecaster_factory=lambda: "chronos",
        environ={subject.ENV_KEY: "test-secret"},
        now=NOW,
    )
    assert record["classification"] == "fail"
    assert _diagnostics(record)[0]["error_kind"] == "output_contract_failed"


def test_external_failure_remains_blocked_without_metadata_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class APIConnectionError(Exception):
        pass

    monkeypatch.setattr(subject, "load_validated_input", lambda root: (_binding(), (object(),)))
    monkeypatch.setattr(subject, "build_agent_frame", lambda rows: "frame")
    record = subject.run_live_exercise(
        tmp_path,
        timecopilot_factory=lambda **kwargs: FakeAgent(APIConnectionError("raw secret")),
        forecaster_factory=lambda: "chronos",
        environ={subject.ENV_KEY: "test-secret"},
        now=NOW,
    )
    assert record["classification"] == "blocked"
    assert [item["error_kind"] for item in _diagnostics(record)] == ["network_unavailable"]


def test_socks_proxy_import_failure_is_classified_as_proxy_blocked() -> None:
    item = subject._external_diagnostic(
        ImportError("Using SOCKS proxy, but the 'socksio' package is not installed."),
        stage="provider_resolution",
    )
    assert item == {
        "classification": "blocked",
        "stage": "provider_resolution",
        "exception_class": "ImportError",
        "error_kind": "proxy_unavailable",
        "sanitized_reason": "configured proxy blocked the provider request.",
    }


def test_unclassified_model_api_request_failure_is_neutral_and_blocked() -> None:
    class ModelAPIError(Exception):
        pass

    item = subject._external_diagnostic(
        ModelAPIError("provider request failed"),
        stage="request",
    )
    assert item == {
        "classification": "blocked",
        "stage": "request",
        "exception_class": "ModelAPIError",
        "error_kind": "provider_request_failed",
        "sanitized_reason": "provider request failed for an unclassified external reason.",
    }


@pytest.mark.parametrize(
    ("status_code", "error_kind"),
    [
        (401, "authentication_rejected"),
        (403, "authentication_rejected"),
        (429, "rate_limited"),
        (500, "provider_request_failed"),
        (None, "provider_request_failed"),
    ],
)
def test_model_http_error_is_classified_by_status(
    status_code: int | None, error_kind: str
) -> None:
    class ModelHTTPError(Exception):
        def __init__(self, status: int | None) -> None:
            super().__init__("provider response")
            self.status_code = status

    item = subject._external_diagnostic(ModelHTTPError(status_code), stage="request")
    assert item["exception_class"] == "ModelHTTPError"
    assert item["error_kind"] == error_kind


@pytest.mark.parametrize(
    ("exception", "stage"),
    [
        (RuntimeError("raw secret"), "request"),
        (AttributeError("raw secret"), "provider_resolution"),
        (RuntimeError("raw secret"), "dataframe_construction"),
    ],
)
def test_unknown_runtime_families_are_sanitized_failures(
    exception: Exception, stage: str
) -> None:
    item = subject._external_diagnostic(exception, stage=stage)
    assert item == {
        "classification": "fail",
        "stage": stage,
        "exception_class": "ExternalRuntimeError",
        "error_kind": "unexpected_runtime_failure",
        "sanitized_reason": "an unexpected runtime failure prevented the run.",
    }
    assert "raw secret" not in json.dumps(item)


def test_recorded_forecaster_oserror_mapping_remains_dependency_blocked() -> None:
    assert subject._external_diagnostic(OSError("raw secret"), stage="forecaster_construction") == {
        "classification": "blocked",
        "stage": "forecaster_construction",
        "exception_class": "OSError",
        "error_kind": "runtime_dependency_unavailable",
        "sanitized_reason": "required runtime dependency is unavailable.",
    }


def test_provider_setup_oserror_is_not_mislabeled_as_provider_outage() -> None:
    item = subject._external_diagnostic(OSError("raw secret"), stage="provider_resolution")
    assert item["error_kind"] == "runtime_dependency_unavailable"
    assert item["error_kind"] != "provider_unavailable"


@pytest.mark.parametrize(
    ("stage", "forged_key"),
    [
        ("dependency_gate", "dependency_gate_pass"),
        ("credential", "env_key_loaded"),
        ("input", "input_window_valid"),
        ("input", "no_future_leakage"),
    ],
)
def test_nonpass_validation_rejects_forged_prerequisite_checks(
    stage: str, forged_key: str
) -> None:
    diagnostic_by_stage = {
        "dependency_gate": subject.diagnostic(
            "dependency_gate", "DependencyGateError", "prerequisite_not_pass"
        ),
        "credential": subject.diagnostic(
            "credential", "CredentialUnavailable", "missing_credential"
        ),
        "input": subject.diagnostic("input", "InputContractError", "invalid_input_window"),
    }
    checks = _nonpass_checks(stage)
    checks[forged_key] = not checks[forged_key]
    classification = cast(str, diagnostic_by_stage[stage]["classification"])
    record = subject.build_evidence(
        source_binding=_binding(),
        classification=classification,
        checks=checks,
        diagnostics=(diagnostic_by_stage[stage],),
        now=NOW,
    )
    with pytest.raises(subject.LocalContractError, match="prerequisite checks"):
        subject.validate_evidence(record)


def test_validation_rejects_secret_free_check_that_disagrees_with_diagnostic() -> None:
    checks = _nonpass_checks("response")
    checks["secret_free"] = False
    record = subject.build_evidence(
        source_binding=_binding(),
        classification="fail",
        checks=checks,
        diagnostics=(subject.diagnostic("response", "OutputContractError", "output_contract_failed"),),
        now=NOW,
    )
    with pytest.raises(subject.LocalContractError, match="secret-free check"):
        subject.validate_evidence(record)


def test_publication_is_canonical_and_roadmap_is_pass_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subject, "load_validated_input", lambda root: (_binding(), (object(),)))
    roadmap = "# Roadmap\n\n- [ ] **P1-08 — Natural-language exercise.**\n"
    (tmp_path / "docs").mkdir()
    (tmp_path / subject.ROADMAP_RELATIVE_PATH).write_text(roadmap, encoding="utf-8")
    record = _pass_record()
    subject.publish_bundle(record, tmp_path)
    assert subject.validate_publication(tmp_path) == record
    assert not subject.check_roadmap(tmp_path)
    subject.update_roadmap(tmp_path)
    assert subject.check_roadmap(tmp_path)
    assert json.loads((tmp_path / subject.EVIDENCE_RELATIVE_PATH).read_text())["classification"] == "pass"


def test_publication_rolls_back_first_replacement_when_second_fails(tmp_path: Path) -> None:
    destination_markdown = tmp_path / subject.FINDING_RELATIVE_PATH
    destination_evidence = tmp_path / subject.EVIDENCE_RELATIVE_PATH
    destination_markdown.parent.mkdir(parents=True)
    destination_evidence.parent.mkdir(parents=True)
    old_record = subject.build_evidence(
        source_binding=_binding(),
        classification="blocked",
        checks=_nonpass_checks("credential"),
        diagnostics=(subject.diagnostic("credential", "CredentialUnavailable", "missing_credential"),),
        now=NOW,
    )
    destination_markdown.write_text(subject.render_markdown(old_record), encoding="utf-8")
    destination_evidence.write_text(
        json.dumps(old_record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    old_markdown = destination_markdown.read_bytes()
    old_evidence = destination_evidence.read_bytes()
    new_record = subject.build_evidence(
        source_binding=_binding(),
        classification="blocked",
        checks=_nonpass_checks("credential"),
        diagnostics=(subject.diagnostic("credential", "CredentialUnavailable", "missing_credential"),),
        now=NOW + timedelta(seconds=1),
    )
    replacement_count = 0

    def fail_second_replacement(source: Path, destination: Path) -> None:
        nonlocal replacement_count
        replacement_count += 1
        if replacement_count == 2:
            raise OSError("simulated second replacement failure")
        subject.os.replace(source, destination)

    replacement = cast(Callable[[Path, Path], None], fail_second_replacement)
    with pytest.raises(subject.PublicationError):
        subject.publish_bundle(new_record, tmp_path, replace_file=replacement)
    assert destination_markdown.read_bytes() == old_markdown
    assert destination_evidence.read_bytes() == old_evidence


def test_publication_cleans_first_temp_when_second_staging_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = subject.build_evidence(
        source_binding=_binding(),
        classification="blocked",
        checks=_nonpass_checks("credential"),
        diagnostics=(subject.diagnostic("credential", "CredentialUnavailable", "missing_credential"),),
        now=NOW,
    )
    real_stage_bytes = subject._stage_bytes
    stage_count = 0

    def fail_second_stage(destination: Path, payload: bytes) -> Path:
        nonlocal stage_count
        stage_count += 1
        if stage_count == 2:
            raise OSError("simulated second staging failure")
        return real_stage_bytes(destination, payload)

    monkeypatch.setattr(subject, "_stage_bytes", fail_second_stage)
    with pytest.raises(subject.PublicationError):
        subject.publish_bundle(record, tmp_path)
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_staging_cleans_up_when_control_flow_exception_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "artifact.json"
    monkeypatch.setattr(subject.os, "fsync", lambda fd: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        subject._stage_bytes(destination, b"payload")
    assert list(tmp_path.iterdir()) == []


def test_nonpass_publication_stays_unchecked_and_cannot_update_roadmap(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / subject.ROADMAP_RELATIVE_PATH).write_text(
        "- [ ] **P1-08 — Natural-language exercise.**\n", encoding="utf-8"
    )
    item = subject.diagnostic("credential", "CredentialUnavailable", "missing_credential")
    record = subject.build_evidence(
        source_binding=_binding(),
        classification="blocked",
        checks=_nonpass_checks("credential"),
        diagnostics=(item,),
        now=NOW,
    )
    subject.publish_bundle(record, tmp_path)
    assert subject.check_roadmap(tmp_path)
    with pytest.raises(subject.PublicationError):
        subject.update_roadmap(tmp_path)


def test_pass_publication_rejects_stale_prerequisite_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subject, "load_validated_input", lambda root: (_binding(), (object(),)))
    subject.publish_bundle(_pass_record(), tmp_path)
    stale = _binding()
    stale["p1_07_run_id"] = "P1-07-newer"
    monkeypatch.setattr(subject, "load_validated_input", lambda root: (stale, (object(),)))
    with pytest.raises(subject.PublicationError):
        subject.validate_publication(tmp_path)


def test_cli_nonpass_publishes_and_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item = subject.diagnostic("credential", "CredentialUnavailable", "missing_credential")
    record = subject.build_evidence(
        source_binding=_binding(),
        classification="blocked",
        checks=_nonpass_checks("credential"),
        diagnostics=(item,),
        now=NOW,
    )
    monkeypatch.setattr(subject, "run_live_exercise", lambda root: record)
    published: list[object] = []
    monkeypatch.setattr(subject, "publish_bundle", lambda value, root: published.append(value))
    monkeypatch.setenv(subject.RUNTIME_PREPARED_ENV, "1")
    assert subject.main(["--repo-root", str(tmp_path), "--live", "--publish"]) == 1
    assert published == [record]


def test_live_parent_delegates_to_one_prepared_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[Path, bool]] = []

    def run_live_child(root: Path, *, publish: bool) -> int:
        calls.append((root, publish))
        return 7

    monkeypatch.delenv(subject.RUNTIME_PREPARED_ENV, raising=False)
    monkeypatch.setattr(subject, "run_live_child", run_live_child)
    monkeypatch.setattr(
        subject,
        "run_live_exercise",
        lambda root: pytest.fail("parent must not execute the credentialed exercise"),
    )

    assert subject.main(["--repo-root", str(tmp_path), "--live", "--publish"]) == 7
    assert calls == [(tmp_path.resolve(), True)]


def test_live_child_environment_is_cuda_ready_and_proxy_scoped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cuda_home = tmp_path / "cuda"

    def configure(environment: dict[str, str]) -> dict[str, str]:
        configured = dict(environment)
        configured.update(
            {
                "CUDA_HOME": str(cuda_home),
                "P1_05_CUDA_HOME": str(cuda_home),
                "PATH": f"{cuda_home / 'bin'}:/usr/bin",
                "LD_LIBRARY_PATH": str(cuda_home / "lib"),
            }
        )
        configured.pop("CUDA_VISIBLE_DEVICES", None)
        return configured

    monkeypatch.setattr(subject.runtime_compatibility, "configure_cuda_environment", configure)
    source = {
        "HTTP_PROXY": "http://http-proxy.invalid",
        "HTTPS_PROXY": "http://https-proxy.invalid",
        "ALL_PROXY": "socks5://socks-proxy.invalid",
        "all_proxy": "socks5://socks-proxy.invalid",
        "CUDA_VISIBLE_DEVICES": "0",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }

    environment = subject.build_live_child_environment(
        tmp_path / "runtime",
        tmp_path,
        environ=source,
    )

    assert environment["CUDA_HOME"] == str(cuda_home)
    assert environment["P1_05_CUDA_HOME"] == str(cuda_home)
    assert environment["HTTP_PROXY"] == source["HTTP_PROXY"]
    assert environment["HTTPS_PROXY"] == source["HTTPS_PROXY"]
    assert "ALL_PROXY" not in environment
    assert "all_proxy" not in environment
    assert "CUDA_VISIBLE_DEVICES" not in environment
    assert "HF_HUB_OFFLINE" not in environment
    assert "TRANSFORMERS_OFFLINE" not in environment
    assert environment[subject.RUNTIME_PREPARED_ENV] == "1"
    assert environment["PYTHONPATH"] == str((tmp_path / "src").resolve())
    for name in ("MPLCONFIGDIR", "HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME"):
        assert Path(environment[name]).is_dir()


def test_configured_child_imports_real_chronos_on_cuda_path(tmp_path: Path) -> None:
    if subject.runtime_compatibility.find_cuda_home() is None:
        pytest.skip("verified CUDA toolkit is unavailable")
    root = Path(__file__).resolve().parents[2]
    source = {name: value for name, value in os.environ.items() if name != subject.ENV_KEY}
    environment = subject.build_live_child_environment(
        tmp_path / "runtime",
        root,
        environ=source,
    )
    script = (
        "from pathlib import Path; "
        "import torch; "
        "torch.cuda.is_available=lambda: True; "
        "from commodity_forecasting.phase1.natural_language import "
        "build_agent_frame, load_validated_input; "
        "_, rows=load_validated_input(Path.cwd()); "
        "frame=build_agent_frame(rows); "
        "from timecopilot import TimeCopilot; "
        "from timecopilot.models.foundation.chronos import Chronos; "
        "forecaster=Chronos(repo_id='autogluon/chronos-2-small', batch_size=1, alias='P105'); "
        "assert len(frame) == 60; "
        "assert TimeCopilot.__name__ == 'TimeCopilot'; "
        "assert type(forecaster).__name__ == 'Chronos'"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert subject.ENV_KEY not in completed.stdout
    assert subject.ENV_KEY not in completed.stderr
