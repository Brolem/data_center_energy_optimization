# ERCOT 2025 Houston × Alibaba 2026 Spot GPU Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, paper-only, rolling day-ahead replay that schedules Alibaba HP/Spot GPU workloads against ERCOT Houston DAM prices, with cost as the primary objective and cost-guarded system-renewable matching plus consumer-carbon evaluation.

**Architecture:** The new study is isolated under `experiments/paper/ercot_2025_spot_gpu/`; it must not import, copy, read, or modify `experiments/career/` or `tests/career/`. A paper-only preparation layer converts shared annual energy data plus raw local forecast archives into 1,062-hour seasonal inputs. A separate workload layer constructs strict-priority HP reservations and eligible Spot jobs, then a rolling, model-specific MILP derives a gang-feasible Spot schedule. Evaluation consumes realized ERCOT system signals only after decisions have been committed.

**Tech Stack:** Python 3.13, pandas 3.0.5, NumPy 2.5.1, PySCIPOpt 6.2.1, standard-library `unittest`, CSV/JSON provenance artifacts, and Markdown.

---

## Scope locks

- All new implementation lives in the paper namespace; the established Houston 2020 model remains unchanged.
- Raw ERCOT, EIA and Alibaba downloads stay local and ignored. Scripts, source manifests, schema files and the four compact paper inputs are version controlled; bulky run results and figures remain ignored reproducible artifacts.
- `timestamp_utc` in the existing annual CSV remains a source-compatible **interval end**. New paper inputs add `interval_start_utc` and `interval_end_utc`; no code may shift market values by six hours.
- The 30-day core is 720 hours. Main eligibility is `D_max=168 h`, completion slack is `H=3 h`, and the context/core/tail input length is `171 + 720 + 171 = 1,062 h`.
- A 72-hour eligibility fallback is allowed only when the preregistered feasibility trial fails its runtime gate before any cost, renewable or carbon comparison is inspected.

## File structure

| Path | Responsibility |
| --- | --- |
| `experiments/paper/ercot_2025_spot_gpu/config.py` | Immutable study paths, timing constants, power scenarios and solver limits. |
| `experiments/paper/ercot_2025_spot_gpu/types.py` | Typed rows for energy intervals, jobs, reservations, forecast intervals and schedules. |
| `experiments/paper/ercot_2025_spot_gpu/energy.py` | Interval semantics, 1,062-hour seasonal input validation and forecast join. |
| `experiments/paper/ercot_2025_spot_gpu/workload.py` | Alibaba job normalization, deterministic core selection, HP reservation and Spot eligibility. |
| `experiments/paper/ercot_2025_spot_gpu/power.py` | GPU TDP mapping and incremental facility-power calculation. |
| `experiments/paper/ercot_2025_spot_gpu/hp_forecast.py` | Rolling HP capacity forecast and quantile risk reserve. |
| `experiments/paper/ercot_2025_spot_gpu/envelope.py` | Cohort construction, gang-feasible capacity constraints and schedule recovery. |
| `experiments/paper/ercot_2025_spot_gpu/scheduler.py` | Daily commitment loop and B0/B1/B2/P policy implementations. |
| `experiments/paper/ercot_2025_spot_gpu/evaluation.py` | Cost, realized renewable-match, carbon and service metrics. |
| `experiments/paper/ercot_2025_spot_gpu/run.py` | Staged run directory, provenance and season/policy orchestration. |
| `scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py` | Creates validated paper-only inputs from annual data and local raw forecast archives. |
| `tests/paper/ercot_2025_spot_gpu/` | Unit, integration and no-leakage tests for this study only. |
| `docs/paper/experiments/ercot_2025_houston_spot_gpu_experiment.md` | Updated experimental data contract; it replaces the obsolete 723-hour description. |
| `docs/development/paper/ercot_2025_houston_spot_gpu_energy_inputs.md` | Dated preparation status and hashes; it records the transition without altering shared-data documentation. |

## Task 1: Establish paper-only configuration and command routing

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/__init__.py`
- Create: `experiments/paper/ercot_2025_spot_gpu/config.py`
- Create: `tests/paper/ercot_2025_spot_gpu/__init__.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_config.py`
- Modify: `experiments/paper/cli.py`
- Modify: `tests/paper/test_cli.py`
- Modify: `tests/paper/test_module_boundaries.py`

- [ ] **Step 1: Write the failing configuration and routing tests.**

```python
import unittest
from pathlib import Path

