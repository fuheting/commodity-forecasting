"""Canonical World Bank Pink Sheet Arabica source configuration for the PoC."""

from __future__ import annotations

from commodity_forecasting.data.target import MonthlyTargetContract
from commodity_forecasting.data.workbook import WorkbookTargetSource

ARABICA_TARGET = MonthlyTargetContract(
    unique_id="world_bank_pink_sheet_monthly_arabica",
    period_start="1960M01",
    period_end="2026M07",
    period_count=799,
)

ARABICA_SOURCE = WorkbookTargetSource(
    worksheet_name="Monthly Prices",
    target_column="Coffee, Arabica",
    expected_sha256="7902a77505ebdc5d202ce65f666c2ee1b04b626f042d7738ed3e6f7d112c8433",
    target=ARABICA_TARGET,
)
