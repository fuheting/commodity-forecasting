"""Conservative, documentation-only feasibility screening for Phase 1.

The module deliberately does not import forecasting packages, contact model hubs,
download artifacts, or execute models.  Official facts are curated in the
canonical JSON ledger; this code validates and derives decisions from those facts.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import target_pipeline

TASK_ID = "P1-03"
SCHEMA_VERSION = 1
TARGET_GPU_GB = 16
INVENTORY_BASELINE_RELATIVE_PATH = Path(
    ".omx/context/p1-03-official-inventory-baseline-20260814T133808Z.md"
)
EXECUTION_CATALOG_CAPTURED_AT_UTC = "2026-08-14T14:24:44Z"
_FROZEN_INVENTORY_BASELINE_JSON = r'''[{"family":"Chronos / Chronos-2","identifiers":["amazon/chronos-bolt-tiny","amazon/chronos-bolt-mini","amazon/chronos-bolt-small","amazon/chronos-bolt-base","amazon/chronos-t5-tiny","amazon/chronos-t5-mini","amazon/chronos-t5-small","amazon/chronos-t5-base","amazon/chronos-t5-large","amazon/chronos-2","autogluon/chronos-2-synth","autogluon/chronos-2-small"]},{"family":"FlowState","identifiers":["ibm-research/flowstate","ibm-granite/granite-timeseries-flowstate-r1"]},{"family":"Moirai","identifiers":["Salesforce/moirai-1.1-R-small","Salesforce/moirai-1.1-R-base","Salesforce/moirai-moe-1.0-R-base","Salesforce/moirai-2.0-R-small","Salesforce/moirai-1.0-R-large"]},{"family":"PatchTST-FM","identifiers":["ibm-research/patchtst-fm-r1","ibm-granite/granite-timeseries-patchtst-fm-r1"]},{"family":"Sundial","identifiers":["thuml/sundial-base-128m"]},{"family":"TabPFN","identifiers":["TabPFN-TS-3"]},{"family":"TiRex","identifiers":["NX-AI/TiRex","NX-AI/TiRex-1.1-gifteval"]},{"family":"TiRex-2","identifiers":["NX-AI/TiRex-2","NX-AI/TiRex-2-gifteval-zs","NX-AI/TiRex-2-gifteval-pretrain","NX-AI/TiRex-2-fevbench"]},{"family":"TimesFM","identifiers":["google/timesfm-1.0-200m","google/timesfm-1.0-200m-pytorch","google/timesfm-2.0-500m-jax","google/timesfm-2.0-500m-pytorch","google/timesfm-2.5-200m-pytorch","google/timesfm-2.5-200m-flax","google/timesfm-2.5-200m-transformers"]},{"family":"Toto / Toto-2","identifiers":["Datadog/Toto-Open-Base-1.0","Datadog/Toto-2.0-4m","Datadog/Toto-2.0-22m","Datadog/Toto-2.0-313m","Datadog/Toto-2.0-1B","Datadog/Toto-2.0-2.5B","Datadog/Toto-2.0-2.5B-FT","Datadog/Toto-2.0-Family-and-Friends"]}]'''
_PINNED_EXECUTION_CATALOG_JSON = r'''[{"family":"Chronos / Chronos-2","identifiers":["amazon/chronos-bolt-tiny","amazon/chronos-bolt-mini","amazon/chronos-bolt-small","amazon/chronos-bolt-base","amazon/chronos-t5-tiny","amazon/chronos-t5-mini","amazon/chronos-t5-small","amazon/chronos-t5-base","amazon/chronos-t5-large","amazon/chronos-2","autogluon/chronos-2-synth","autogluon/chronos-2-small"],"official_sources":[{"identifier":"amazon/chronos-bolt-tiny","source_ref":"src:official:amazon_chronos_bolt_tiny","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/amazon/chronos-bolt-tiny"},{"identifier":"amazon/chronos-bolt-mini","source_ref":"src:official:amazon_chronos_bolt_mini","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/amazon/chronos-bolt-mini"},{"identifier":"amazon/chronos-bolt-small","source_ref":"src:official:amazon_chronos_bolt_small","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/amazon/chronos-bolt-small"},{"identifier":"amazon/chronos-bolt-base","source_ref":"src:official:amazon_chronos_bolt_base","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/amazon/chronos-bolt-base"},{"identifier":"amazon/chronos-t5-tiny","source_ref":"src:official:amazon_chronos_t5_tiny","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/amazon/chronos-t5-tiny"},{"identifier":"amazon/chronos-t5-mini","source_ref":"src:official:amazon_chronos_t5_mini","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/amazon/chronos-t5-mini"},{"identifier":"amazon/chronos-t5-small","source_ref":"src:official:amazon_chronos_t5_small","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/amazon/chronos-t5-small"},{"identifier":"amazon/chronos-t5-base","source_ref":"src:official:amazon_chronos_t5_base","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/amazon/chronos-t5-base"},{"identifier":"amazon/chronos-t5-large","source_ref":"src:official:amazon_chronos_t5_large","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/amazon/chronos-t5-large"},{"identifier":"amazon/chronos-2","source_ref":"src:official:amazon_chronos_2","source_version_or_date":"2025-10-20","source_version_status":"known","url":"https://huggingface.co/amazon/chronos-2"},{"identifier":"autogluon/chronos-2-synth","source_ref":"src:official:autogluon_chronos_2_synth","source_version_or_date":"2025-10-20","source_version_status":"known","url":"https://huggingface.co/autogluon/chronos-2-synth"},{"identifier":"autogluon/chronos-2-small","source_ref":"src:official:autogluon_chronos_2_small","source_version_or_date":"2025-10-20","source_version_status":"known","url":"https://huggingface.co/autogluon/chronos-2-small"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"FlowState","identifiers":["ibm-research/flowstate","ibm-granite/granite-timeseries-flowstate-r1"],"official_sources":[{"identifier":"ibm-research/flowstate","source_ref":"src:official:ibm_research_flowstate","source_version_or_date":"r1.1 / 2025-08-07","source_version_status":"known","url":"https://huggingface.co/ibm-research/flowstate"},{"identifier":"ibm-granite/granite-timeseries-flowstate-r1","source_ref":"src:official:ibm_granite_granite_timeseries_flowstate_r1","source_version_or_date":"2025-08-07","source_version_status":"known","url":"https://huggingface.co/ibm-granite/granite-timeseries-flowstate-r1"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"Moirai","identifiers":["Salesforce/moirai-1.1-R-small","Salesforce/moirai-1.1-R-base","Salesforce/moirai-moe-1.0-R-base","Salesforce/moirai-2.0-R-small","Salesforce/moirai-1.0-R-large"],"official_sources":[{"identifier":"Salesforce/moirai-1.1-R-small","source_ref":"src:official:salesforce_moirai_1_1_r_small","source_version_or_date":"Uni2TS 1.1.0 / adf7206 / 2024-06-14","source_version_status":"known","url":"https://huggingface.co/Salesforce/moirai-1.1-R-small"},{"identifier":"Salesforce/moirai-1.1-R-base","source_ref":"src:official:salesforce_moirai_1_1_r_base","source_version_or_date":"Uni2TS 1.1.0 / adf7206 / 2024-06-14","source_version_status":"known","url":"https://huggingface.co/Salesforce/moirai-1.1-R-base"},{"identifier":"Salesforce/moirai-moe-1.0-R-base","source_ref":"src:official:salesforce_moirai_moe_1_0_r_base","source_version_or_date":"Uni2TS 1.2.0 / fdcb656 / 2024-11-28","source_version_status":"known","url":"https://huggingface.co/Salesforce/moirai-moe-1.0-R-base"},{"identifier":"Salesforce/moirai-2.0-R-small","source_ref":"src:official:salesforce_moirai_2_0_r_small","source_version_or_date":"Uni2TS 2.0.0 / 8062ef5 / 2025-11-04","source_version_status":"known","url":"https://huggingface.co/Salesforce/moirai-2.0-R-small"},{"identifier":"Salesforce/moirai-1.0-R-large","source_ref":"src:official:salesforce_moirai_1_0_r_large","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/Salesforce/moirai-1.0-R-large"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"PatchTST-FM","identifiers":["ibm-research/patchtst-fm-r1","ibm-granite/granite-timeseries-patchtst-fm-r1"],"official_sources":[{"identifier":"ibm-research/patchtst-fm-r1","source_ref":"src:official:ibm_research_patchtst_fm_r1","source_version_or_date":"2026-02-06","source_version_status":"known","url":"https://huggingface.co/ibm-research/patchtst-fm-r1"},{"identifier":"ibm-granite/granite-timeseries-patchtst-fm-r1","source_ref":"src:official:ibm_granite_granite_timeseries_patchtst_fm_r1","source_version_or_date":"2026-03-18","source_version_status":"known","url":"https://huggingface.co/ibm-granite/granite-timeseries-patchtst-fm-r1"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"Sundial","identifiers":["thuml/sundial-base-128m"],"official_sources":[{"identifier":"thuml/sundial-base-128m","source_ref":"src:official:thuml_sundial_base_128m","source_version_or_date":"2025-02-02","source_version_status":"known","url":"https://huggingface.co/thuml/sundial-base-128m"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"TabPFN","identifiers":["TabPFN-TS-3"],"official_sources":[{"identifier":"TabPFN-TS-3","source_ref":"src:official:tabpfn_ts_3","source_version_or_date":"tabpfn-time-series v1.1.0 / 2026-05-12","source_version_status":"known","url":"https://github.com/PriorLabs/tabpfn-time-series"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"TiRex","identifiers":["NX-AI/TiRex","NX-AI/TiRex-1.1-gifteval"],"official_sources":[{"identifier":"NX-AI/TiRex","source_ref":"src:official:nx_ai_tirex","source_version_or_date":"2025-05-29","source_version_status":"known","url":"https://huggingface.co/NX-AI/TiRex"},{"identifier":"NX-AI/TiRex-1.1-gifteval","source_ref":"src:official:nx_ai_tirex_1_1_gifteval","source_version_or_date":"2025-05-29","source_version_status":"known","url":"https://huggingface.co/NX-AI/TiRex-1.1-gifteval"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"TiRex-2","identifiers":["NX-AI/TiRex-2","NX-AI/TiRex-2-gifteval-zs","NX-AI/TiRex-2-gifteval-pretrain","NX-AI/TiRex-2-fevbench"],"official_sources":[{"identifier":"NX-AI/TiRex-2","source_ref":"src:official:nx_ai_tirex_2","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/NX-AI/TiRex-2"},{"identifier":"NX-AI/TiRex-2-gifteval-zs","source_ref":"src:official:nx_ai_tirex_2_gifteval_zs","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/NX-AI/TiRex-2-gifteval-zs"},{"identifier":"NX-AI/TiRex-2-gifteval-pretrain","source_ref":"src:official:nx_ai_tirex_2_gifteval_pretrain","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/NX-AI/TiRex-2-gifteval-pretrain"},{"identifier":"NX-AI/TiRex-2-fevbench","source_ref":"src:official:nx_ai_tirex_2_fevbench","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/NX-AI/TiRex-2-fevbench"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"TimesFM","identifiers":["google/timesfm-1.0-200m","google/timesfm-1.0-200m-pytorch","google/timesfm-2.0-500m-jax","google/timesfm-2.0-500m-pytorch","google/timesfm-2.5-200m-pytorch","google/timesfm-2.5-200m-flax","google/timesfm-2.5-200m-transformers"],"official_sources":[{"identifier":"google/timesfm-1.0-200m","source_ref":"src:official:google_timesfm_1_0_200m","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/google/timesfm-1.0-200m"},{"identifier":"google/timesfm-1.0-200m-pytorch","source_ref":"src:official:google_timesfm_1_0_200m_pytorch","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/google/timesfm-1.0-200m-pytorch"},{"identifier":"google/timesfm-2.0-500m-jax","source_ref":"src:official:google_timesfm_2_0_500m_jax","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/google/timesfm-2.0-500m-jax"},{"identifier":"google/timesfm-2.0-500m-pytorch","source_ref":"src:official:google_timesfm_2_0_500m_pytorch","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/google/timesfm-2.0-500m-pytorch"},{"identifier":"google/timesfm-2.5-200m-pytorch","source_ref":"src:official:google_timesfm_2_5_200m_pytorch","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/google/timesfm-2.5-200m-pytorch"},{"identifier":"google/timesfm-2.5-200m-flax","source_ref":"src:official:google_timesfm_2_5_200m_flax","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/google/timesfm-2.5-200m-flax"},{"identifier":"google/timesfm-2.5-200m-transformers","source_ref":"src:official:google_timesfm_2_5_200m_transformers","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/google/timesfm-2.5-200m-transformers"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"Toto / Toto-2","identifiers":["Datadog/Toto-Open-Base-1.0","Datadog/Toto-2.0-4m","Datadog/Toto-2.0-22m","Datadog/Toto-2.0-313m","Datadog/Toto-2.0-1B","Datadog/Toto-2.0-2.5B","Datadog/Toto-2.0-2.5B-FT","Datadog/Toto-2.0-Family-and-Friends"],"official_sources":[{"identifier":"Datadog/Toto-Open-Base-1.0","source_ref":"src:official:datadog_toto_open_base_1_0","source_version_or_date":"unknown","source_version_status":"unknown","url":"https://huggingface.co/Datadog/Toto-Open-Base-1.0"},{"identifier":"Datadog/Toto-2.0-4m","source_ref":"src:official:datadog_toto_2_0_4m","source_version_or_date":"Toto 2.0 collection / 2026-05-11","source_version_status":"known","url":"https://huggingface.co/Datadog/Toto-2.0-4m"},{"identifier":"Datadog/Toto-2.0-22m","source_ref":"src:official:datadog_toto_2_0_22m","source_version_or_date":"Toto 2.0 collection / 2026-05-11","source_version_status":"known","url":"https://huggingface.co/Datadog/Toto-2.0-22m"},{"identifier":"Datadog/Toto-2.0-313m","source_ref":"src:official:datadog_toto_2_0_313m","source_version_or_date":"Toto 2.0 collection / 2026-05-11","source_version_status":"known","url":"https://huggingface.co/Datadog/Toto-2.0-313m"},{"identifier":"Datadog/Toto-2.0-1B","source_ref":"src:official:datadog_toto_2_0_1b","source_version_or_date":"Toto 2.0 collection / 2026-05-11","source_version_status":"known","url":"https://huggingface.co/Datadog/Toto-2.0-1B"},{"identifier":"Datadog/Toto-2.0-2.5B","source_ref":"src:official:datadog_toto_2_0_2_5b","source_version_or_date":"Toto 2.0 collection / 2026-05-11","source_version_status":"known","url":"https://huggingface.co/Datadog/Toto-2.0-2.5B"},{"identifier":"Datadog/Toto-2.0-2.5B-FT","source_ref":"src:official:datadog_toto_2_0_2_5b_ft","source_version_or_date":"2026-05-19","source_version_status":"known","url":"https://huggingface.co/Datadog/Toto-2.0-2.5B-FT"},{"identifier":"Datadog/Toto-2.0-Family-and-Friends","source_ref":"src:official:datadog_toto_2_0_family_and_friends","url":"https://huggingface.co/Datadog/Toto-2.0-Family-and-Friends","source_version_status":"unknown","source_version_or_date":"unknown"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"T0","identifiers":["theforecastingcompany/t0-alpha"],"official_sources":[{"identifier":"theforecastingcompany/t0-alpha","source_ref":"src:official:theforecastingcompany_t0_alpha","url":"https://huggingface.co/theforecastingcompany/t0-alpha","source_version_status":"unknown","source_version_or_date":"unknown"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"},{"family":"TimeGPT","identifiers":["TimeGPT"],"official_sources":[{"identifier":"TimeGPT","source_ref":"src:official:timegpt","url":"https://www.nixtla.io/docs/reference/sdk_reference","source_version_status":"unknown","source_version_or_date":"unknown"}],"retrieved_at_utc":"2026-08-14T14:24:44Z"}]'''
_FROZEN_INVENTORY_ROWS = json.loads(_FROZEN_INVENTORY_BASELINE_JSON)
_PINNED_CATALOG_ROWS = json.loads(_PINNED_EXECUTION_CATALOG_JSON)


def _pinned_official_stable_locator(version_status: str, version: str) -> str:
    if version_status == "unknown":
        return "current model card at retrieval; mutable source"
    return f"{version}; artifact identity and model metadata"


FROZEN_INVENTORY_BASELINE: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {row["family"]: tuple(row["identifiers"]) for row in _FROZEN_INVENTORY_ROWS}
)
PINNED_EXECUTION_CATALOG: Mapping[
    str,
    tuple[tuple[str, ...], tuple[tuple[str, str, str, str, str, str], ...], str],
] = MappingProxyType(
    {
        row["family"]: (
            tuple(row["identifiers"]),
            tuple(
                (
                    source["identifier"],
                    source["source_ref"],
                    source["url"],
                    source["source_version_status"],
                    source["source_version_or_date"],
                    _pinned_official_stable_locator(
                        source["source_version_status"], source["source_version_or_date"]
                    ),
                )
                for source in row["official_sources"]
            ),
            row["retrieved_at_utc"],
        )
        for row in _PINNED_CATALOG_ROWS
    }
)
FROZEN_INVENTORY_BASELINE_SHA256 = "850f2d13a55e7049925de0b55c425f5f386bac4f79fcd63effc2809e625a3827"
PINNED_EXECUTION_CATALOG_SHA256 = "6b8fa6be02962696092e944f0ceaf08ef41fc7f476c6259abe6307f1d5683ff6"
del _FROZEN_INVENTORY_ROWS, _PINNED_CATALOG_ROWS
P1_02_EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/target_pipeline.json")
FINDING_RELATIVE_PATH = Path("docs/findings/phase1/model_screening.md")
EVIDENCE_RELATIVE_PATH = Path("docs/findings/phase1/evidence/model_screening.json")
ROADMAP_RELATIVE_PATH = Path("docs/roadmap.md")
P1_03_ROADMAP_PLANNED_LINE = (
    "- [ ] **P1-03 — Official-document edge-feasibility screen.** Depends on P1-02. "
    "Screen every documented local-capable Time Series Foundation Model family at the "
    "artifact-variant level against official evidence and the recorded 16 GB GPU target; "
    "required unknowns are not eligible. Evidence: "
    "`docs/findings/phase1/model_screening.md` and "
    "`docs/findings/phase1/evidence/model_screening.json`."
)

INSTALLED_DISTRIBUTIONS = (
    "timecopilot", "torch", "transformers", "accelerate",
    "timecopilot-chronos-forecasting", "timecopilot-uni2ts", "timecopilot-timesfm",
    "timecopilot-tirex", "timecopilot-tirex2", "timecopilot-toto",
    "timecopilot-toto-2", "tfc-t0", "nixtla", "tabpfn-time-series",
)
ADAPTER_MANIFEST: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "timecopilot/models/foundation/chronos.py": (),
        "timecopilot/models/foundation/flowstate.py": (),
        "timecopilot/models/foundation/moirai.py": (
            "timecopilot/models/utils/gluonts_forecaster.py",
        ),
        "timecopilot/models/foundation/patchtst_fm.py": (),
        "timecopilot/models/foundation/sundial.py": (),
        "timecopilot/models/foundation/tabpfn.py": (),
        "timecopilot/models/foundation/tirex.py": (),
        "timecopilot/models/foundation/timesfm.py": (),
        "timecopilot/models/foundation/toto.py": (),
        "timecopilot/models/foundation/t0.py": (),
        "timecopilot/models/foundation/timegpt.py": (),
    }
)
PINNED_LOCAL_SOURCE_BY_FAMILY: Mapping[str, str] = MappingProxyType(
    {
        "Chronos / Chronos-2": "src:local:chronos",
        "FlowState": "src:local:flowstate",
        "Moirai": "src:local:moirai",
        "PatchTST-FM": "src:local:patchtst_fm",
        "Sundial": "src:local:sundial",
        "TabPFN": "src:local:tabpfn",
        "TiRex": "src:local:tirex",
        "TiRex-2": "src:local:tirex",
        "TimesFM": "src:local:timesfm",
        "Toto / Toto-2": "src:local:toto",
        "T0": "src:local:t0",
        "TimeGPT": "src:local:timegpt",
    }
)
PINNED_LOCAL_LOCATORS: Mapping[str, str] = MappingProxyType(
    {
        "src:local:chronos": "timecopilot/models/foundation/chronos.py",
        "src:local:flowstate": "timecopilot/models/foundation/flowstate.py",
        "src:local:moirai": "timecopilot/models/foundation/moirai.py",
        "src:local:patchtst_fm": "timecopilot/models/foundation/patchtst_fm.py",
        "src:local:sundial": "timecopilot/models/foundation/sundial.py",
        "src:local:tabpfn": "timecopilot/models/foundation/tabpfn.py",
        "src:local:tirex": "timecopilot/models/foundation/tirex.py",
        "src:local:timesfm": "timecopilot/models/foundation/timesfm.py",
        "src:local:toto": "timecopilot/models/foundation/toto.py",
        "src:local:t0": "timecopilot/models/foundation/t0.py",
        "src:local:timegpt": "timecopilot/models/foundation/timegpt.py",
    }
)

OFFICIAL_SOURCE_KINDS = frozenset(
    {"official_model_card", "official_repository_and_docs", "official_sdk_documentation"}
)
SOURCE_KINDS = OFFICIAL_SOURCE_KINDS | frozenset(
    {"observed_local_package_source", "persisted_inventory_baseline"}
)
BASE_SOURCE_FIELDS = frozenset(
    {"url_or_path", "source_kind", "source_version_or_date", "retrieved_at_utc", "stable_locator"}
)
OFFICIAL_SOURCE_FIELDS = BASE_SOURCE_FIELDS
LOCAL_SOURCE_FIELDS = BASE_SOURCE_FIELDS | frozenset({"sha256"})
INVENTORY_SOURCE_FIELDS = BASE_SOURCE_FIELDS | frozenset({"persisted_inventory_path", "sha256"})
INVENTORY_SOURCE_VERSION_OR_DATE = "2026-08-14"
INVENTORY_SOURCE_STABLE_LOCATOR = "exact identifier lists under Official-family baselines"
REQUIRED_CHECK_KEYS = frozenset(
    {
        "classification_integrity", "inventory_complete", "inventory_drift_absent",
        "markdown_is_canonical_render", "no_models_imported_or_executed",
        "no_weights_downloaded", "p1_02_current_pass", "per_fact_provenance_complete",
        "required_unknowns_excluded_from_eligibility",
    }
)

FACT_STATUSES = frozenset({"known", "unknown", "blocked"})
RESULTS = frozenset({"eligible", "ineligible", "unknown/ineligible", "excluded", "blocked"})
OVERALL_CLASSIFICATIONS = frozenset({"pass", "fail", "blocked"})
DISPOSITIONS = frozenset({"screened_variant", "alias", "out_of_scope"})
DEVICE_STATUSES = frozenset({"supported", "unsupported", "unknown"})
OFFLINE_STATUSES = frozenset({"supported", "requires_runtime_service", "unknown"})
COLD_START_STATUSES = frozenset({"supported", "requires_prior_acquisition", "unknown"})
AUTH_STATUSES = frozenset({"none", "required", "unknown"})
LICENSE_STATUSES = frozenset({"known", "unknown"})
POC_USE_STATUSES = frozenset({"allowed", "prohibited", "unknown"})

REQUIRED_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version", "task_id", "run_id", "generated_at_utc", "target_gpu",
        "p1_02_evidence_path", "p1_02_evidence_sha256", "source_registry",
        "frozen_inventory_baseline_sha256", "pinned_execution_catalog_sha256",
        "official_catalog_snapshot",
        "inventory_witnesses", "local_package_observations", "variant_records",
        "derived_counts", "eligible_variant_ids", "overall_classification", "checks",
        "errors", "notes",
    }
)
REQUIRED_VARIANT_FIELDS = frozenset(
    {
        "family", "canonical_variant_id", "inventory_disposition", "official_source_url",
        "source_version_or_date", "retrieved_at_utc", "applicable_installed_package_versions",
        "artifact_identity", "artifact_size", "runtime_framework", "model_native",
        "timecopilot_adapter", "probabilistic", "device_target", "device_status",
        "offline_after_acquisition", "cold_start_offline", "runtime_auth",
        "acquisition_auth", "code_license", "artifact_license",
        "documented_memory_vram_requirement", "fit_against_16gb_target",
        "monthly_history_only_60x3_support", "result", "notes", "unknowns",
    }
)
MODEL_NATIVE_FIELDS = (
    "monthly_frequency", "usable_context_months", "forecast_horizon_months",
    "history_only", "univariate_only", "model_specific_minimums",
)
ADAPTER_FIELDS = ("artifact_identity", "point", "interval", "quantile")
PROBABILISTIC_FIELDS = ("point", "interval", "quantile")
P1_03_ROADMAP_PATTERN = re.compile(r"(?m)^- \[([ x-])\] \*\*P1-03\b.*$")
P1_03_ROADMAP_LINE_PATTERN = re.compile(r"(?m)^- \[[ x-]\] \*\*P1-03\b.*$")
UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
REPOSITORY_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?![A-Za-z0-9_.-])"
)
REPOSITORY_ID_SYMBOLS = frozenset(
    {"repo_id", "repo_ids", "repository_id", "repository_ids", "repositories", "model_id", "model_ids"}
)
STATIC_EXPOSURE_UNKNOWN_RATIONALE = (
    "Static source inspection cannot prove the returned output contract without execution."
)


class ScreeningError(RuntimeError):
    """Base error for an invalid or unsafe screening operation."""


class ScreeningSchemaError(ScreeningError):
    """Raised when canonical screening evidence violates its closed schema."""


class InventoryError(ScreeningError):
    """Raised when the frozen inventory is incomplete or has drifted."""


class PublicationError(ScreeningError):
    """Raised when screening artifacts cannot be safely published."""


class RoadmapConsistencyError(ScreeningError):
    """Raised when evidence does not authorize the requested roadmap state."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScreeningSchemaError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def frozen_inventory_snapshot() -> list[dict[str, Any]]:
    return [
        {"family": family, "identifiers": list(identifiers)}
        for family, identifiers in FROZEN_INVENTORY_BASELINE.items()
    ]