from experiments.paper.ercot_2025_spot_gpu.config import ERCOT_2025_SPOT_GPU
from experiments.paper.cli import parse_command


class SpotGpuConfigTests(unittest.TestCase):
    def test_formal_study_uses_paper_scoped_paths(self) -> None:
        self.assertEqual(
            ERCOT_2025_SPOT_GPU.output_dir,
            Path("outputs/paper/ercot_2025_houston_spot_gpu/day_ahead"),
        )
        self.assertEqual(ERCOT_2025_SPOT_GPU.core_hours, 720)
        self.assertEqual(ERCOT_2025_SPOT_GPU.context_hours, 171)
        self.assertEqual(ERCOT_2025_SPOT_GPU.tail_hours, 171)

    def test_cli_parses_spot_gpu_replay_command(self) -> None:
        command = parse_command(["spot-gpu", "replay"])
        self.assertEqual(command.name, "spot-gpu")
        self.assertEqual(command.study, "replay")
```

- [ ] **Step 2: Run the focused test and confirm it fails because the module and command do not exist.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_config -v`
Expected: import or command-routing failure.

- [ ] **Step 3: Add immutable paper-study configuration and a CLI namespace.**

```python
@dataclass(frozen=True)
class SpotGpuStudyConfig:
    annual_energy_data: Path = Path("data/energy/ercot_2025_houston_hourly.csv")
    output_dir: Path = Path("outputs/paper/ercot_2025_houston_spot_gpu/day_ahead")
    core_hours: int = 720
    completion_slack_h: int = 3
    max_spot_duration_h: int = 168
    context_hours: int = 171
    tail_hours: int = 171
    cost_guardrail_fraction: float = 0.01
    hp_risk_quantile: float = 0.95
    hp_calibration_hours: int = 336


ERCOT_2025_SPOT_GPU = SpotGpuStudyConfig()
```

Add `spot-gpu replay`, `spot-gpu pilot`, and `spot-gpu report` parsers. Their defaults must come from `ERCOT_2025_SPOT_GPU`; the existing `day-ahead`, `sensitivity`, and `plot` commands must retain their current defaults and behavior.

- [ ] **Step 4: Re-run focused configuration and existing CLI tests.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_config tests.paper.test_cli tests.paper.test_module_boundaries -v`
Expected: all selected tests pass.

- [ ] **Step 5: Commit only the paper namespace and its tests.**

```powershell
git add experiments/paper/ercot_2025_spot_gpu experiments/paper/cli.py tests/paper/ercot_2025_spot_gpu tests/paper/test_cli.py tests/paper/test_module_boundaries.py
git commit -m "feat: scaffold paper spot gpu study"
```

## Task 2: Define raw-data provenance and produce the 1,062-hour energy contract

**Files:**

- Create: `scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py`
- Create: `experiments/paper/ercot_2025_spot_gpu/energy.py`
- Create: `experiments/paper/ercot_2025_spot_gpu/types.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_energy.py`
- Modify: `.gitignore`
- Modify: `data/energy/README.md`
- Modify: `docs/paper/experiments/ercot_2025_houston_spot_gpu_experiment.md`
- Modify: `docs/development/paper/ercot_2025_houston_spot_gpu_energy_inputs.md`

- [ ] **Step 1: Add failing tests for interval semantics, winter context and forecast availability.**

```python
import unittest

class EnergyInputTests(unittest.TestCase):
    def test_interval_end_creates_previous_hour_start(self) -> None:
        row = {"timestamp_utc": "2025-01-01T07:00:00Z"}
        interval = to_energy_interval(row)
        self.assertEqual(interval.interval_start_utc, "2025-01-01T06:00:00Z")
        self.assertEqual(interval.interval_end_utc, "2025-01-01T07:00:00Z")

    def test_window_has_context_core_and_settlement_tail(self) -> None:
        rows = build_study_window_rows(
            annual_2025=synthetic_annual_rows(),
            december_2024=synthetic_december_rows(),
            window_start=date(2025, 1, 1),
            context_hours=171,
            core_hours=720,
            tail_hours=171,
        )
        self.assertEqual(len(rows), 1062)
        self.assertEqual([row["period_role"] for row in rows].count("context"), 171)
        self.assertEqual([row["period_role"] for row in rows].count("core"), 720)
        self.assertEqual([row["period_role"] for row in rows].count("settlement_tail"), 171)

    def test_rejects_forecast_published_after_decision_cutoff(self) -> None:
        with self.assertRaisesRegex(ValueError, "published after cutoff"):
            join_latest_forecasts(intervals, late_forecast_rows, cutoff_utc)
