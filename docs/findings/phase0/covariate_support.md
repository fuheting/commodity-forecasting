# Phase 0 Covariate Support Finding

- Test ID: `SM-01`
- Classification: `pass`
- Gate result: `adapter_gap_proven`
- TimeCopilot version: `0.0.30`
- Model or adapter: `timecopilot.models.foundation.t0.T0`
- Model-native capability: `known_future_future_covariates_executed`
- Adapter exposure: `univariate_only_adapter_omits_covariates`
- Covariate path classification: `known_future`

## Observed Result

Native tfc-t0 T0Forecaster.predict accepted and executed future_covariates on a tiny local model, while the TimeCopilot T0.forecast adapter accepted only the univariate forecast contract and a monkeypatched adapter run with covariate columns passed no future_covariates keyword to native predict.

## Boundary

No unsupported model was modified and no custom covariate adapter was added. The finding is limited to the installed T0 native API and the current TimeCopilot T0 adapter behavior exercised by the smoke test.

Evidence: `docs/findings/phase0/evidence/covariate_support.json`
