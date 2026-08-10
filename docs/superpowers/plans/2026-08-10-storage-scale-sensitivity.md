# Storage-Scale Sensitivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Run three independent 28-day experiments with `max_delay_h=3`, compare their storage and task-shifting costs, and publish independent artifacts plus a cross-experiment summary.

**Architecture:** A new experiment wrapper invokes `run_houston_2020_experiment` once for each storage specification. Each invocation creates its complete four-case project below a distinct child directory. The wrapper extracts four total costs, derives the storage-only benefit, shift benefit with and without storage, and their difference; it publishes a parent CSV, two PNGs, metadata, and a Markdown analysis report.

**Tech Stack:** Python 3.13, pandas, NumPy, Pillow, PySCIPOpt, unittest.

---

### Task 1: Add failing tests for the storage-scale contract

**Files:**
- Create: `tests/unit/test_storage_scale_sensitivity.py`
- Create: `tests/integration/test_storage_scale_sensitivity.py`

- [ ] Define a unit test for one scale with four case costs: `100, 92, 90, 84`. Assert that no-storage shift saving is `8`, storage-enabled shift saving is `6`, and storage effect on shift is `-2` CNY.
- [ ] Run `conda run -n scip_env python -m unittest tests.unit.test_storage_scale_sensitivity -v` and confirm the module-import failure.
- [ ] Define an integration test that patches the existing main runner and verifies these published paths:
  - `experiments/energy_2p0_mwh_power_0p5_mw/results/case_metrics.csv`
  - `experiments/energy_4p0_mwh_power_1p0_mw/results/case_metrics.csv`
  - `experiments/energy_6p0_mwh_power_1p5_mw/results/case_metrics.csv`
  - `results/storage_scale_sensitivity.csv`
  - `figures/storage_scale_total_cost.png`
  - `figures/storage_scale_shift_value.png`
  - `analysis.md`

### Task 2: Implement independent experiment projects and the summary

**Files:**
- Create: `dc_energy_opt/experiments/storage_scale_sensitivity.py`
- Modify: `dc_energy_opt/experiments/__init__.py`

- [ ] Define immutable storage specifications:
  - `energy_2p0_mwh_power_0p5_mw`: 2.0 MWh, 0.5 MW
  - `energy_4p0_mwh_power_1p0_mw`: 4.0 MWh, 1.0 MW
  - `energy_6p0_mwh_power_1p5_mw`: 6.0 MWh, 1.5 MW
- [ ] Implement a summary with the four existing cases and these metrics:
  - `no_storage_shift_savings_cny = renewables_only_cost - renewables_shift_cost`
  - `storage_shift_savings_cny = renewables_storage_cost - joint_cost`
  - `storage_effect_on_shift_cny = storage_shift_savings_cny - no_storage_shift_savings_cny`
  - `storage_base_savings_cny = renewables_only_cost - renewables_storage_cost`
- [ ] Require `params.max_delay_h == 3`, finite total costs, and statuses `optimal` or `gaplimit`.
- [ ] Run each scale with `replace`d energy, charge-power, and discharge-power parameters, writing each complete project below `experiments/<scale name>/`.
- [ ] Write the parent CSV, Chinese `analysis.md`, and `run_metadata.json`; export the result dataclass and runner.
- [ ] Run the two new tests and confirm they pass.

### Task 3: Add parent figures and the command-line entry point

**Files:**
- Modify: `dc_energy_opt/reporting/plots.py`
- Modify: `dc_energy_opt/reporting/__init__.py`
- Create: `run_storage_scale_sensitivity.py`
- Modify: `tests/unit/test_plots.py`
- Modify: `tests/integration/test_cli_entrypoints.py`

- [ ] Add a failing plot test expecting deterministic 1800×900 RGB `storage_scale_total_cost.png` and `storage_scale_shift_value.png`.
- [ ] Add `make_storage_scale_sensitivity_plots`: the first image compares `renewables_storage_cost_cny` and `joint_cost_cny`; the second compares no-storage and storage-enabled shift savings.
- [ ] Add a command exposing `--workload-data`, `--energy-data`, `--output-dir`, and `--show-solver-log`; its concise output reports each scale's storage saving, storage-enabled shift saving, and storage effect on shift.
- [ ] Run the new plot and CLI tests and confirm they pass.

### Task 4: Document, execute, inspect, and commit

**Files:**
- Modify: `README.md`
- Modify: `docs/houston_2020_experiment.md`

- [ ] Document the fixed 3-hour condition, three paired scales, command, metrics, and nested output layout. Distinguish this experiment from flex-ratio sensitivity.
- [ ] Run `conda run -n scip_env python -m unittest discover -s tests -t . -v`.
- [ ] Run `conda run -n scip_env python run_storage_scale_sensitivity.py`; verify all projects, CSV, Markdown report, and figures, then visually inspect the parent PNGs.
- [ ] Commit only the listed source, test, documentation, and plan files with message `新增固定延迟储能规模敏感性分析`.
