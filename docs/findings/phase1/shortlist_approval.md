# Phase 1 Shortlist Approval

- Decision ID: `P1-04-20260815T031954Z`
- Approved at: `2026-08-15T03:19:54Z`
- Classification: `approved`
- Approval basis: `explicit_unknown_risk_acceptance`
- P1-03 evidence SHA-256: `db8a16f556821552aa3d0d01f370430d96fbdab3a09b25b3d497843659daa4d0`

## Approved execution order

1. `amazon/chronos-2`
2. `autogluon/chronos-2-synth`
3. `autogluon/chronos-2-small`
4. `google/timesfm-1.0-200m-pytorch`
5. `google/timesfm-2.5-200m-transformers`

All approved variants retain P1-03 `unknown/ineligible` evidence status. The user explicitly accepted the unknown local edge-feasibility risk for shortlist admission; actual weight loading and compatibility are deferred to P1-05. This approval does not rewrite the underlying evidence.

## User approval statements

- I approve these variants with accepted unknown risks.
- I approve autogluon/chronos-2-synth.
- No, proceed with the five previously approved variant. The unknown risk is their actual edge feasbility in terms of loading weights on the local machine, which is the recorded task for P1-05

## Exclusions

- `theforecastingcompany/t0-alpha` — Fixed exclusion retained for the user-specified rationale. Source-timing conflict: current upstream now publishes open weights and source code, but this task must not admit T0.
- `TimeGPT` — Excluded because the TimeCopilot integration is API-backed and requires a Nixtla API key. No downloadable checkpoint inventory is documented.

## Remaining unknown/ineligible variants

38 variants remain unapproved and cannot enter P1-05.
- `amazon/chronos-bolt-tiny`
- `amazon/chronos-bolt-mini`
- `amazon/chronos-bolt-small`
- `amazon/chronos-bolt-base`
- `amazon/chronos-t5-tiny`
- `amazon/chronos-t5-mini`
- `amazon/chronos-t5-small`
- `amazon/chronos-t5-base`
- `amazon/chronos-t5-large`
- `ibm-research/flowstate`
- `ibm-granite/granite-timeseries-flowstate-r1`
- `Salesforce/moirai-1.1-R-small`
- `Salesforce/moirai-1.1-R-base`
- `Salesforce/moirai-moe-1.0-R-base`
- `Salesforce/moirai-2.0-R-small`
- `Salesforce/moirai-1.0-R-large`
- `ibm-research/patchtst-fm-r1`
- `ibm-granite/granite-timeseries-patchtst-fm-r1`
- `thuml/sundial-base-128m`
- `TabPFN-TS-3`
- `NX-AI/TiRex`
- `NX-AI/TiRex-1.1-gifteval`
- `NX-AI/TiRex-2`
- `NX-AI/TiRex-2-gifteval-zs`
- `NX-AI/TiRex-2-gifteval-pretrain`
- `NX-AI/TiRex-2-fevbench`
- `google/timesfm-1.0-200m`
- `google/timesfm-2.0-500m-jax`
- `google/timesfm-2.0-500m-pytorch`
- `google/timesfm-2.5-200m-pytorch`
- `google/timesfm-2.5-200m-flax`
- `Datadog/Toto-Open-Base-1.0`
- `Datadog/Toto-2.0-4m`
- `Datadog/Toto-2.0-22m`
- `Datadog/Toto-2.0-313m`
- `Datadog/Toto-2.0-1B`
- `Datadog/Toto-2.0-2.5B`
- `Datadog/Toto-2.0-2.5B-FT`

## Gate

Downstream execution must present the exact approved list in the recorded order. Any P1-03 evidence-byte change invalidates this approval and returns execution to P1-04.
