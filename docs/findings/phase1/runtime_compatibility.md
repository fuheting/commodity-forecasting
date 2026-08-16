# Phase 1 Runtime Compatibility and Reference Selection

- Run: `P1-05-20260816T064548Z`
- Matrix: `complete`
- Outcome: `pass`
- Selected reference: `autogluon/chronos-2-small`
- Selection basis: `smallest_verified_common_peak_then_p1_04_order`
- History: `2021-08-01..2026-07-01` (`60` rows)
- Forecast timestamps: `2026-08-01, 2026-09-01, 2026-10-01`

## Candidate matrix

| Order | Variant | Classification | Point | Probabilistic | Offline replay | Peak memory | Duration (s) |
| ---: | --- | --- | --- | --- | --- | --- | ---: |
| 1 | `amazon/chronos-2` | `pass` | `True` | `both` | `success` | 511798272 bytes (torch_cuda_max_memory_allocated) | 61.085616 |
| 2 | `autogluon/chronos-2-synth` | `pass` | `True` | `both` | `success` | 509765632 bytes (torch_cuda_max_memory_allocated) | 61.356427 |
| 3 | `autogluon/chronos-2-small` | `pass` | `True` | `both` | `success` | 145472512 bytes (torch_cuda_max_memory_allocated) | 59.425368 |
| 4 | `google/timesfm-1.0-200m-pytorch` | `fail` | `False` | `none` | `incomplete` | unmeasured | 28.718983 |
| 5 | `google/timesfm-2.5-200m-transformers` | `unsupported` | `False` | `none` | `incomplete` | unmeasured | 22.747947 |

## Attempt evidence

### `amazon/chronos-2`

- `connected_point`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; unique_id, ds, P105
- `connected_interval`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; unique_id, ds, P105, P105-lo-80, P105-hi-80
- `connected_quantiles`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; unique_id, ds, P105, P105-q-10, P105-q-20, P105-q-30, P105-q-40, P105-q-50, P105-q-60, P105-q-70, P105-q-80, P105-q-90
- `offline_point`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `offline_flags_no_proxy`; acquisition `None`; unique_id, ds, P105
- `offline_interval`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `offline_flags_no_proxy`; acquisition `None`; unique_id, ds, P105, P105-lo-80, P105-hi-80
- `offline_quantiles`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `offline_flags_no_proxy`; acquisition `None`; unique_id, ds, P105, P105-q-10, P105-q-20, P105-q-30, P105-q-40, P105-q-50, P105-q-60, P105-q-70, P105-q-80, P105-q-90

### `autogluon/chronos-2-synth`

- `connected_point`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; unique_id, ds, P105
- `connected_interval`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; unique_id, ds, P105, P105-lo-80, P105-hi-80
- `connected_quantiles`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; unique_id, ds, P105, P105-q-10, P105-q-20, P105-q-30, P105-q-40, P105-q-50, P105-q-60, P105-q-70, P105-q-80, P105-q-90
- `offline_point`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `offline_flags_no_proxy`; acquisition `None`; unique_id, ds, P105
- `offline_interval`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `offline_flags_no_proxy`; acquisition `None`; unique_id, ds, P105, P105-lo-80, P105-hi-80
- `offline_quantiles`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `offline_flags_no_proxy`; acquisition `None`; unique_id, ds, P105, P105-q-10, P105-q-20, P105-q-30, P105-q-40, P105-q-50, P105-q-60, P105-q-70, P105-q-80, P105-q-90

### `autogluon/chronos-2-small`

- `connected_point`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; unique_id, ds, P105
- `connected_interval`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; unique_id, ds, P105, P105-lo-80, P105-hi-80
- `connected_quantiles`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; unique_id, ds, P105, P105-q-10, P105-q-20, P105-q-30, P105-q-40, P105-q-50, P105-q-60, P105-q-70, P105-q-80, P105-q-90
- `offline_point`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `offline_flags_no_proxy`; acquisition `None`; unique_id, ds, P105
- `offline_interval`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `offline_flags_no_proxy`; acquisition `None`; unique_id, ds, P105, P105-lo-80, P105-hi-80
- `offline_quantiles`: `success`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `offline_flags_no_proxy`; acquisition `None`; unique_id, ds, P105, P105-q-10, P105-q-20, P105-q-30, P105-q-40, P105-q-50, P105-q-60, P105-q-70, P105-q-80, P105-q-90

### `google/timesfm-1.0-200m-pytorch`

- `connected_point`: `failed`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; shape '[1, -1, 32]' is invalid for input of size 60
- `connected_interval`: `unsupported`; device `unknown:cuda_visible_without_observed_allocation`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; TimesFM only supports the default quantiles, please use the default quantiles or default level, see https://github.com/google-research/timesfm/issues/286
- `connected_quantiles`: `failed`; device `cuda:0:NVIDIA RTX PRO 4000 Blackwell Generation Laptop GPU`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `cache_hit`; shape '[1, -1, 32]' is invalid for input of size 60
- `offline_point`: `not_run_due_to_prior_failure`; device `unobserved`; device policy `runtime_default`; network policy `runtime_default`; acquisition `None`; connected_point did not succeed
- `offline_interval`: `not_run_due_to_prior_failure`; device `unobserved`; device policy `runtime_default`; network policy `runtime_default`; acquisition `None`; connected_interval did not succeed
- `offline_quantiles`: `not_run_due_to_prior_failure`; device `unobserved`; device policy `runtime_default`; network policy `runtime_default`; acquisition `None`; connected_quantiles did not succeed

### `google/timesfm-2.5-200m-transformers`

- `connected_point`: `unsupported`; device `unknown:cuda_visible_without_observed_allocation`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `unknown`; TimesFM only supports pytorch models, if you'd like to use jax, please open an issue
- `connected_interval`: `unsupported`; device `unknown:cuda_visible_without_observed_allocation`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `unknown`; TimesFM only supports pytorch models, if you'd like to use jax, please open an issue
- `connected_quantiles`: `unsupported`; device `unknown:cuda_visible_without_observed_allocation`; device policy `gpu_required`; network policy `http_proxy_without_socks_fallback`; acquisition `unknown`; TimesFM only supports pytorch models, if you'd like to use jax, please open an issue
- `offline_point`: `not_run_due_to_prior_failure`; device `unobserved`; device policy `runtime_default`; network policy `runtime_default`; acquisition `None`; connected_point did not succeed
- `offline_interval`: `not_run_due_to_prior_failure`; device `unobserved`; device policy `runtime_default`; network policy `runtime_default`; acquisition `None`; connected_interval did not succeed
- `offline_quantiles`: `not_run_due_to_prior_failure`; device `unobserved`; device policy `runtime_default`; network policy `runtime_default`; acquisition `None`; connected_quantiles did not succeed

## Limits

This is one history-only 60-month/3-month runtime smoke on the local machine. It is not an accuracy ranking, tuned evaluation, training run, or backtest. Unknown device or unavailable peak-memory observations remain unknown rather than inferred.