```

Import `unittest`; the repository test suite is standard-library `unittest`.

- [ ] **Step 2: Run the new test module and confirm failure.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_energy -v`
Expected: missing module/function failures.

- [ ] **Step 3: Implement a paper-only input schema.**

```python
ENERGY_INPUT_COLUMNS = (
    "window_id", "window_hour", "period_role",
    "interval_start_utc", "interval_end_utc", "local_date",
    "dam_lz_houston_usd_per_mwh",
    "erco_solar_generation_mwh", "erco_wind_generation_mwh",
    "erco_consumed_co2_intensity_lbs_per_kwh",
    "forecast_issue_utc", "forecast_target_end_utc",
    "forecast_system_wind_hsl_mw", "forecast_system_solar_hsl_mw",
    "forecast_consumed_co2_lbs_per_kwh",
)
```

`to_energy_interval` must parse the existing `timestamp_utc` only as an interval end, derive the one-hour preceding start, and preserve all source values unchanged. `build_study_window_rows` must require consecutive UTC intervals, non-null core/tail evaluation signals, exactly 171/720/171 roles, and no post-cutoff forecast record. It must obtain the 2024-12-24 through 2024-12-31 winter context from a separately downloaded local raw source, record its SHA-256, and never include that raw source in Git. The source manifest must identify ERCOT DAM archive `np4-180-er`, ERCOT wind forecast product `NP4-732-CD` (`https://www.ercot.com/mp/data-products/data-product-details?id=NP4-732-CD`), and ERCOT solar forecast product `NP4-737-CD` (`https://www.ercot.com/mp/data-products/data-product-details?id=NP4-737-CD`).

Add ignored raw paths for the 2024 DAM archive and the local ERCOT wind/solar forecast archive. Replace the broad `outputs/` ignore with these scoped rules, which keep all result directories ignored while allowing only compact paper inputs and their manifests into Git:

```gitignore
outputs/*
!outputs/paper/
!outputs/paper/ercot_2025_houston_spot_gpu/
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/*.csv
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/*.json
```

In `data/energy/README.md`, list their official source URL, retrieval date, SHA-256, report identifier, issue-time timezone and the fact that forecasts target HSL rather than realized EIA generation. The paper experiment document must replace every 723-hour statement with the formal 1,062-hour contract.

- [ ] **Step 4: Produce all four compact paper inputs and a manifest.**

The preparation command must write only these versioned derived artifacts:

```text
outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/
  2025-01-01_30d_d168_h3_energy.csv
  2025-04-01_30d_d168_h3_energy.csv
  2025-07-01_30d_d168_h3_energy.csv
  2025-10-01_30d_d168_h3_energy.csv
  inputs_manifest.json
```

`inputs_manifest.json` must contain schema version, all timing constants, source hashes, output hashes, forecast cutoffs, source report identifiers, the past-only carbon-forecast rule and missing-value counts. It must not contain an access token, local absolute path or raw data payload.

- [ ] **Step 5: Run data validation and existing shared-energy regression tests.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_energy tests.shared.test_ercot_2025_energy -v`
Expected: all selected tests pass; the legacy 723-hour generator output remains unchanged until a separately reviewed paper-data migration retires it.

- [ ] **Step 6: Commit the data contract, parser and documentation.**

```powershell
git add .gitignore data/energy/README.md scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py experiments/paper/ercot_2025_spot_gpu/energy.py experiments/paper/ercot_2025_spot_gpu/types.py tests/paper/ercot_2025_spot_gpu/test_energy.py docs/paper/experiments/ercot_2025_houston_spot_gpu_experiment.md docs/development/paper/ercot_2025_houston_spot_gpu_energy_inputs.md outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs
git commit -m "feat: prepare paper spot gpu energy inputs"
```

## Task 3: Normalize Alibaba work, freeze the replay core and construct HP reservations

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/workload.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_workload.py`
- Modify: `experiments/paper/ercot_2025_spot_gpu/types.py`
- Create: `docs/paper/data/alibaba_2026_spot_gpu_replay_contract.md`

- [ ] **Step 1: Write failing tests for deterministic selection and honest eligibility.**

