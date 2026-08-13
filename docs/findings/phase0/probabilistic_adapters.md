# Phase 0 Probabilistic Adapter Finding

- Test ID: `SM-02`
- Classification: `pass`
- Gate result: `compatible_adapter_selected`
- TimeCopilot version: `0.0.30`
- Model or adapter: `timecopilot.models.foundation.t0.T0`
- Model-native capability: `native_probabilistic_quantiles`
- Adapter exposure: `quantiles_and_level_exposed`
- Probabilistic output kind: `both`
- Output columns: `ds, t0-alpha, t0-alpha-hi-80, t0-alpha-lo-80, t0-alpha-q-10, t0-alpha-q-50, t0-alpha-q-90, unique_id`

## Observed Result

TimeCopilot 0.0.30 T0.forecast returned requested quantile columns for quantiles=[0.1, 0.5, 0.9] and interval columns for level=[80] through the adapter. The adapter rejected simultaneous level and quantiles with the documented ValueError.

## Unsupported Combinations

The adapter does not support simultaneous `level` and `quantiles`; TimeCopilot raises a `ValueError` with the message: `You must not provide both level and quantiles simultaneously.`

## Boundary

No point-only model was modified. The finding is limited to TimeCopilot 0.0.30's T0 adapter output conversion, exercised with synthetic weekly data and a monkeypatched local model loader.

Evidence: `docs/findings/phase0/evidence/probabilistic_adapters.json`