def pinned_catalog_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "family": family,
            "identifiers": list(identifiers),
            "official_sources": [
                {
                    "identifier": identifier,
                    "source_ref": source_ref,
                    "url": url,
                    "source_version_status": version_status,
                    "source_version_or_date": version,
                    "stable_locator": stable_locator,
                }
                for identifier, source_ref, url, version_status, version, stable_locator in sources
            ],
            "retrieved_at_utc": retrieved_at_utc,
        }
        for family, (identifiers, sources, retrieved_at_utc) in PINNED_EXECUTION_CATALOG.items()
    ]


def validate_embedded_manifests() -> None:
    if _canonical_json_sha256(frozen_inventory_snapshot()) != FROZEN_INVENTORY_BASELINE_SHA256:
        raise InventoryError("embedded frozen inventory manifest hash is invalid")
    if _canonical_json_sha256(pinned_catalog_snapshot()) != PINNED_EXECUTION_CATALOG_SHA256:
        raise InventoryError("embedded pinned execution catalog hash is invalid")


def _require_enum(value: object, allowed: frozenset[str], name: str) -> None:
    if value not in allowed:
        raise ScreeningSchemaError(f"{name} has unsupported value {value!r}")


def _require_utc(value: object, name: str) -> None:
    if not isinstance(value, str) or not UTC_PATTERN.fullmatch(value):
        raise ScreeningSchemaError(f"{name} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScreeningSchemaError(f"{name} is malformed") from exc


def _fact(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"status", "value", "source_refs", "rationale"}:
        raise ScreeningSchemaError(
            f"{name} must contain exactly status, value, source_refs, and rationale"
        )
    _require_enum(value["status"], FACT_STATUSES, f"{name}.status")
    if not isinstance(value["source_refs"], list) or not value["source_refs"]:
        raise ScreeningSchemaError(f"{name}.source_refs must be a non-empty list")
    if not all(isinstance(ref, str) and ref for ref in value["source_refs"]):
        raise ScreeningSchemaError(f"{name}.source_refs must contain non-empty strings")
    if not isinstance(value["rationale"], str) or not value["rationale"].strip():
        raise ScreeningSchemaError(f"{name}.rationale must be non-empty")
    if value["status"] == "unknown" and value["value"] is not None and value["value"] != "unknown":
        raise ScreeningSchemaError(f"{name} unknown facts must preserve an unknown value")
    return value


def _typed_known_value(
    value: object,
    name: str,
    expected_type: type[Any] | tuple[type[Any], ...],
) -> object | None:
    fact = _fact(value, name)
    if fact["status"] != "known":
        return None
    known = fact["value"]
    if known is None or known == "unknown" or known == "" or known == [] or known == {}:
        raise ScreeningSchemaError(f"{name} known facts cannot contain an unknown or empty sentinel")
    if not isinstance(known, expected_type) or (
        expected_type in {int, float, (int, float)} and isinstance(known, bool)
    ):
        raise ScreeningSchemaError(f"{name}.value has the wrong type")
    return known


def _typed_boolean_fact(value: object, name: str) -> bool | None:
    known = _typed_known_value(value, name, bool)
    return known if isinstance(known, bool) else None


def _all_fact_objects(value: object) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if set(value) == {"status", "value", "source_refs", "rationale"}:
            yield value
        else:
            for nested in value.values():
                yield from _all_fact_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_fact_objects(nested)


def canonical_unknown_fact_paths(value: Mapping[str, Any]) -> list[str]:
    """Return recursively discovered unknown fact paths in canonical lexical order."""

    paths: set[str] = set()

    def visit_known_value(current: object, path: str) -> None:
        if current == "unknown":
            paths.add(path)
        elif isinstance(current, dict):
            for key, nested in current.items():
                visit_known_value(nested, f"{path}.{key}")
        elif isinstance(current, list):
            for index, nested in enumerate(current):
                visit_known_value(nested, f"{path}[{index}]")

    def visit(current: object, path: str) -> None:
        if isinstance(current, dict):
            if set(current) == {"status", "value", "source_refs", "rationale"}:
                if current["status"] == "unknown":
                    paths.add(path)
                elif current["status"] == "known":
                    visit_known_value(current["value"], f"{path}.value")
                return
            for key, nested in current.items():
                if key == "unknowns":
                    continue
                visit(nested, f"{path}.{key}" if path else key)
        elif isinstance(current, list):
            for index, nested in enumerate(current):
                visit(nested, f"{path}[{index}]")

    visit(value, "")
    return sorted(paths)


def _family_heading(name: str) -> str:
    aliases = {
        "Chronos and Chronos-2": "Chronos / Chronos-2",
        "TabPFN time series": "TabPFN",
        "Toto and Toto-2": "Toto / Toto-2",
    }
    return aliases.get(name, name)


def load_inventory_baseline(path: Path) -> dict[str, tuple[str, ...]]:
    """Parse the persisted planning baseline directly as the independent oracle."""

    text = path.read_text(encoding="utf-8")
    official = text.split("## Installed TimeCopilot", 1)[0]
    inventories: dict[str, list[str]] = {}
    current_family: str | None = None
    for line in official.splitlines():
        if line.startswith("### "):
            current_family = _family_heading(line[4:].strip())
            inventories.setdefault(current_family, [])
            continue
        if current_family is None:
            continue
        label = line.lower()
        if not line.startswith("-") or not any(
            token in label
            for token in (
                "identifiers:", "identifier:", "collection identifiers:",
                "adapter defaults", "historical gap:",
            )
        ):
            continue
        for identifier in re.findall(r"`([^`]+)`", line):
            if "/" in identifier or identifier == "TabPFN-TS-3":
                inventories[current_family].append(identifier)
    parsed_identifiers = [identifier for identifiers in inventories.values() for identifier in identifiers]
    duplicates = sorted(
        identifier for identifier, count in Counter(parsed_identifiers).items() if count > 1
    )
    if duplicates:
        raise InventoryError(f"baseline contains duplicate identifiers: {', '.join(duplicates)}")
    empty = [family for family, identifiers in inventories.items() if not identifiers]
    if empty:
        raise InventoryError(f"baseline contains families without parsed identifiers: {', '.join(empty)}")
    return {family: tuple(ids) for family, ids in inventories.items()}


def load_source_registry(record_or_path: Mapping[str, Any] | Path) -> dict[str, dict[str, Any]]:
    """Load the compact source registry without contacting any source."""

    if isinstance(record_or_path, Path):
        raw = json.loads(record_or_path.read_text(encoding="utf-8"))
        registry = raw.get("source_registry") if isinstance(raw, dict) else None
    else:
        registry = record_or_path.get("source_registry")
    if not isinstance(registry, dict) or not registry:
        raise ScreeningSchemaError("source_registry must be a non-empty object")
    for source_id, source in registry.items():
        if not isinstance(source_id, str) or not source_id.startswith("src:") or not isinstance(source, dict):
            raise ScreeningSchemaError("source_registry entries require src: identifiers and objects")
        if not BASE_SOURCE_FIELDS.issubset(source):
            raise ScreeningSchemaError(f"source registry entry {source_id} is incomplete")
        _require_utc(source["retrieved_at_utc"], f"source_registry.{source_id}.retrieved_at_utc")
        for key in BASE_SOURCE_FIELDS - {"retrieved_at_utc"}:
            if not isinstance(source[key], str) or not source[key].strip():
                raise ScreeningSchemaError(f"source_registry.{source_id}.{key} must be non-empty")
    return dict(registry)


def validate_source_registry(
    registry: Mapping[str, Mapping[str, Any]], observations: Mapping[str, Any]
) -> None:
    official_by_ref = {
        source_ref: (url, version, stable_locator, retrieved_at_utc)
        for _, sources, retrieved_at_utc in PINNED_EXECUTION_CATALOG.values()
        for _, source_ref, url, _, version, stable_locator in sources
    }
    local_refs = set(PINNED_LOCAL_LOCATORS)
    expected_refs = set(official_by_ref) | local_refs | {"src:inventory:baseline"}
    if set(registry) != expected_refs:
        missing = sorted(expected_refs - set(registry))
        extra = sorted(set(registry) - expected_refs)
        raise ScreeningSchemaError(
            f"source_registry approved closure failed; missing={missing}, extra={extra}"
        )
    for source_ref, source in registry.items():
        if source.get("source_kind") not in SOURCE_KINDS:
            raise ScreeningSchemaError(
                f"source_registry.{source_ref} has an unapproved source kind"
            )
        if source_ref == "src:inventory:baseline":
            expected_kind = "persisted_inventory_baseline"
            expected_path = INVENTORY_BASELINE_RELATIVE_PATH.as_posix()
            expected = {
                "url_or_path": expected_path,
                "source_kind": expected_kind,
                "source_version_or_date": INVENTORY_SOURCE_VERSION_OR_DATE,
                "retrieved_at_utc": EXECUTION_CATALOG_CAPTURED_AT_UTC,
                "stable_locator": INVENTORY_SOURCE_STABLE_LOCATOR,
                "persisted_inventory_path": expected_path,
                "sha256": FROZEN_INVENTORY_BASELINE_SHA256,
            }
            if set(source) != INVENTORY_SOURCE_FIELDS or dict(source) != expected:
                raise ScreeningSchemaError("inventory registry entry differs from frozen provenance")
            continue
        if source_ref in local_refs:
            expected_kind = "observed_local_package_source"
            locator = PINNED_LOCAL_LOCATORS[source_ref]
            observed = next(
                (item for item in observations["adapter_sources"] if item["stable_locator"] == locator),
                None,
            )
            if observed is None:
                raise ScreeningSchemaError("local registry locator is absent from observations")
            try:
                relative_path = Path(observed["adapter_module_path"]).relative_to(
                    Path(observations["project_root"])
                ).as_posix()
            except ValueError as exc:
                raise ScreeningSchemaError("observed adapter path is outside the project root") from exc
            expected = {
                "url_or_path": relative_path,
                "source_kind": expected_kind,
                "source_version_or_date": f"timecopilot=={observed['distribution_version']}",
                "retrieved_at_utc": observed["observed_at_utc"],
                "stable_locator": locator,
                "sha256": observed["adapter_module_sha256"],
            }
            if set(source) != LOCAL_SOURCE_FIELDS or dict(source) != expected:
                raise ScreeningSchemaError("local registry entry differs from observed adapter provenance")
            continue
        if source_ref == "src:official:tabpfn_ts_3":
            expected_kind = "official_repository_and_docs"
        elif source_ref == "src:official:timegpt":
            expected_kind = "official_sdk_documentation"
        else:
            expected_kind = "official_model_card"
        url, version, stable_locator, retrieved_at_utc = official_by_ref[source_ref]
        expected = {
            "url_or_path": url,
            "source_kind": expected_kind,
            "source_version_or_date": version,
            "retrieved_at_utc": retrieved_at_utc,
            "stable_locator": stable_locator,
        }
        if set(source) != OFFICIAL_SOURCE_FIELDS or dict(source) != expected:
            raise ScreeningSchemaError(
                f"source_registry.{source_ref} differs from pinned official provenance"
            )


def validate_execution_official_catalog(
    catalog: object,
    baseline: Mapping[str, Sequence[str]],
    *,
    baseline_sha256: str,
) -> None:
    """Validate the independent execution-time official catalog artifact."""

    if not isinstance(catalog, dict) or set(catalog) != {
        "schema_version", "task_id", "captured_at_utc", "inventory_baseline_path",
        "inventory_baseline_sha256", "families", "catalog_content_sha256",
    }:
        raise InventoryError("execution official catalog has an invalid closed schema")
    if catalog["schema_version"] != 1 or catalog["task_id"] != TASK_ID:
        raise InventoryError("execution official catalog identity is invalid")
    _require_utc(catalog["captured_at_utc"], "execution catalog captured_at_utc")
    if catalog["captured_at_utc"] != EXECUTION_CATALOG_CAPTURED_AT_UTC:
        raise InventoryError("execution catalog capture time is invalid")
    if catalog["inventory_baseline_path"] != INVENTORY_BASELINE_RELATIVE_PATH.as_posix() or catalog[
        "inventory_baseline_sha256"
    ] != baseline_sha256:
        raise InventoryError("execution catalog baseline binding is invalid")
    value = catalog["families"]
    if not isinstance(value, list) or len(value) != len(baseline):
        raise InventoryError("execution catalog must contain every baseline family once")
    families: list[str] = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {
            "family", "identifiers", "official_sources", "retrieved_at_utc"
        }:
            raise InventoryError("official catalog entries have an invalid closed schema")
        family = entry["family"]
        if not isinstance(family, str) or family not in baseline:
            raise InventoryError(f"official catalog has an unknown family: {family!r}")
        families.append(family)
        identifiers = entry["identifiers"]
        if not isinstance(identifiers, list) or not all(
            isinstance(identifier, str) and identifier for identifier in identifiers
        ):
            raise InventoryError(f"official catalog identifiers are invalid for {family}")
        duplicates = sorted(
            identifier for identifier, count in Counter(identifiers).items() if count > 1
        )
        if duplicates:
            raise InventoryError(
                f"official catalog contains duplicate identifiers for {family}: {duplicates}"
            )
        if identifiers != list(baseline[family]):
            raise InventoryError(f"official catalog drift detected for {family}")
        sources = entry["official_sources"]
        if not isinstance(sources, list) or not sources:
            raise InventoryError(f"official catalog sources are missing for {family}")
        source_refs: list[str] = []
        for source in sources:
            if not isinstance(source, dict) or set(source) != {
                "source_ref", "url", "source_version_status", "source_version_or_date"
            }:
                raise InventoryError(f"official catalog source schema is invalid for {family}")
            if not isinstance(source["source_ref"], str) or not source["source_ref"].startswith("src:official:"):
                raise InventoryError(f"official catalog source ref is invalid for {family}")
            source_refs.append(source["source_ref"])
            if not isinstance(source["url"], str) or not source["url"].startswith(("https://", "http://")):
                raise InventoryError(f"official catalog URL is invalid for {family}")
            _require_enum(
                source["source_version_status"],
                frozenset({"known", "unknown"}),
                "official catalog source version status",
            )
            version = source["source_version_or_date"]
            if source["source_version_status"] == "known":
                if not isinstance(version, str) or not version.strip() or version == "unknown":
                    raise InventoryError(f"known official catalog version is invalid for {family}")
            elif version != "unknown":
                raise InventoryError(f"unknown official catalog version must stay unknown for {family}")
        if len(source_refs) != len(set(source_refs)):
            raise InventoryError(f"official catalog source refs are duplicated for {family}")
        _require_utc(entry["retrieved_at_utc"], f"execution_catalog.{family}.retrieved_at_utc")
        if entry["retrieved_at_utc"] != EXECUTION_CATALOG_CAPTURED_AT_UTC:
            raise InventoryError(f"execution catalog retrieval time is invalid for {family}")
    if families != list(baseline):
        raise InventoryError("official catalog family order or uniqueness has drifted")
    content_sha256 = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if catalog["catalog_content_sha256"] != content_sha256:
        raise InventoryError("execution official catalog content SHA-256 is invalid")


def validate_official_catalog_snapshot(
    value: object,
    registry: Mapping[str, Any],
) -> None:
    """Require the ledger snapshot to exactly mirror the pinned code manifest."""

    expected = pinned_catalog_snapshot()
    if value != expected:
        raise InventoryError("ledger official catalog snapshot differs from pinned manifest")
    for family in expected:
        for source in family["official_sources"]:
            registered = registry.get(source["source_ref"])
            if not isinstance(registered, dict):
                raise InventoryError("catalog source ref is absent from the ledger registry")
            if registered["url_or_path"] != source["url"] or registered[
                "source_version_or_date"
            ] != source["source_version_or_date"] or registered[
                "retrieved_at_utc"
            ] != family["retrieved_at_utc"]:
                raise InventoryError("catalog source differs from the ledger source registry")


def build_inventory_witnesses(
    baseline: Mapping[str, Sequence[str]],
    mappings: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Build and verify one exact disposition for every frozen identifier."""

    if set(baseline) != set(mappings):
        missing = sorted(set(baseline) - set(mappings))
        orphan = sorted(set(mappings) - set(baseline))
        raise InventoryError(f"inventory family drift; missing={missing}, orphan={orphan}")
    witnesses: list[dict[str, Any]] = []
    for family, expected in baseline.items():
        entries = list(mappings[family])
        identifiers = [str(entry.get("identifier", "")) for entry in entries]
        duplicates = sorted(identifier for identifier, count in Counter(identifiers).items() if count > 1)
        missing = sorted(set(expected) - set(identifiers))
        orphan = sorted(set(identifiers) - set(expected))
        if duplicates or missing or orphan or len(entries) != len(expected):
            raise InventoryError(
                f"{family} inventory mismatch; missing={missing}, duplicate={duplicates}, orphan={orphan}"
            )
        for entry in entries:
            _require_enum(entry.get("disposition"), DISPOSITIONS, "inventory disposition")
            if entry["disposition"] in {"screened_variant", "alias"} and not str(
                entry.get("canonical_variant_id", "")
            ).strip():
                raise InventoryError("screened and alias dispositions require canonical_variant_id")
        witnesses.append(
            {
                "family": family,
                "baseline_identifiers": list(expected),
                "mappings": entries,
                "checks": {"missing": [], "duplicate": [], "orphan": [], "complete": True},
            }
        )
    return witnesses


def validate_inventory_closure(
    baseline: Mapping[str, Sequence[str]],
    witnesses: object,
    variant_ids: set[str],
) -> None:
    """Validate forward inventory coverage and exact reverse variant closure."""

    if not isinstance(witnesses, list):
        raise InventoryError("inventory_witnesses must be a list")
    mappings: dict[str, list[Mapping[str, Any]]] = {}
    witnesses_by_family: dict[str, dict[str, Any]] = {}
    for witness in witnesses:
        if not isinstance(witness, dict):
            raise InventoryError("inventory witnesses must be objects")
        family = str(witness.get("family"))
        if family in mappings:
            raise InventoryError(f"duplicate inventory witness for {family}")
        raw_mappings = witness.get("mappings")
        if not isinstance(raw_mappings, list) or not all(
            isinstance(mapping, dict) for mapping in raw_mappings
        ):
            raise InventoryError(f"inventory mappings are invalid for {family}")
        mappings[family] = raw_mappings
        witnesses_by_family[family] = witness
    expected_witnesses = build_inventory_witnesses(baseline, mappings)
    for expected in expected_witnesses:
        actual = witnesses_by_family[expected["family"]]
        if actual.get("baseline_identifiers") != expected["baseline_identifiers"]:
            raise InventoryError("inventory witness baseline identifiers have drifted")
        if actual.get("mappings") != expected["mappings"] or actual.get("checks") != expected["checks"]:
            raise InventoryError("inventory witness mappings or checks are not canonical")
    mapped_variant_ids = {
        entry["canonical_variant_id"]
        for entries in mappings.values()
        for entry in entries
        if entry["disposition"] in {"screened_variant", "alias"}
    }
    expected_variant_ids = mapped_variant_ids | {
        "theforecastingcompany/t0-alpha",
        "TimeGPT",
    }
    if variant_ids != expected_variant_ids:
        missing_variants = sorted(str(value) for value in expected_variant_ids - variant_ids)
        extra_variants = sorted(str(value) for value in variant_ids - expected_variant_ids)
        raise InventoryError(
            f"variant reverse closure failed; missing={missing_variants}, extra={extra_variants}"
        )
    mappings_by_canonical: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for family, entries in mappings.items():
        for entry in entries:
            if entry["disposition"] in {"screened_variant", "alias"}:
                mappings_by_canonical.setdefault(str(entry["canonical_variant_id"]), []).append(
                    (family, entry)
                )
    for canonical_variant_id in variant_ids - {
        "theforecastingcompany/t0-alpha",
        "TimeGPT",
    }:
        canonical_entries = mappings_by_canonical.get(canonical_variant_id, [])
        primaries = [
            (family, entry)
            for family, entry in canonical_entries
            if entry["disposition"] == "screened_variant"
        ]
        if len(primaries) != 1 or primaries[0][1]["identifier"] != canonical_variant_id:
            raise InventoryError(
                f"{canonical_variant_id} requires exactly one matching screened_variant primary"
            )
        primary_family, primary = primaries[0]
        if any(
            entry is not primary and entry["disposition"] != "alias"
            for _, entry in canonical_entries
        ):
            raise InventoryError(
                f"additional identifiers for {canonical_variant_id} must be aliases"
            )
        if any(
            family != primary_family
            for family, entry in canonical_entries
            if entry is not primary
        ):
            raise InventoryError(
                f"aliases for {canonical_variant_id} must share the primary witness family"
            )


def validate_variant_oracle_bindings(
    variant_records: Sequence[Mapping[str, Any]],
    witnesses: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
) -> None:
    """Bind every variant to one primary witness and one pinned official source."""

    primary_by_id: dict[str, tuple[str, str]] = {}
    for witness in witnesses:
        family = str(witness["family"])
        for mapping in witness["mappings"]:
            if mapping["disposition"] != "screened_variant":
                continue
            identifier = str(mapping["canonical_variant_id"])
            if identifier in primary_by_id:
                raise InventoryError(f"duplicate primary witness for {identifier}")
            primary_by_id[identifier] = (family, "screened_variant")
    primary_by_id.update(
        {
            "theforecastingcompany/t0-alpha": ("T0", "screened_variant"),
            "TimeGPT": ("TimeGPT", "screened_variant"),
        }
    )
    catalog_by_id: dict[str, tuple[str, tuple[str, str, str, str, str, str], str]] = {}
    for family, (_, sources, retrieved_at_utc) in PINNED_EXECUTION_CATALOG.items():
        for source in sources:
            identifier = source[0]
            if identifier in catalog_by_id:
                raise InventoryError(f"duplicate pinned catalog source for {identifier}")
            catalog_by_id[identifier] = (family, source, retrieved_at_utc)
    for variant in variant_records:
        identifier = str(variant["canonical_variant_id"])
        if identifier not in primary_by_id or identifier not in catalog_by_id:
            raise InventoryError(f"variant {identifier} lacks a unique oracle binding")
        witness_family, disposition = primary_by_id[identifier]
        catalog_family, source, retrieved_at_utc = catalog_by_id[identifier]
        if variant["family"] != witness_family or variant["family"] != catalog_family:
            raise InventoryError(f"variant {identifier} family differs from its primary witness")
        if variant["inventory_disposition"] != disposition:
            raise InventoryError(f"variant {identifier} disposition differs from its primary witness")
        _, source_ref, url, version_status, version, _ = source
        expected_facts = (
            ("official_source_url", "known", url),
            ("source_version_or_date", version_status, version),
            ("retrieved_at_utc", "known", retrieved_at_utc),
        )
        for fact_name, expected_status, expected_value in expected_facts:
            fact = _fact(variant[fact_name], fact_name)
            official_refs = [
                ref for ref in fact["source_refs"] if ref.startswith("src:official:")
            ]
            if (
                fact["status"] != expected_status
                or fact["value"] != expected_value
                or official_refs != [source_ref]
            ):
                raise InventoryError(
                    f"variant {identifier} {fact_name} differs from its primary official source"
                )
        registered = registry.get(source_ref)
        if not isinstance(registered, dict):
            raise InventoryError(f"variant {identifier} official source is absent from registry")


def _validate_license(value: object, name: str) -> None:
    fact = _fact(value, name)
    if fact["status"] != "known":
        return
    license_value = fact["value"]
    if not isinstance(license_value, dict) or set(license_value) != {
        "status", "identifier", "terms", "poc_use"
    }:
        raise ScreeningSchemaError(f"{name}.value has an invalid license schema")
    _require_enum(license_value["status"], LICENSE_STATUSES, f"{name}.status")
    _require_enum(license_value["poc_use"], POC_USE_STATUSES, f"{name}.poc_use")
    if license_value["status"] == "known" and (
        not isinstance(license_value["identifier"], str)
        or not license_value["identifier"].strip()
        or not isinstance(license_value["terms"], str)
        or not license_value["terms"].strip()
    ):
        raise ScreeningSchemaError(
            f"{name} known licenses require non-empty identifier and terms"
        )


def _variant_official_source_ref(identifier: str) -> str:
    matches = [
        source_ref
        for _, sources, _ in PINNED_EXECUTION_CATALOG.values()
        for source_identifier, source_ref, _, _, _, _ in sources
        if source_identifier == identifier
    ]
    if len(matches) != 1:
        raise ScreeningSchemaError(f"variant {identifier} lacks one pinned official source")
    return matches[0]


def validate_variant_provenance(record: Mapping[str, Any]) -> None:
    identifier = str(record["canonical_variant_id"])
    official_ref = _variant_official_source_ref(identifier)
    local_ref = PINNED_LOCAL_SOURCE_BY_FAMILY.get(str(record["family"]))
    if local_ref is None:
        raise ScreeningSchemaError(f"variant {identifier} lacks one pinned local adapter source")
    inventory_ref = "src:inventory:baseline"
    official_paths = (
        "official_source_url", "source_version_or_date", "retrieved_at_utc",
        "artifact_identity", "artifact_size", "runtime_framework", "device_status",
        "offline_after_acquisition", "cold_start_offline", "runtime_auth",
        "acquisition_auth", "code_license", "artifact_license",
        "documented_memory_vram_requirement", "fit_against_16gb_target",
    )
    for path in official_paths:
        fact = _fact(record[path], path)
        if fact["source_refs"] != [official_ref, inventory_ref]:
            raise ScreeningSchemaError(f"{identifier}.{path} provenance refs are not canonical")
    for path in MODEL_NATIVE_FIELDS:
        fact = _fact(record["model_native"][path], f"model_native.{path}")
        if fact["source_refs"] != [official_ref, inventory_ref]:
            raise ScreeningSchemaError(
                f"{identifier}.model_native.{path} provenance refs are not canonical"
            )
    for path in PROBABILISTIC_FIELDS:
        fact = _fact(record["probabilistic"][path], f"probabilistic.{path}")
        if fact["source_refs"] != [official_ref, inventory_ref]:
            raise ScreeningSchemaError(
                f"{identifier}.probabilistic.{path} provenance refs are not canonical"
            )
    package_fact = _fact(
        record["applicable_installed_package_versions"],
        "applicable_installed_package_versions",
    )
    if package_fact["source_refs"] != [local_ref, inventory_ref]:
        raise ScreeningSchemaError(
            f"{identifier}.applicable_installed_package_versions provenance refs are not canonical"
        )
    for path in ADAPTER_FIELDS:
        fact = _fact(record["timecopilot_adapter"][path], f"timecopilot_adapter.{path}")
        if fact["source_refs"] != [local_ref, inventory_ref]:
            raise ScreeningSchemaError(
                f"{identifier}.timecopilot_adapter.{path} provenance refs are not canonical"
            )
    summary = _fact(
        record["monthly_history_only_60x3_support"],
        "monthly_history_only_60x3_support",
    )
    if summary["source_refs"] != [official_ref, local_ref, inventory_ref]:
        raise ScreeningSchemaError(
            f"{identifier}.monthly_history_only_60x3_support provenance refs are not canonical"
        )


def derive_monthly_history_only_60x3(record: Mapping[str, Any]) -> bool | None:
    native = record.get("model_native")
    adapter = record.get("timecopilot_adapter")
    probabilistic = record.get("probabilistic")
    if not all(isinstance(group, dict) for group in (native, adapter, probabilistic)):
        raise ScreeningSchemaError("model_native, timecopilot_adapter, and probabilistic must be objects")
    assert isinstance(native, dict) and isinstance(adapter, dict) and isinstance(probabilistic, dict)
    for name in MODEL_NATIVE_FIELDS:
        _fact(native[name], f"model_native.{name}")
    for name in ADAPTER_FIELDS:
        _fact(adapter[name], f"timecopilot_adapter.{name}")
    for name in PROBABILISTIC_FIELDS:
        _fact(probabilistic[name], f"probabilistic.{name}")
    # Static adapter inspection deliberately cannot prove the returned output
    # contract.  Therefore this screen can never establish 60x3 support.
    return None


def classify_variant_record(record: Mapping[str, Any]) -> str:
    """Classify fixed exclusions and blocked records before the universal static unknown."""

    family = str(record.get("family", ""))
    variant_id = str(record.get("canonical_variant_id", ""))
    if family == "T0" or variant_id in {"T0", "theforecastingcompany/t0-alpha"}:
        return "excluded"
    if family == "TimeGPT" or variant_id == "TimeGPT":
        return "excluded"
    if any(fact.get("status") == "blocked" for fact in _all_fact_objects(record)):
        return "blocked"

    required_facts = (
        "official_source_url", "source_version_or_date", "retrieved_at_utc",
        "applicable_installed_package_versions", "artifact_identity", "artifact_size",
        "runtime_framework", "device_status", "offline_after_acquisition", "cold_start_offline",
        "runtime_auth", "acquisition_auth", "code_license", "artifact_license",
        "documented_memory_vram_requirement", "fit_against_16gb_target",
    )
    for name in required_facts:
        _fact(record[name], name)
    derive_monthly_history_only_60x3(record)
    return "unknown/ineligible"


def _validate_variant(
    record: dict[str, Any],
    registry: Mapping[str, Any],
    observations: Mapping[str, Any] | None = None,
    *,
    validate_provenance: bool = True,
) -> None:
    missing = sorted(REQUIRED_VARIANT_FIELDS - set(record))
    if missing:
        raise ScreeningSchemaError(f"variant record missing fields: {', '.join(missing)}")
    extra = sorted(set(record) - REQUIRED_VARIANT_FIELDS)
    if extra:
        raise ScreeningSchemaError(f"variant record has unsupported fields: {', '.join(extra)}")
    if not str(record["family"]).strip() or not str(record["canonical_variant_id"]).strip():
        raise ScreeningSchemaError("variant identity must be non-empty")
    canonical_variant_id = str(record["canonical_variant_id"])
    _require_enum(record["inventory_disposition"], DISPOSITIONS, "inventory_disposition")
    _require_enum(record["result"], RESULTS, "result")
    if record["device_target"] != "cuda":
        raise ScreeningSchemaError("device_target must be cuda")
    retrieved_at = _typed_known_value(record["retrieved_at_utc"], "retrieved_at_utc", str)
    if retrieved_at is not None:
        _require_utc(retrieved_at, "retrieved_at_utc.value")
    for name, allowed in (
        ("device_status", DEVICE_STATUSES),
        ("offline_after_acquisition", OFFLINE_STATUSES),
        ("cold_start_offline", COLD_START_STATUSES),
        ("runtime_auth", AUTH_STATUSES),
        ("acquisition_auth", AUTH_STATUSES),
    ):
        fact = _fact(record[name], name)
        if fact["status"] == "known":
            if fact["value"] == "unknown":
                raise ScreeningSchemaError(
                    f"{name} known facts cannot contain an unknown or empty sentinel"
                )
            _require_enum(fact["value"], allowed, f"{name}.value")
    _validate_license(record["code_license"], "code_license")
    _validate_license(record["artifact_license"], "artifact_license")
    for name in ("official_source_url", "source_version_or_date", "runtime_framework"):
        _typed_known_value(record[name], name, str)
    versions = _typed_known_value(
        record["applicable_installed_package_versions"],
        "applicable_installed_package_versions",
        dict,
    )
    if isinstance(versions, dict) and (
        not all(isinstance(name, str) and name for name in versions)
        or not all(version is None or isinstance(version, str) and version for version in versions.values())
    ):
        raise ScreeningSchemaError("applicable installed package versions are invalid")
    artifact_identity = _typed_known_value(record["artifact_identity"], "artifact_identity", str)
    if artifact_identity != canonical_variant_id:
        raise ScreeningSchemaError("artifact_identity must equal canonical_variant_id")
    _typed_known_value(record["artifact_size"], "artifact_size", dict)
    _typed_known_value(
        record["documented_memory_vram_requirement"],
        "documented_memory_vram_requirement",
        dict,
    )
    _typed_boolean_fact(record["fit_against_16gb_target"], "fit_against_16gb_target")
    for name in ("history_only", "univariate_only", "model_specific_minimums"):
        _typed_boolean_fact(record["model_native"][name], f"model_native.{name}")
    for name in ("usable_context_months", "forecast_horizon_months"):
        _typed_known_value(record["model_native"][name], f"model_native.{name}", int)
    _typed_known_value(record["model_native"]["monthly_frequency"], "model_native.monthly_frequency", str)
    for name in ("point", "interval", "quantile"):
        adapter_exposure = _fact(
            record["timecopilot_adapter"][name], f"timecopilot_adapter.{name}"
        )
        if adapter_exposure["status"] != "unknown" or adapter_exposure["value"] != "unknown":
            raise ScreeningSchemaError(
                f"timecopilot_adapter.{name} must have unknown status and value"
            )
        _typed_boolean_fact(record["probabilistic"][name], f"probabilistic.{name}")
    adapter_identity = _typed_known_value(
        record["timecopilot_adapter"]["artifact_identity"],
        "timecopilot_adapter.artifact_identity",
        str,
    )
    if adapter_identity is not None and adapter_identity != canonical_variant_id:
        raise ScreeningSchemaError("known adapter artifact identity must equal canonical_variant_id")
    _typed_boolean_fact(
        record["monthly_history_only_60x3_support"], "monthly_history_only_60x3_support"
    )
    for fact in _all_fact_objects(record):
        checked = _fact(fact, "fact")
        missing_refs = sorted(set(checked["source_refs"]) - set(registry))
        if missing_refs:
            raise ScreeningSchemaError(f"fact cites unknown source refs: {', '.join(missing_refs)}")
    if validate_provenance:
        validate_variant_provenance(record)
    derived_support = derive_monthly_history_only_60x3(record)
    summary = record["monthly_history_only_60x3_support"]
    if summary["status"] == "known" and summary["value"] is not derived_support:
        raise ScreeningSchemaError("60x3 summary disagrees with its subclaims")
    if summary["status"] == "unknown" and derived_support is not None:
        raise ScreeningSchemaError("60x3 summary erases a derivable value")
    expected = classify_variant_record(record)
    if record["result"] != expected:
        raise ScreeningSchemaError(
            f"variant {record['canonical_variant_id']} result {record['result']!r} != derived {expected!r}"
        )
    if not isinstance(record["notes"], list) or not isinstance(record["unknowns"], list):
        raise ScreeningSchemaError("variant notes and unknowns must be lists")
    expected_unknowns = canonical_unknown_fact_paths(record)
    if record["unknowns"] != expected_unknowns:
        raise ScreeningSchemaError(
            "variant unknowns must exactly match canonical recursively derived fact paths"
        )
    if record["family"] == "T0" and not any("conflict" in str(note).lower() for note in record["notes"]):
        raise ScreeningSchemaError("T0 must preserve the source-timing conflict note")
    if record["family"] == "TimeGPT" and not any("api" in str(note).lower() for note in record["notes"]):
        raise ScreeningSchemaError("TimeGPT must preserve its API-backed exclusion note")
    if observations is not None:
        _validate_variant_observation_binding(record, registry, observations)


def _validate_variant_observation_binding(
    record: Mapping[str, Any],
    registry: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> None:
    distribution_versions = {
        item["distribution_name"]: item["distribution_version"]
        for item in observations["distributions"]
    }
    versions = _fact(
        record["applicable_installed_package_versions"],
        "applicable_installed_package_versions",
    )
    if versions["status"] == "known" and any(
        name not in distribution_versions or distribution_versions[name] != version
        for name, version in versions["value"].items()
    ):
        raise ScreeningSchemaError("applicable package versions disagree with local observations")
    local_refs = {
        ref
        for fact in record["timecopilot_adapter"].values()
        for ref in _fact(fact, "timecopilot_adapter fact")["source_refs"]
        if registry[ref].get("source_kind") == "observed_local_package_source"
    }
    if len(local_refs) != 1:
        raise ScreeningSchemaError("adapter facts must bind exactly one local adapter source")
    source = registry[next(iter(local_refs))]
    locator = source["stable_locator"]
    observed_by_locator = {
        item["stable_locator"]: item for item in observations["adapter_sources"]
    }
    if locator not in observed_by_locator:
        raise ScreeningSchemaError("adapter fact source locator is absent from observations")
    observed = observed_by_locator[locator]
    if source.get("sha256") != observed["adapter_module_sha256"]:
        raise ScreeningSchemaError("adapter source registry SHA-256 disagrees with observations")
    if source["source_version_or_date"] != f"timecopilot=={observed['distribution_version']}":
        raise ScreeningSchemaError("adapter source version disagrees with observations")
    if source["retrieved_at_utc"] != observed["observed_at_utc"]:
        raise ScreeningSchemaError("adapter source observation time disagrees with observations")
    adapter_identity = _fact(
        record["timecopilot_adapter"]["artifact_identity"],
        "timecopilot_adapter.artifact_identity",
    )
    if adapter_identity["status"] == "known":
        if adapter_identity["value"] not in observed["repository_ids"]:
            raise ScreeningSchemaError(
                "known adapter artifact identity is absent from semantic repository-ID observations"
            )
    for fact_name, observation_name in (
        ("point", "point_exposure"),
        ("interval", "interval_exposure"),
        ("quantile", "quantile_exposure"),
    ):
        fact = _fact(record["timecopilot_adapter"][fact_name], fact_name)
        observed_value = observed[observation_name]
        if observed_value != "unknown" or fact["status"] != "unknown" or fact["value"] != "unknown":
            raise ScreeningSchemaError(
                f"adapter {fact_name} fact disagrees with observed source exposure"
            )


def derive_eligible_projection(variant_records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, int], list[str]]:
    results = [str(record["result"]) for record in variant_records]
    for result in results:
        _require_enum(result, RESULTS, "variant result")
    counts = {result: results.count(result) for result in sorted(RESULTS)}
    eligible = [str(record["canonical_variant_id"]) for record in variant_records if record["result"] == "eligible"]
    return counts, eligible


def validate_screening_record(
    record: dict[str, Any],
    *,
    repo_root: Path | None = None,
    fresh_observation: Mapping[str, Any] | None = None,
    validate_oracles: bool = True,
) -> None:
    validate_embedded_manifests()
    missing = sorted(REQUIRED_TOP_LEVEL_FIELDS - set(record))
    if missing:
        raise ScreeningSchemaError(f"screening evidence missing fields: {', '.join(missing)}")
    extra = sorted(set(record) - REQUIRED_TOP_LEVEL_FIELDS)
    if extra:
        raise ScreeningSchemaError(f"screening evidence has unsupported fields: {', '.join(extra)}")
    if record["schema_version"] != SCHEMA_VERSION or record["task_id"] != TASK_ID:
        raise ScreeningSchemaError("screening evidence identity is invalid")
    if not str(record["run_id"]).strip():
        raise ScreeningSchemaError("run_id must be non-empty")
    _require_utc(record["generated_at_utc"], "generated_at_utc")
    if record["target_gpu"] != {"device": "cuda", "memory_gb": TARGET_GPU_GB}:
        raise ScreeningSchemaError("target_gpu must be the exact 16 GB CUDA target")
    if record["p1_02_evidence_path"] != P1_02_EVIDENCE_RELATIVE_PATH.as_posix():
        raise ScreeningSchemaError("P1-02 evidence path is not canonical")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record["p1_02_evidence_sha256"])):
        raise ScreeningSchemaError("P1-02 evidence SHA-256 is malformed")
    if record["frozen_inventory_baseline_sha256"] != FROZEN_INVENTORY_BASELINE_SHA256:
        raise InventoryError("ledger frozen inventory manifest hash binding has drifted")
    if record["pinned_execution_catalog_sha256"] != PINNED_EXECUTION_CATALOG_SHA256:
        raise InventoryError("ledger pinned execution catalog hash binding has drifted")
    registry = load_source_registry(record)
    validate_local_package_observations(
        record["local_package_observations"],
        repo_root=repo_root,
        fresh_observation=fresh_observation,
    )
    observation_timestamp = record["local_package_observations"]["observed_at_utc"]
    adapter_timestamps = {
        adapter["observed_at_utc"]
        for adapter in record["local_package_observations"]["adapter_sources"]
    }
    if record["generated_at_utc"] != observation_timestamp or adapter_timestamps != {
        observation_timestamp
    }:
        raise ScreeningSchemaError(
            "generated and local package observation timestamps must match exactly"
        )
    if validate_oracles:
        validate_source_registry(registry, record["local_package_observations"])
    baseline_relative = INVENTORY_BASELINE_RELATIVE_PATH.as_posix()
    if not any(
        str(source["url_or_path"]) == baseline_relative
        or str(source.get("persisted_inventory_path", "")) == baseline_relative
        for source in registry.values()
    ):
        raise ScreeningSchemaError("source_registry must preserve the persisted inventory link")
    if not isinstance(record["variant_records"], list) or not record["variant_records"]:
        raise ScreeningSchemaError("variant_records must be a non-empty list")
    ids = [variant.get("canonical_variant_id") for variant in record["variant_records"]]
    if not all(isinstance(identifier, str) and identifier for identifier in ids):
        raise ScreeningSchemaError("canonical_variant_id values must be non-empty strings")
    if len(ids) != len(set(ids)):
        raise ScreeningSchemaError("canonical_variant_id values must be unique")
    for variant in record["variant_records"]:
        if not isinstance(variant, dict):
            raise ScreeningSchemaError("variant records must be objects")
        _validate_variant(
            variant,
            registry,
            record["local_package_observations"],
            validate_provenance=validate_oracles,
        )
    if not isinstance(record["inventory_witnesses"], list):
        raise ScreeningSchemaError("inventory_witnesses must be a list")
    if validate_oracles:
        baseline = dict(FROZEN_INVENTORY_BASELINE)
        validate_official_catalog_snapshot(record["official_catalog_snapshot"], registry)
        variant_ids = {str(identifier) for identifier in ids}
        validate_inventory_closure(baseline, record["inventory_witnesses"], variant_ids)
        validate_variant_oracle_bindings(
            record["variant_records"], record["inventory_witnesses"], registry
        )
    counts, eligible = derive_eligible_projection(record["variant_records"])
    if record["derived_counts"] != counts or record["eligible_variant_ids"] != eligible:
        raise ScreeningSchemaError("derived counts or eligible projection has drifted")
    _require_enum(record["overall_classification"], OVERALL_CLASSIFICATIONS, "overall_classification")
    blocked = any(variant["result"] == "blocked" for variant in record["variant_records"])
    if blocked and record["overall_classification"] != "blocked":
        raise ScreeningSchemaError("blocked facts must propagate to overall_classification")
    if not isinstance(record["checks"], dict) or not isinstance(record["errors"], list) or not isinstance(record["notes"], list):
        raise ScreeningSchemaError("checks, errors, and notes have invalid container types")
    if set(record["checks"]) != REQUIRED_CHECK_KEYS or not all(
        value is True for value in record["checks"].values()
    ):
        raise ScreeningSchemaError("checks must contain exactly the canonical true boolean keys")
    if record["overall_classification"] == "pass" and record["errors"]:
        raise ScreeningSchemaError("pass evidence requires all checks true and no errors")


def validate_p1_02_binding(repo_root: Path, record: Mapping[str, Any] | None = None) -> str:
    """Validate P1-02 first, then return/check the exact canonical evidence hash."""

    root = repo_root.resolve()
    target_pipeline.validate_published_state(root)
    path = root / P1_02_EVIDENCE_RELATIVE_PATH
    digest = sha256_file(path)
    if record is not None:
        if record.get("p1_02_evidence_path") != P1_02_EVIDENCE_RELATIVE_PATH.as_posix():
            raise ScreeningSchemaError("P1-02 binding path mismatch")
        if record.get("p1_02_evidence_sha256") != digest:
            raise ScreeningSchemaError("P1-02 binding hash mismatch")
    return digest


def _direct_string_literals(value: ast.AST | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return {value.value} if REPOSITORY_ID_PATTERN.fullmatch(value.value) else set()
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return set().union(*(_direct_string_literals(item) for item in value.elts))
    return set()


def _direct_string_literal(value: ast.AST) -> set[str]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return {value.value} if REPOSITORY_ID_PATTERN.fullmatch(value.value) else set()
    return set()


def _semantic_leaf(value: ast.AST) -> str | None:
    if isinstance(value, ast.Name):
        return value.id.lower()
    if isinstance(value, ast.Attribute):
        return value.attr.lower()
    return None


def _paired_assignment_ids(target: ast.AST, value: ast.AST | None) -> set[str]:
    leaf = _semantic_leaf(target)
    if leaf is not None:
        return _direct_string_literals(value) if leaf in REPOSITORY_ID_SYMBOLS else set()
    if (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
    ):
        return set().union(
            *(_paired_assignment_ids(target_item, value_item) for target_item, value_item in zip(target.elts, value.elts))
        )
    return set()


def _semantic_repository_ids(tree: ast.AST) -> list[str]:
    """Extract only repository IDs that participate in executable adapter semantics."""

    repositories: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = list(node.args.posonlyargs) + list(node.args.args)
            defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
            for argument, default in zip(positional, defaults):
                if argument.arg.lower() in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literals(default))
            for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                if argument.arg.lower() in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literals(default))
        elif isinstance(node, ast.Assign):
            if len(node.targets) == 1:
                repositories.update(_paired_assignment_ids(node.targets[0], node.value))
        elif isinstance(node, ast.AnnAssign):
            repositories.update(_paired_assignment_ids(node.target, node.value))
        elif isinstance(node, ast.Compare):
            expressions = [node.left, *node.comparators]
            for left, right in zip(expressions, expressions[1:]):
                if _semantic_leaf(left) in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literal(right))
                if _semantic_leaf(right) in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literal(left))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.lower() in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literals(value))
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in REPOSITORY_ID_SYMBOLS:
                    repositories.update(_direct_string_literals(keyword.value))
    return sorted(repositories)


def inspect_timecopilot_adapter_source(
    distribution: importlib.metadata.Distribution,
    adapter_file: str | Path,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Inspect an installed adapter as text/AST without importing package modules."""

    requested = Path(adapter_file).as_posix()
    if requested not in ADAPTER_MANIFEST:
        raise ScreeningError(f"adapter is not in the fixed P1-03 manifest: {requested}")
    files = tuple(distribution.files or ())
    match = next((entry for entry in files if Path(str(entry)).as_posix().endswith(requested)), None)
    if match is None:
        raise ScreeningError(f"adapter file is not present in timecopilot distribution: {requested}")
    path = Path(str(distribution.locate_file(match))).resolve()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    trees = [tree]
    supporting_sources: list[dict[str, str]] = []
    for support_locator in ADAPTER_MANIFEST[requested]:
        support_match = next(
            (
                entry
                for entry in files
                if Path(str(entry)).as_posix().endswith(support_locator)
            ),
            None,
        )
        if support_match is None:
            raise ScreeningError(f"adapter inspection requires installed support source: {support_locator}")
        support_path = Path(str(distribution.locate_file(support_match))).resolve()
        support_source = support_path.read_text(encoding="utf-8")
        trees.append(ast.parse(support_source, filename=str(support_path)))
        supporting_sources.append(
            {
                "adapter_module_path": str(support_path),
                "adapter_module_sha256": sha256_file(support_path),
                "stable_locator": Path(str(support_match)).as_posix(),
            }
        )
    distribution_name = distribution.metadata.get("Name", "timecopilot")
    repositories = sorted(
        {repository for current_tree in trees for repository in _semantic_repository_ids(current_tree)}
    )
    return {
        "distribution_name": distribution_name,
        "distribution_present": True,
        "distribution_version": distribution.version,
        "observed_at_utc": _timestamp(observed_at or _utc_now()),
        "adapter_module_path": str(path),
        "adapter_module_sha256": sha256_file(path),
        "stable_locator": Path(str(match)).as_posix(),
        "supporting_sources": supporting_sources,
        "repository_ids": repositories,
        "point_exposure": "unknown",
        "interval_exposure": "unknown",
        "quantile_exposure": "unknown",
        "exposure_rationale": STATIC_EXPOSURE_UNKNOWN_RATIONALE,
    }


def observe_local_packages(
    repo_root: Path,
    *,
    injected_versions: Mapping[str, str | None] | None = None,
    injected_adapter_sources: Sequence[Mapping[str, Any]] | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Observe only the explicit project .venv, or a frozen injected unit-test mapping."""

    root = repo_root.resolve()
    timestamp = _timestamp(observed_at or _utc_now())
    if injected_versions is not None:
        return {
            "interpreter_path": str(root / ".venv/bin/python"),
            "interpreter_realpath": "injected",
            "project_root": str(root),
            "python_version": "injected",
            "observed_at_utc": timestamp,
            "distributions": [
                {
                    "distribution_name": name,
                    "distribution_present": version is not None,
                    "distribution_version": version,
                }
                for name, version in injected_versions.items()
            ],
            "adapter_sources": [dict(source) for source in (injected_adapter_sources or ())],
            "observation_mode": "injected",
        }
    expected_interpreter = (root / ".venv/bin/python").resolve()
    actual_interpreter = Path(sys.executable).resolve()
    if actual_interpreter != expected_interpreter or sys.prefix != str((root / ".venv").resolve()):
        raise ScreeningError(
            f"local observation requires the exact project .venv interpreter: {expected_interpreter}"
        )
    distributions: list[dict[str, Any]] = []
    for name in INSTALLED_DISTRIBUTIONS:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            distributions.append({"distribution_name": name, "distribution_present": False, "distribution_version": None})
        else:
            distributions.append({"distribution_name": name, "distribution_present": True, "distribution_version": distribution.version})
    try:
        timecopilot_distribution = importlib.metadata.distribution("timecopilot")
    except importlib.metadata.PackageNotFoundError:
        adapters: list[dict[str, Any]] = []
    else:
        adapters = [
            inspect_timecopilot_adapter_source(timecopilot_distribution, adapter, observed_at=observed_at)
            for adapter in ADAPTER_MANIFEST
        ]
    return {
        "interpreter_path": str(root / ".venv/bin/python"),
        "interpreter_realpath": str(actual_interpreter),
        "project_root": str(root),
        "python_version": sys.version.split()[0],
        "observed_at_utc": timestamp,
        "distributions": distributions,
        "adapter_sources": adapters,
        "observation_mode": "project_venv",
    }


def _observation_comparable(value: Mapping[str, Any]) -> dict[str, Any]:
    comparable = json.loads(json.dumps(value))
    comparable.pop("observed_at_utc", None)
    for adapter in comparable.get("adapter_sources", []):
        adapter.pop("observed_at_utc", None)
    return comparable


def validate_local_package_observations(
    value: object,
    *,
    repo_root: Path | None = None,
    fresh_observation: Mapping[str, Any] | None = None,
) -> None:
    """Validate the closed observation schema and optionally bind it to the live .venv."""

    if not isinstance(value, dict) or set(value) != {
        "interpreter_path", "interpreter_realpath", "project_root", "python_version",
        "observed_at_utc", "distributions", "adapter_sources", "observation_mode",
    }:
        raise ScreeningSchemaError("local_package_observations has an invalid closed schema")
    if value["observation_mode"] not in {"project_venv", "injected"}:
        raise ScreeningSchemaError("local observation mode is unsupported")
    _require_utc(value["observed_at_utc"], "local_package_observations.observed_at_utc")
    for name in ("interpreter_path", "interpreter_realpath", "project_root", "python_version"):
        if not isinstance(value[name], str) or not value[name].strip():
            raise ScreeningSchemaError(f"local_package_observations.{name} must be non-empty")
    distributions = value["distributions"]
    if not isinstance(distributions, list) or len(distributions) != len(INSTALLED_DISTRIBUTIONS):
        raise ScreeningSchemaError("local distribution inventory is incomplete")
    distribution_names: list[str] = []
    for distribution in distributions:
        if not isinstance(distribution, dict) or set(distribution) != {
            "distribution_name", "distribution_present", "distribution_version"
        }:
            raise ScreeningSchemaError("local distribution observation has an invalid schema")
        name = distribution["distribution_name"]
        distribution_names.append(name)
        if type(distribution["distribution_present"]) is not bool:
            raise ScreeningSchemaError("distribution_present must be boolean")
        version = distribution["distribution_version"]
        if distribution["distribution_present"]:
            if not isinstance(version, str) or not version.strip() or version == "unknown":
                raise ScreeningSchemaError(f"present distribution {name} requires an exact version")
        elif version is not None:
            raise ScreeningSchemaError(f"absent distribution {name} cannot record a version")
    if distribution_names != list(INSTALLED_DISTRIBUTIONS):
        raise ScreeningSchemaError("local distribution names/order do not match the fixed manifest")
    adapters = value["adapter_sources"]
    if not isinstance(adapters, list) or len(adapters) != len(ADAPTER_MANIFEST):
        raise ScreeningSchemaError("adapter observations do not match the fixed manifest")
    locators: list[str] = []
    for adapter in adapters:
        if not isinstance(adapter, dict) or set(adapter) != {
            "distribution_name", "distribution_present", "distribution_version",
            "observed_at_utc", "adapter_module_path", "adapter_module_sha256",
            "stable_locator", "supporting_sources", "repository_ids", "point_exposure",
            "interval_exposure", "quantile_exposure", "exposure_rationale",
        }:
            raise ScreeningSchemaError("adapter observation has an invalid closed schema")
        locator = adapter["stable_locator"]
        locators.append(locator)
        if adapter["distribution_name"].lower() != "timecopilot" or adapter[
            "distribution_present"
        ] is not True:
            raise ScreeningSchemaError("adapter observation must bind the timecopilot distribution")
        if not isinstance(adapter["distribution_version"], str) or not adapter[
            "distribution_version"
        ].strip():
            raise ScreeningSchemaError("adapter observation requires a distribution version")
        _require_utc(adapter["observed_at_utc"], f"adapter.{locator}.observed_at_utc")
        if not isinstance(adapter["adapter_module_path"], str) or not Path(
            adapter["adapter_module_path"]
        ).is_absolute():
            raise ScreeningSchemaError("adapter_module_path must be absolute")
        if not re.fullmatch(r"[0-9a-f]{64}", str(adapter["adapter_module_sha256"])):
            raise ScreeningSchemaError("adapter_module_sha256 is malformed")
        repositories = adapter["repository_ids"]
        if not isinstance(repositories, list) or repositories != sorted(set(repositories)) or not all(
            isinstance(repository, str) and REPOSITORY_ID_PATTERN.fullmatch(repository)
            for repository in repositories
        ):
            raise ScreeningSchemaError("adapter repository IDs must be unique canonical IDs")
        for exposure in ("point_exposure", "interval_exposure", "quantile_exposure"):
            if adapter[exposure] != "unknown":
                raise ScreeningSchemaError(f"adapter {exposure} must be unknown")
        if adapter["exposure_rationale"] != STATIC_EXPOSURE_UNKNOWN_RATIONALE:
            raise ScreeningSchemaError("adapter exposure rationale is not canonical")
        supporting = adapter["supporting_sources"]
        expected_supporting = ADAPTER_MANIFEST.get(locator)
        if expected_supporting is None or not isinstance(supporting, list) or len(
            supporting
        ) != len(expected_supporting):
            raise ScreeningSchemaError("adapter supporting sources do not match the fixed manifest")
        for source, expected_locator in zip(supporting, expected_supporting):
            if not isinstance(source, dict) or set(source) != {
                "adapter_module_path", "adapter_module_sha256", "stable_locator"
            } or source["stable_locator"] != expected_locator:
                raise ScreeningSchemaError("adapter supporting source has an invalid schema or locator")
            if not re.fullmatch(r"[0-9a-f]{64}", str(source["adapter_module_sha256"])):
                raise ScreeningSchemaError("supporting source SHA-256 is malformed")
    if locators != list(ADAPTER_MANIFEST):
        raise ScreeningSchemaError("adapter locators/order do not match the fixed manifest")
    if repo_root is not None:
        root = repo_root.resolve()
        expected_interpreter = root / ".venv/bin/python"
        if value["observation_mode"] != "project_venv":
            raise ScreeningSchemaError("published observations must come from the project .venv")
        if value["interpreter_path"] != str(expected_interpreter) or value["project_root"] != str(root):
            raise ScreeningSchemaError("local observation is not bound to the exact project .venv")
        if Path(value["interpreter_realpath"]) != expected_interpreter.resolve():
            raise ScreeningSchemaError("local observation interpreter identity has drifted")
        current = fresh_observation or observe_local_packages(root)
        if _observation_comparable(value) != _observation_comparable(current):
            raise ScreeningSchemaError("published local package observation has drifted")


def render_markdown_report(record: dict[str, Any]) -> str:
    """Render deterministic human-readable output from canonical JSON only."""

    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    rows = "\n".join(
        "| "
        f"`{cell(item['family'])}` | `{cell(item['canonical_variant_id'])}` | "
        f"`{cell(item['result'])}` | "
        f"<{cell(item['official_source_url']['value'])}>; "
        f"version `{cell(item['source_version_or_date']['value'])}`; "
        f"retrieved `{cell(item['retrieved_at_utc']['value'])}` | "
        f"{cell(', '.join(item['unknowns']) or 'None')} | "
        f"{cell('<br>'.join(str(note) for note in item['notes']) or 'None')} |"
        for item in record["variant_records"]
    )
    counts = "\n".join(
        f"- `{result}`: {count}" for result, count in sorted(record["derived_counts"].items())
    )
    eligible = "\n".join(f"- `{identifier}`" for identifier in record["eligible_variant_ids"]) or "- None"
    errors = "\n".join(f"- {error}" for error in record["errors"]) or "- None"
    return (
        "# Phase 1 Model Screening\n\n"
        f"- Run ID: `{record['run_id']}`\n"
        f"- Overall classification: `{record['overall_classification']}`\n"
        f"- Target GPU: `{record['target_gpu']['memory_gb']} GB {record['target_gpu']['device']}`\n"
        f"- P1-02 evidence SHA-256: `{record['p1_02_evidence_sha256']}`\n\n"
        "## Variant results\n\n"
        "| Family | Variant | Result | Official source anchor | Exact unknown facts | Notes / exclusion reason |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"{rows}\n\n## Result counts\n\n{counts}\n\n"
        f"## Eligible variants\n\n{eligible}\n\n## Errors\n\n{errors}\n\n"
        "Machine-readable evidence: `docs/findings/phase1/evidence/model_screening.json`\n"
    )


ReplaceFile = Callable[[Path, Path], None]


def _replace_file(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _stage(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def publish_screening_artifacts(
    repo_root: Path,
    record: dict[str, Any],
    *,
    replace_file: ReplaceFile = _replace_file,
) -> None:
    """Publish Markdown first and canonical JSON last; never write the roadmap."""

    root = repo_root.resolve()
    validate_screening_record(
        record,
        repo_root=root,
    )
    if record["overall_classification"] != "pass":
        raise PublicationError("only overall-pass screening evidence may be published")
    markdown_bytes = render_markdown_report(record).encode("utf-8")
    json_bytes = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if json.loads(json_bytes) != record:
        raise PublicationError("canonical JSON does not round-trip")
    staged: list[tuple[Path, Path]] = []
    try:
        for destination, content in (
            (root / FINDING_RELATIVE_PATH, markdown_bytes),
            (root / EVIDENCE_RELATIVE_PATH, json_bytes),
        ):
            staged.append((_stage(destination, content), destination))
        for temporary, destination in staged:
            replace_file(temporary, destination)
    except OSError as exc:
        raise PublicationError(f"screening publication failed: {exc}") from exc
    finally:
        for temporary, _ in staged:
            if temporary.exists():
                temporary.unlink()


def _load_record(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScreeningSchemaError(f"canonical screening ledger is unavailable: {exc}") from exc
    if not isinstance(value, dict):
        raise ScreeningSchemaError("canonical screening ledger must be an object")
    return value


def _refresh_derived(record: dict[str, Any]) -> None:
    for variant in record["variant_records"]:
        support = derive_monthly_history_only_60x3(variant)
        summary = variant["monthly_history_only_60x3_support"]
        summary["status"] = "known" if support is not None else "unknown"
        summary["value"] = support if support is not None else "unknown"
        variant["result"] = classify_variant_record(variant)
    counts, eligible = derive_eligible_projection(record["variant_records"])
    record["derived_counts"] = counts
    record["eligible_variant_ids"] = eligible
    if any(variant["result"] == "blocked" for variant in record["variant_records"]):
        record["overall_classification"] = "blocked"


def _refresh_local_source_registry(
    record: dict[str, Any], observation: Mapping[str, Any]
) -> None:
    observed_by_locator = {
        item["stable_locator"]: item for item in observation["adapter_sources"]
    }
    for source in record["source_registry"].values():
        if source.get("source_kind") != "observed_local_package_source":
            continue
        observed = observed_by_locator.get(source.get("stable_locator"))
        if observed is None:
            raise ScreeningSchemaError("local source registry contains an unmanifested adapter")
        source["sha256"] = observed["adapter_module_sha256"]
        source["source_version_or_date"] = f"timecopilot=={observed['distribution_version']}"
        source["retrieved_at_utc"] = observed["observed_at_utc"]
        source["url_or_path"] = str(
            Path(observed["adapter_module_path"]).relative_to(record["local_package_observations"]["project_root"])
        )

def publish(repo_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Refresh local/binding/derived fields of an externally curated ledger and publish it."""

    root = repo_root.resolve()
    record = _load_record(root / EVIDENCE_RELATIVE_PATH)
    validate_p1_02_binding(root, record)
    validate_screening_record(record)
    publication_time = now or _utc_now()
    record["local_package_observations"] = observe_local_packages(
        root, observed_at=publication_time
    )
    _refresh_local_source_registry(record, record["local_package_observations"])
    record["generated_at_utc"] = _timestamp(publication_time)
    _refresh_derived(record)
    publish_screening_artifacts(root, record)
    validate_published_state(root)
    return record


def validate_published_state(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    record = _load_record(root / EVIDENCE_RELATIVE_PATH)
    validate_screening_record(
        record,
        repo_root=root,
    )
    validate_p1_02_binding(root, record)
    finding = root / FINDING_RELATIVE_PATH
    if not finding.is_file() or finding.read_text(encoding="utf-8") != render_markdown_report(record):
        raise ScreeningSchemaError("screening Markdown does not match canonical JSON")
    return record


def validate(repo_root: Path) -> dict[str, Any]:
    return validate_published_state(repo_root)


def validate_roadmap_consistency(
    repo_root: Path,
    *,
    expect: str,
    require_update_eligible: bool = False,
) -> None:
    """Read-only roadmap guard; it never reconciles or edits the roadmap."""

    if expect not in {"planned", "complete"}:
        raise RoadmapConsistencyError("expect must be planned or complete")
    root = repo_root.resolve()
    record = validate_published_state(root)
    if record["overall_classification"] != "pass":
        raise RoadmapConsistencyError("roadmap checks require canonical overall-pass evidence")
    roadmap_path = root / ROADMAP_RELATIVE_PATH
    roadmap = roadmap_path.read_text(encoding="utf-8")
    matches = P1_03_ROADMAP_PATTERN.findall(roadmap)
    expected_marker = " " if expect == "planned" else "x"
    if matches != [expected_marker]:
        raise RoadmapConsistencyError(f"P1-03 roadmap state is not {expect}")
    lines = P1_03_ROADMAP_LINE_PATTERN.findall(roadmap)
    if len(lines) != 1:
        raise RoadmapConsistencyError("roadmap must contain exactly one P1-03 entry")
    planned_line = re.sub(r"^- \[[ x-]\]", "- [ ]", lines[0])
    if planned_line != P1_03_ROADMAP_PLANNED_LINE:
        raise RoadmapConsistencyError("P1-03 roadmap entry contains an unauthorized edit")
    if require_update_eligible and expect != "planned":
        raise RoadmapConsistencyError("update eligibility is meaningful only for planned state")


def check_roadmap(repo_root: Path, *, expect: str, require_update_eligible: bool = False) -> None:
    validate_roadmap_consistency(
        repo_root, expect=expect, require_update_eligible=require_update_eligible
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("publish", "validate"):
        item = subparsers.add_parser(command)
        item.add_argument("--repo-root", type=Path, required=True)
    roadmap = subparsers.add_parser("check-roadmap")
    roadmap.add_argument("--repo-root", type=Path, required=True)
    roadmap.add_argument("--expect", choices=("planned", "complete"), required=True)
    roadmap.add_argument("--require-update-eligible", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.repo_root.is_absolute():
        print("--repo-root must be an absolute path", file=sys.stderr)
        return 1
    try:
        if arguments.command == "publish":
            result = publish(arguments.repo_root)
            print(json.dumps(result, sort_keys=True))
        elif arguments.command == "validate":
            result = validate(arguments.repo_root)
            print(json.dumps(result, sort_keys=True))
        else:
            check_roadmap(
                arguments.repo_root,
                expect=arguments.expect,
                require_update_eligible=arguments.require_update_eligible,
            )
    except (ScreeningError, target_pipeline.TargetPipelineError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