```python
class WorkloadReplayTests(unittest.TestCase):
    def test_selects_median_workload_30_day_core_without_using_energy_values(self) -> None:
        selection = select_replay_core(normalized_jobs, core_hours=720, max_duration_h=168)
        self.assertEqual(selection.core_start_seconds, 3_369_600)
        self.assertEqual(selection.core_end_seconds, 5_961_600)
        self.assertEqual(selection.selection_rule, "closest_to_median_eligible_spot_gpu_hours")

    def test_deadline_includes_duration_and_completion_slack(self) -> None:
        job = make_spot_job(submit_hour=10, duration_seconds=7_201, gpu_count=8)
        self.assertEqual(job.required_run_hours, 3)
        self.assertEqual(job.deadline_hour, 16)

    def test_hp_reservation_counts_requested_gpus_by_model(self) -> None:
        reservation = realized_hp_reservation([hp_job], horizon_hours=4)
        self.assertEqual(reservation.loc[1, "A100-SXM4-80GB"], hp_job.gpu_count)
```

- [ ] **Step 2: Run the workload tests and confirm failure.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_workload -v`
Expected: missing workload functions and types.

- [ ] **Step 3: Implement normalized immutable job records.**

```python
@dataclass(frozen=True)
class GpuJob:
    job_id: str
    priority: str
    gpu_model: str
    gpu_count: int
    submit_hour: int
    required_run_hours: int
    deadline_hour: int | None


def normalize_jobs(frame: pd.DataFrame, *, completion_slack_h: int) -> list[GpuJob]:
    """Convert relative-second trace fields without inventing wall-clock dates."""
```

Set `gpu_count = gpu_request * worker_num`, `submit_hour = floor(submit_time / 3600)`, and `required_run_hours = ceil(duration / 3600)`. Set a Spot deadline to `submit_hour + required_run_hours + completion_slack_h`; keep the HP deadline as `None`. Reject non-positive requests, unknown priorities, unknown GPU models and negative timings. Do not derive waiting time, observed start time, eviction count, utilization or power from the trace.

`select_replay_core` must evaluate every admissible 720-hour block, calculate eligible Spot GPU-hours using only `priority`, resource request and duration, select the block closest to the median, then break exact ties by earliest start. It must serialize the selected start/end, candidate count, median work and excluded-work percentage into `outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/workload_selection.json`.

- [ ] **Step 4: Add HP initial-state and carry-in handling.**

For each simulated hour, compute realized HP capacity from every job whose immediate-start proxy spans the hour. Carry-in HP is included even if it was submitted before the 30-day core. The initial inherited Spot state is reconstructed by a fixed EDF warm-up policy and written as an input artifact; all compared policies must receive exactly that same state.

- [ ] **Step 5: Run focused tests and create the compact workload input.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_workload -v`
Expected: all selected tests pass. The committed compact input must state the source file hashes, selection rule, 7,050 eligible jobs, 122,773.2 eligible Spot GPU-hours and the ten excluded over-168-hour jobs; regenerating it must reproduce those values from the pinned source hashes.

- [ ] **Step 6: Commit the workload contract.**

```powershell
git add experiments/paper/ercot_2025_spot_gpu/workload.py experiments/paper/ercot_2025_spot_gpu/types.py tests/paper/ercot_2025_spot_gpu/test_workload.py docs/paper/data/alibaba_2026_spot_gpu_replay_contract.md outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs
git commit -m "feat: add reproducible spot gpu workload replay"
```

## Task 4: Implement the parameterized GPU-to-facility power model

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/power.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_power.py`
- Create: `docs/paper/data/gpu_power_assumptions.md`

- [ ] **Step 1: Write failing arithmetic and scenario tests.**

```python
class PowerModelTests(unittest.TestCase):
    def test_facility_power_applies_gpu_tdp_utilization_it_factor_and_pue(self) -> None:
        model = PowerModel(pue=1.20, it_overhead_factor=1.15, active_power_fraction=0.70)
        self.assertEqual(model.facility_mw({"A100-SXM4-80GB": 10}), 0.003864)

    def test_unknown_gpu_model_requires_an_explicit_scenario_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "MYSTERY-GPU"):
            PowerModel.baseline().facility_mw({"MYSTERY-GPU": 1})
```

- [ ] **Step 2: Run the power tests and confirm failure.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_power -v`
Expected: missing power module.

- [ ] **Step 3: Implement only the declared incremental-power calculation.**

