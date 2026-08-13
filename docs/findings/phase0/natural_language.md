# Phase 0 Natural-Language Capability Finding

- Classification: `pass`
- Provider/model: `PydanticAI deterministic FunctionModel` / `FunctionModel (pydantic-ai 2.28.0)`
- Credentials: `not_required`; network: `not_used`
- Tool calls: `tsfeatures_tool, cross_validation_tool, forecast_tool, detect_anomalies_tool`
- Forecast rows: `12`

## Observed Result

All four registered forecasting tools executed and the agent returned a 12-row forecast, non-empty analysis, and query-specific response.

## Boundary

- The weekly Coffee C wording is retained only to reproduce the historical SM-03 capability result; the active PoC contract is monthly Coffee, Arabica.
- This proves the TimeCopilot query and tool contract without credentials; it does not evaluate external-provider language quality.
- The deterministic response marks the baseline as accepted to satisfy TimeCopilot's output validator; it is not a performance claim.

Evidence: `docs/findings/phase0/evidence/natural_language.json`
