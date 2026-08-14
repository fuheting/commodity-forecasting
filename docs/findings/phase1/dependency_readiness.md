# Phase 1 Dependency Readiness

- Run ID: `P1-01-20260814T050221Z`
- Classification: `pass`
- Reader: `openpyxl 3.1.5` (`openpyxl>=3.1,<4`)
- Installed project: `0.1.0`
- Acceptance command: `PYTHONPATH=/home/hfu_nestle/projects/commodity-forecasting/src /home/hfu_nestle/projects/commodity-forecasting/.venv/bin/python -m commodity_forecasting.phase1.readiness verify-clean-install --repo-root /home/hfu_nestle/projects/commodity-forecasting`
- Controller / child mode: `verify-clean-install` / `probe-installed`
- Host / child PYTHONPATH: `explicit_repo_src` / `absent`
- Workbook: `/home/hfu_nestle/projects/commodity-forecasting/data/raw/world_bank/pink_sheet/CMO-Historical-Data-Monthly.xlsx`
- Raw SHA-256 before: `7902a77505ebdc5d202ce65f666c2ee1b04b626f042d7738ed3e6f7d112c8433`
- Raw SHA-256 after: `7902a77505ebdc5d202ce65f666c2ee1b04b626f042d7738ed3e6f7d112c8433`
- Worksheet / target: `Monthly Prices` / `Coffee, Arabica`
- Monthly extent: `1960M01` through `2026M07` (`799` rows)

## Stage outcomes

- `create_environment`: `pass` (exit `0`)
- `install_project`: `pass` (exit `0`)
- `pip_check`: `pass` (exit `0`)
- `probe_installed`: `pass` (exit `0`)
- `cleanup`: `pass` (exit `0`)
- Failed stage: `None`
- Cleanup: `pass`

## Checks

- `child_outside_repo`: `True`
- `child_pythonpath_absent`: `True`
- `cleanup_completed`: `True`
- `dependency_declared`: `True`
- `host_bootstrap_explicit`: `True`
- `install_non_editable`: `True`
- `periods_parse`: `True`
- `phase0_complete`: `True`
- `pip_check`: `True`
- `publication_policy_present`: `True`
- `raw_hash_after_matches`: `True`
- `raw_hash_before_matches`: `True`
- `reader_version_supported`: `True`
- `repo_root_explicit`: `True`
- `sheet_found`: `True`
- `target_found_once`: `True`
- `workbook_exists`: `True`

## Publication-availability policy

- Evaluation label: `revised_workbook_pseudo_real_time`
- Availability proxy: `strict_prior_month`
- Limitation: Historical release timestamps and vintages are not available in the preserved workbook. Strict prior-month eligibility is a conservative simulation assumption, not a verified historical publication date; the latest workbook can contain revisions.
- Prohibited claim: Do not describe this evaluation as vintage-real-time.

## Errors

- None

Machine-readable evidence: `docs/findings/phase1/evidence/dependency_readiness.json`