```python
@dataclass(frozen=True)
class PowerModel:
    tdp_watts_by_gpu_model: Mapping[str, float]
    pue: float
    it_overhead_factor: float
    active_power_fraction: float

    def facility_mw(self, active_gpu_counts: Mapping[str, int]) -> float:
        it_mw = sum(
            active_gpu_counts[model] * self.tdp_watts_by_gpu_model[model]
            for model in active_gpu_counts
        ) / 1_000_000.0
        return self.pue * self.it_overhead_factor * self.active_power_fraction * it_mw
```

Set the baseline to `PUE=1.20`, `it_overhead_factor=1.15`, and `active_power_fraction=0.70`; publish low/base/high triplets `(1.10, 1.00, 0.50)`, `(1.20, 1.15, 0.70)`, `(1.40, 1.30, 0.90)`. The assumptions document must cite the public source and TDP for every named model and label anonymous `GPU-series-*` values as scenarios.

- [ ] **Step 4: Run the tests and commit.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_power -v`
Expected: all selected tests pass.

```powershell
git add experiments/paper/ercot_2025_spot_gpu/power.py tests/paper/ercot_2025_spot_gpu/test_power.py docs/paper/data/gpu_power_assumptions.md
git commit -m "feat: add gpu facility power scenarios"
```

## Task 5: Build the HP risk reserve without future-information leakage

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/hp_forecast.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_hp_forecast.py`
- Modify: `experiments/paper/ercot_2025_spot_gpu/types.py`

- [ ] **Step 1: Write failing no-leakage and quantile-bound tests.**

```python
class HpForecastTests(unittest.TestCase):
    def test_reserve_for_hour_t_uses_only_hp_observations_before_t(self) -> None:
        forecast = forecast_hp_reserve(history, prediction_start_hour=336, horizon_hours=24)
        self.assertEqual(forecast.training_end_hour, 335)

    def test_forecast_is_bounded_by_physical_gpu_capacity(self) -> None:
        forecast = forecast_hp_reserve(history, capacities={"A10": 4}, prediction_start_hour=336, horizon_hours=2)
        self.assertTrue((forecast.values["A10"] <= 4).all())
```

- [ ] **Step 2: Run the HP forecast tests and confirm failure.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_hp_forecast -v`
Expected: missing forecasting module.

- [ ] **Step 3: Implement a transparent rolling quantile reserve.**

At each daily decision boundary, calculate per-model realized HP capacity from hours strictly before the boundary. Forecast future HP capacity as the maximum of known ongoing HP occupancy and the empirical 0.95 quantile of the previous 336 hours for the same forecast offset. Clip the forecast to the trace-derived physical capacity. Persist the calibration window, quantile, forecast creation timestamp and every training interval. Do not train on future core or settlement-tail hours.

- [ ] **Step 4: Re-run tests and add a realized-versus-planned audit table.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_hp_forecast -v`
Expected: all selected tests pass. The audit table must contain `decision_hour`, `gpu_model`, `forecast_reserve_gpus`, `realized_hp_gpus`, and `reserve_shortfall_gpus`.

- [ ] **Step 5: Commit the isolated HP forecasting module.**

```powershell
git add experiments/paper/ercot_2025_spot_gpu/hp_forecast.py experiments/paper/ercot_2025_spot_gpu/types.py tests/paper/ercot_2025_spot_gpu/test_hp_forecast.py
git commit -m "feat: add risk aware hp reservation forecast"
```

## Task 6: Derive and recover a gang-feasible Spot flexibility envelope

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/envelope.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_envelope.py`
- Modify: `experiments/paper/ercot_2025_spot_gpu/types.py`

- [ ] **Step 1: Write failing tests for release/deadline, gang capacity and recovery.**

```python
class EnvelopeFailureTests(unittest.TestCase):
    def test_envelope_never_runs_before_release_or_after_deadline(self) -> None:
        schedule = solve_envelope([spot_job], residual_capacity, horizon_hours=8)
        self.assertEqual(schedule.execution_hours(spot_job.job_id), [2, 3])

    def test_recovered_schedule_respects_model_specific_gang_capacity(self) -> None:
        schedule = solve_envelope(two_eight_gpu_jobs, {"A100": [8, 8, 8]})
        self.assertLessEqual(schedule.active_gpus("A100", 0), 8)

    def test_infeasible_deadline_raises_a_named_error(self) -> None:
        with self.assertRaisesRegex(InfeasibleSpotScheduleError, "job_id=late"):
            solve_envelope([impossible_job], {"A10": [1]})
