# TimeCopilot Capability Findings

**Scope:** TimeCopilot library capability boundaries only<br>
**Verified:** 2026-08-12<br>
**Repository:** https://github.com/TimeCopilot/timecopilot

## 1. What TimeCopilot is

TimeCopilot is an open-source forecasting agent and unified forecasting interface. It integrates foundation, statistical, machine-learning, and neural forecasting models.

An underlying model capability is usable through TimeCopilot only when the corresponding adapter or integration exposes it.

```text
usable capability
= model capability
∩ TimeCopilot adapter/integration capability
```

## 2. Unified forecasting interface

The common forecasting interface is:

```python
forecast(df, h, freq=None, level=None, quantiles=None)
```

The documented common input is a long-format DataFrame:

```text
unique_id | ds | y
```

- `unique_id`: time-series ID
- `ds`: timestamp
- `y`: target
- `h`: forecast horizon
- `freq`: frequency
- `level`: prediction-interval levels
- `quantiles`: forecast quantiles

The interface supports panel / multi-series data through multiple `unique_id` values.

TimeCopilot does **not** define a unified four-table input contract for:

```text
target_history
past_covariates
future_covariates
static_covariates
```

## 3. Natural-language forecasting

TimeCopilot documents natural-language forecasting as an agent-level capability. The `TimeCopilot` agent accepts a plain-language `query` alongside the time-series data:

```python
result = tc.forecast(
    df=df,
    freq="MS",
    query="How many air passengers are expected in total in the next 12 months?",
)
```

The documented agent output includes natural-language feature analysis, model comparison and selection rationale, forecast interpretation, and `user_query_response` for the supplied question. The CLI exposes the same query path through `timecopilot forecast ... --query "..."`.

This capability is distinct from the lower-level unified model interface described above. It requires a configured LLM, and the TimeCopilot README states that the selected LLM must support tool use. Local availability, credentials, provider behavior, and successful execution on the PoC dataset still require an empirical smoke test.

## 4. Forecast outputs

The common API exposes:

- point forecasts
- prediction intervals through `level`
- quantile forecasts through `quantiles`

Actual support remains model/adapter dependent.

Example: the sktime adapter currently does not support prediction intervals or quantile forecasts.

## 5. Local-capable open foundation models

The following TimeCopilot integrations expose local execution or local model-loading paths and reference public model/code sources.

| Model family | Local path / mode | Recorded boundary |
|---|---|---|
| Chronos / Chronos-2 | Yes | Chronos-2 fine-tuning exposed; full and LoRA modes |
| FlowState | Yes | Common forecasting interface |
| Moirai | Yes | Covariate dimensions exist, but usable inputs remain adapter-specific |
| PatchTST-FM | Yes | Common forecasting interface |
| Sundial | Yes | Local model weights |
| TabPFN | Yes | LOCAL and client modes |
| TiRex / TiRex-2 | Yes | Exogenous cross-validation unsupported |
| TimesFM | Yes | PyTorch checkpoints supported; JAX unsupported |
| Toto / Toto-2 | Yes | Common forecasting interface |

Excluded from this list:

- **TimeGPT:** TimeCopilot integration uses the Nixtla API.
- **T0:** TimeCopilot supports local loading of an open-weight checkpoint, but the current documentation does not establish it as an open-source implementation.

## 6. Trainable non-foundation models

These model families are fitted or trained on supplied time-series data within TimeCopilot workflows.

| Family | Models |
|---|---|
| Statistical / classical | ADIDA, AutoARIMA, AutoCES, AutoETS, CrostonClassic, DynamicOptimizedTheta, HistoricAverage, IMAPA, SeasonalNaive, Theta, ZeroModel, Prophet |
| Machine learning | AutoCatboost, AutoElasticNet, AutoLasso, AutoLGBM, AutoLinearRegression, AutoRandomForest, AutoRidge, AutoXGBoost |
| Neural | AutoDeepAR, AutoNBEATS, AutoNHITS, AutoPatchTST, AutoTFT |

The common public abstraction is `forecast()` / `cross_validation()`, not a single generic persisted `fit()` / `retrain()` API across all families.

## 7. Covariate and adapter boundaries

Adapter support is a necessary condition.

Confirmed boundaries:

- T0 natively supports past and known-future covariates.
- The current TimeCopilot T0 integration exposes the **univariate path only**.
- Foundation-model cross-validation rejects exogenous columns with:

```text
NotImplementedError:
Cross validation with exogenous variables is not yet supported.
```

- The sktime adapter contains an explicit TODO for exogenous-data support.

Therefore, underlying-model covariate support must not be treated as TimeCopilot-level support without checking the adapter.

## 8. Unknown or unestablished capabilities

### Static covariates

**Status: unknown / not established as a unified TimeCopilot capability.**

No common TimeCopilot forecasting contract was found for static or time-invariant covariates.

### Multivariate forecasting

The unified `unique_id / ds / y` format supports panel / multi-series data. This does not establish universal multivariate-target support.

Multivariate support remains model- and adapter-specific.

## 9. Multimodal input boundary

TimeCopilot's documented forecasting interfaces operate on structured time-series data.

No native forecasting input contract was found for raw:

- images
- audio
- video
- PDF documents
- news articles
- social-media text

Raw multimodal input is therefore **not a documented TimeCopilot forecasting capability**.

## 10. Frequency boundary

The common interface uses `freq`, supplied explicitly or inferred.

Cross-validation can fail when frequency does not match the series or when expected periods are missing.

## 11. Recorded local GPU

```text
NVIDIA RTX PRO 4000 Blackwell
VRAM: 16 GB
```

No local-deployment, memory-fit, batch-size, context-length, or fine-tuning feasibility conclusion is made in this document.

## 12. Capability boundary summary

```text
TimeCopilot unifies model invocation.
It does not normalize every underlying model capability.
```

Key boundaries:

- natural-language queries, analysis, and explanations are exposed through the LLM-backed `TimeCopilot` agent
- natural-language execution requires a configured, tool-capable LLM and remains subject to provider and credential availability
- adapter support is required
- T0 integration currently exposes only the univariate path
- foundation-model cross-validation does not support exogenous variables
- sktime exogenous-data support is not implemented
- sktime prediction intervals and quantile forecasts are not implemented
- static-covariate support is unknown at the unified-library level
- unified input is `unique_id / ds / y`, not a four-table covariate schema
- panel / multi-series support does not imply universal multivariate support
- raw multimodal input is not supported by the documented forecasting interface

## Sources

- https://github.com/TimeCopilot/timecopilot
- https://github.com/TimeCopilot/timecopilot/blob/main/README.md#-key-capabilities
- https://github.com/TimeCopilot/timecopilot/blob/main/README.md#ask-about-the-future
- https://github.com/TimeCopilot/timecopilot/blob/main/timecopilot/agent.py
- https://github.com/TimeCopilot/timecopilot/blob/main/timecopilot/_cli.py
- https://github.com/TimeCopilot/timecopilot/blob/main/timecopilot/forecaster.py
- https://timecopilot.dev/model-hub/
- https://timecopilot.dev/api/forecaster/
- https://timecopilot.dev/api/models/foundation/models/
- https://timecopilot.dev/api/models/stats/
- https://timecopilot.dev/api/models/ml/
- https://timecopilot.dev/api/models/neural/
- https://timecopilot.dev/api/models/adapters/adapters/
