# Phase 0 Evidence Schema

Phase 0 evidence records are compact JSON objects. They record behavior observed from deterministic tests or credential/network smoke tests without storing raw provider payloads, credentials, or real Coffee C data.

Required fields:

- `run_id`
- `test_id`
- `work_item`
- `timestamp_utc`
- `mode`
- `command`
- `tool`
- `timecopilot_version`
- `model_or_adapter`
- `fixture_id`
- `data_origin`
- `credential_state`
- `network_state`
- `observed_result`
- `classification`
- `leakage_controls`
- `artifact_paths`

Allowed `classification` values are `pass`, `fail`, `blocked`, and `unsupported`.

For `SM-01`, records must also include `model_native_capability`, `adapter_exposure`, and `gate_result`. The covariate smoke-test gate result must be one of `native_path_selected`, `adapter_gap_proven`, `model_unsupported`, or `blocked_or_unknown`.

For `SM-02`, records must also include `model_native_capability`, `adapter_exposure`, `gate_result`, `probabilistic_output_kind`, `output_columns`, and `unsupported_combinations`. The probabilistic smoke-test gate result must be one of `compatible_adapter_selected`, `adapter_gap_proven`, `model_unsupported`, or `blocked_or_unknown`; `probabilistic_output_kind` must be one of `intervals`, `quantiles`, `both`, `none`, or `unknown`.