```

- [ ] **Step 2: Run the envelope test module and confirm failure.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_envelope -v`
Expected: missing envelope module.

- [ ] **Step 3: Implement exact cohorts and the recovery check.**

Group jobs only when `(gpu_model, gpu_count, release_hour, deadline_hour, required_run_hours)` are equal. For each cohort `c` and hour `t`, create an integer active-job variable `y[c, t]`. Enforce:

```python
model.addCons(quicksum(y[c, t] for t in cohort.feasible_hours) == cohort.count * cohort.required_run_hours)
model.addCons(
    quicksum(cohort.gpu_count * y[cohort, t] for cohort in cohorts_for_model[model_name])
    <= residual_capacity[model_name][t]
)
```

After solving, expand cohorts to stable job-ID order and run an EDF recovery check. The recovery check must verify each job gets exactly `required_run_hours`, runs only within `[release_hour, deadline_hour)`, and consumes its full gang request in every scheduled hour. Reject a continuous relaxation or a cohort plan that cannot be recovered.

- [ ] **Step 4: Re-run focused tests and record model size.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_envelope -v`
Expected: all selected tests pass. Return a solver audit with cohort count, binary/integer variable count, constraints, status, gap and elapsed seconds.

- [ ] **Step 5: Commit envelope code and tests.**

```powershell
git add experiments/paper/ercot_2025_spot_gpu/envelope.py experiments/paper/ercot_2025_spot_gpu/types.py tests/paper/ercot_2025_spot_gpu/test_envelope.py
git commit -m "feat: add gang feasible spot flexibility envelope"
```

## Task 7: Implement daily commitment policies and the preregistered feasibility gate

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/scheduler.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_scheduler.py`
- Create: `docs/paper/experiments/ercot_2025_spot_gpu_feasibility_gate.md`
- Modify: `experiments/paper/ercot_2025_spot_gpu/config.py`

- [ ] **Step 1: Write failing tests for the information set and priority policies.**

```python
class SchedulerTests(unittest.TestCase):
    def test_day_d_commitment_prices_contain_exactly_next_24_intervals(self) -> None:
        decision = schedule_one_day(state, energy_rows, decision_hour=48, policy="B2")
        self.assertEqual(decision.price_information_end_hour, 71)

    def test_carbon_forecast_uses_only_completed_intervals(self) -> None:
        decision = schedule_one_day(state, energy_rows, decision_hour=48, policy="P")
        self.assertEqual(decision.carbon_training_end_hour, 47)

    def test_realized_hp_preempts_spot_without_hp_capacity_invasion(self) -> None:
        replay = run_replay(synthetic_case, policy="P")
        self.assertTrue(replay.hourly["hp_capacity_invasion_gpus"].eq(0).all())

    def test_proposed_policy_respects_the_cost_guardrail_before_renewable_tie_break(self) -> None:
        result = schedule_one_day(state, energy_rows, policy="P")
        self.assertLessEqual(result.cost_usd, result.price_optimum_usd + result.cost_guardrail_usd)
```

- [ ] **Step 2: Run scheduler tests and confirm failure.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_scheduler -v`
Expected: missing scheduler implementation.

- [ ] **Step 3: Implement B0, B1, B2 and P with a strict 24-hour information boundary.**

`B0` uses static per-model quotas with EDF. `B1` uses the rolling risk reserve and EDF. `B2` minimizes known-next-day DAM cost subject to the risk reserve and envelope feasibility. `P` first solves the same price objective, then constrains cost by:

```python
guardrail_usd = max(0.01, 0.01 * abs(price_optimum_usd))
model.addCons(cost_usd <= price_optimum_usd + guardrail_usd)
```

It next maximizes forecast system-renewable exposure, then minimizes the carbon forecast built from completed EIA observations only. The carbon forecast is the per-hour-of-day median over the preceding 336 published intervals; it must reject a decision hour with fewer than 168 non-null historical carbon observations. Prices after the next 24 committed hours must have no cost coefficient; they only preserve feasibility. Commit 24 hours, update realized HP arrivals, preempt Spot if actual HP exceeds its forecast reserve, carry remaining Spot work forward, and stop new Spot arrivals after the 720-hour core.

- [ ] **Step 4: Run the preregistered feasibility gate before main comparisons.**

The gate uses the frozen replay core, the winter energy input, all four policies, and baseline power parameters. It passes only if every daily solve reaches accepted status within 300 seconds, the complete winter replay finishes within eight hours, the recovery checker finds zero deadline violations, and all HP invasions are zero. Save `pilot_feasibility.json` before calculating or comparing the cost, renewable or carbon summary tables.

If it fails, change only `max_spot_duration_h` from 168 to 72, regenerate the input-selection manifest, rerun Tasks 3–7, and write the pass/fail evidence in the feasibility document. The choice cannot depend on cost, renewable or carbon outcomes.

- [ ] **Step 5: Re-run scheduler tests and commit.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_scheduler -v`
Expected: all selected tests pass.

```powershell
git add experiments/paper/ercot_2025_spot_gpu/scheduler.py experiments/paper/ercot_2025_spot_gpu/config.py tests/paper/ercot_2025_spot_gpu/test_scheduler.py docs/paper/experiments/ercot_2025_spot_gpu_feasibility_gate.md
git commit -m "feat: add rolling spot gpu day ahead scheduler"
```

## Task 8: Evaluate realized outcomes and produce auditable reports

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/evaluation.py`
- Create: `experiments/paper/ercot_2025_spot_gpu/run.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_evaluation.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_run_integration.py`
- Modify: `experiments/paper/cli.py`

- [ ] **Step 1: Write failing metric and integration tests.**

```python
class EvaluationTests(unittest.TestCase):
    def test_realized_cost_uses_interval_energy_and_dam_price(self) -> None:
        metrics = evaluate_replay(hourly_schedule, realized_energy)
        self.assertEqual(metrics["spot_incremental_facility_cost_usd"], 12.5)

    def test_renewable_metric_is_named_matching_not_local_consumption(self) -> None:
        metrics = evaluate_replay(hourly_schedule, realized_energy)
        self.assertIn("renewable_matching_mwh_weighted", metrics)
        self.assertFalse(any("local_renewable" in key for key in metrics))

    def test_four_season_run_writes_all_policies_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            result = run_study(input_dir=fixture_inputs, output_dir=output_dir)
            self.assertEqual(set(result.case_metrics["policy"]), {"B0", "B1", "B2", "P"})
            self.assertTrue((output_dir / "run_metadata.json").is_file())
```

- [ ] **Step 2: Run evaluation tests and confirm failure.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_evaluation tests.paper.ercot_2025_spot_gpu.test_run_integration -v`
Expected: missing evaluation and study-run modules.

- [ ] **Step 3: Implement realized-only evaluation and staged artifacts.**

For each committed interval calculate `spot_incremental_facility_mwh`, `spot_incremental_facility_cost_usd`, `renewable_matching_mwh_weighted`, and `consumed_co2_kg`. Convert EIA lbs/kWh to kg/MWh with the exact factor `453.59237`. Keep planned forecast signals and realized evaluation signals in distinct columns. Write: `hourly_dispatch.csv`, `daily_metrics.csv`, `case_metrics.csv`, `hp_reserve_audit.csv`, `job_completion.csv`, `solver_audit.csv`, and `run_metadata.json`.

`run_metadata.json` must state the counterfactual geographic interpretation, all source/input hashes, selected trace core, policy definitions, information cutoffs, power parameters, solver status/gap, hardware/software versions and whether the 168- or 72-hour eligibility rule was selected. Reuse `dc_energy_opt.artifacts.staged_run_directory` and `build_run_provenance`; do not copy raw sources into tracked output directories.

- [ ] **Step 4: Execute test fixtures for all policies and seasons.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_evaluation tests.paper.ercot_2025_spot_gpu.test_run_integration tests.paper.test_cli -v`
Expected: all selected tests pass; fixtures must run in temporary directories and never require raw data files.

- [ ] **Step 5: Commit the evaluator and orchestrator.**

```powershell
git add experiments/paper/ercot_2025_spot_gpu/evaluation.py experiments/paper/ercot_2025_spot_gpu/run.py experiments/paper/cli.py tests/paper/ercot_2025_spot_gpu/test_evaluation.py tests/paper/ercot_2025_spot_gpu/test_run_integration.py
git commit -m "feat: evaluate paper spot gpu replays"
```

## Task 9: Add sensitivity runs, figures and claims audit

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/reporting.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_reporting.py`
- Create: `docs/paper/results/ercot_2025_houston_spot_gpu_results.md`
- Modify: `docs/paper/README.md`

- [ ] **Step 1: Write failing reporting tests.**

```python
class ClaimLanguageTests(unittest.TestCase):
    def test_result_table_has_one_row_per_season_policy_and_power_case(self) -> None:
        table = build_result_table(case_metrics)
        self.assertTrue(set(table.columns) >= {
            "season", "policy", "power_scenario",
            "spot_incremental_facility_cost_usd",
            "renewable_matching_mwh_weighted", "consumed_co2_kg",
        })

    def test_claim_audit_rejects_a_local_renewable_phrase(self) -> None:
        with self.assertRaisesRegex(ValueError, "local renewable"):
            validate_claim_language("local renewable consumption increased")
```

- [ ] **Step 2: Run reporting tests and confirm failure.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_reporting -v`
Expected: missing reporting module.

- [ ] **Step 3: Implement fixed sensitivity and claim checks.**

Run the main policy matrix for each season and the three predeclared power scenarios. Run `H in {0, 1, 3, 6}` after the main matrix. If official historical forecast snapshots are available, report forecast versus realized-signal diagnostic upper bounds; otherwise report the past-only statistical forecast and label it exactly as such. The report must separate core and settlement-tail contributions, list incomplete/excluded work, and forbid phrases that equate system signals with on-site generation or consumer carbon with marginal carbon.

- [ ] **Step 4: Run reporting tests and build results only after the feasibility gate passes.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_reporting -v`
Expected: all selected tests pass.

Run: `conda run -n scip_env python -m experiments.paper spot-gpu replay --input-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs --output-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead`
Expected: one atomic result directory with all required audit CSVs and a provenance JSON; do not publish a numerical conclusion until the full run is checked.

- [ ] **Step 5: Commit reporting code and paper-facing result template.**

```powershell
git add experiments/paper/ercot_2025_spot_gpu/reporting.py tests/paper/ercot_2025_spot_gpu/test_reporting.py docs/paper/results/ercot_2025_houston_spot_gpu_results.md docs/paper/README.md
git commit -m "feat: report spot gpu paper results"
```

## Task 10: Verify the full paper-study implementation before any manuscript claim

**Files:**

- Modify: `docs/paper/results/ercot_2025_houston_spot_gpu_results.md`
- Modify: `docs/paper/README.md`

- [ ] **Step 1: Run the complete paper and shared test suites.**

Run: `conda run -n scip_env python -m unittest discover -s tests/paper -t . -v`
Expected: all paper tests pass.

Run: `conda run -n scip_env python -m unittest discover -s tests/shared -t . -v`
Expected: all shared tests pass.

- [ ] **Step 2: Audit repository and artifact integrity.**

Run: `git diff --check`
Expected: no output and exit code 0.

Run: `git check-ignore -v data/energy/ercot_2024_historical_dam_load_zone_and_hub_prices.zip data/energy/ercot_2025_public_wind_solar_forecasts`
Expected: both raw paths are ignored by `.gitignore`.

Run: `conda run -n scip_env python -m experiments.paper spot-gpu report --output-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead`
Expected: the report refuses missing hashes, failed solver states, nonzero HP invasion, incomplete tail accounting, or forbidden claim language.

- [ ] **Step 3: Record final evidence and commit.**

The result document must list input hashes, Git commit, exact commands, solver status, feasibility-gate decision, data limitations and the pass/fail state of each audit. It must not add results copied from a failed or partial run.

```powershell
git add docs/paper/results/ercot_2025_houston_spot_gpu_results.md docs/paper/README.md
git commit -m "docs: record verified spot gpu paper results"
```

## Plan self-review

| Design requirement | Covered by |
| --- | --- |
| Paper-only separation and raw-data exclusion | Scope locks; Tasks 1–2 and 10 |
| Correct interval-end semantics and 1,062-hour horizon | Task 2 |
| Trace-derived HP/Spot replay and `H=3` semantics | Task 3 |
| Conditional GPU power mapping | Task 4 |
| Risk-aware HP reservation with no future leakage | Task 5 |
| Gang-feasible flexibility rather than a continuous relaxation claim | Task 6 |
| Operational 24-hour DAM information and B0/B1/B2/P ablation | Task 7 |
| Cost-first, system-renewable matching and consumer-carbon metrics | Task 8 |
| Seasonal and parameter sensitivity, bounded claims | Task 9 |
| Full test, provenance and claim audit before manuscript use | Task 10 |

The plan has no unspecific implementation steps: every code task names the owning file, test module, function boundary, success command and commit scope. The existing Houston 2020 track remains an independent regression target; `experiments/career/` and `tests/career/` are intentionally absent.
