# ERCOT 2025 Houston × Alibaba 2026 Spot GPU Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a reproducible paper-only GPU scheduling study: cost-first rolling day-ahead dispatch of Alibaba HP/Spot GPU jobs under ERCOT Houston DAM prices, with system-renewable matching and consumer-carbon as secondary outcomes.

**Architecture:** New code is confined to `experiments/paper/ercot_2025_spot_gpu/`; it must never import, read, copy or modify the career namespace. One data layer emits the four 1,062-hour inputs and one trace replay. One scheduler combines HP risk reserve, gang-feasible Spot work and GPU power. One evaluator creates the seasonal policy matrix and auditable paper artifacts.

**Tech Stack:** Python 3.13, pandas, NumPy, PySCIPOpt, standard-library `unittest`, CSV/JSON, Markdown.

---

## Non-negotiable study rules

- Existing `timestamp_utc` is an **interval end**. Paper inputs add `interval_start_utc` and `interval_end_utc`; values are never shifted by six hours.
- Four seasonal cases each have 171-hour context, 720-hour core and 171-hour settlement tail. `H=3` is extra completion slack; it is not the full tail length.
- Main Spot eligibility is `D_max=168 h`. A single preregistered pilot may switch all experiments to `72 h`, before comparing any cost, renewable or carbon result, only if the stated feasibility gate fails.
- The scheduler uses only next-day DAM prices, a cutoff-valid wind/solar forecast and a past-only carbon forecast. Actual wind, solar and carbon are evaluation data.
- Raw downloads remain ignored. Only scripts, source/hash manifests and compact paper inputs are committed. Run results remain under ignored `outputs/` directories.
- The study reports system-level renewable **matching**, not data-center local renewable consumption. It reports consumer carbon, not marginal carbon.

## Five-stage delivery map

| Stage | Output | Tests |
| --- | --- | --- |
| 1. Input contract | Four 1,062-hour, hash-logged seasonal energy inputs | `test_inputs.py` |
| 2. Compute contract | Frozen Alibaba replay core, HP capacity table and power scenarios | `test_compute_contract.py` |
| 3. Scheduler | B0/B1/B2/P rolling policies with gang-feasible recovery | `test_scheduler.py` |
| 4. Pilot and matrix | Feasibility verdict, four-season policy results and figures | `test_replay_integration.py` |
| 5. Reproducibility handoff | Verified result record and manuscript-ready tables | Existing paper/shared suites plus audit commands |

## Stage 1: Build the paper input contract

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/{__init__,config,types,energy}.py`
- Create: `scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py`
- Create: `tests/paper/ercot_2025_spot_gpu/{__init__,test_inputs}.py`
- Modify: `.gitignore`, `experiments/paper/cli.py`, `data/energy/README.md`
- Modify: `docs/paper/experiments/ercot_2025_houston_spot_gpu_experiment.md`, `docs/development/paper/ercot_2025_houston_spot_gpu_energy_inputs.md`

- [ ] **Step 1: Write one compact data-contract test module.**

```python
import unittest
from datetime import date

from experiments.paper.ercot_2025_spot_gpu.energy import (
    build_study_window_rows,
    to_energy_interval,
)


class PaperInputTests(unittest.TestCase):
    def test_end_timestamp_defines_the_preceding_one_hour_interval(self) -> None:
        interval = to_energy_interval({"timestamp_utc": "2025-01-01T07:00:00Z"})
        self.assertEqual(interval.interval_start_utc, "2025-01-01T06:00:00Z")
        self.assertEqual(interval.interval_end_utc, "2025-01-01T07:00:00Z")

    def test_winter_window_has_exact_context_core_and_tail_sizes(self) -> None:
        rows = build_study_window_rows(
            annual_2025=synthetic_annual_rows(),
            december_2024=synthetic_december_rows(),
            window_start=date(2025, 1, 1),
        )
        self.assertEqual(len(rows), 1062)
        self.assertEqual(sum(row["period_role"] == "context" for row in rows), 171)
        self.assertEqual(sum(row["period_role"] == "core" for row in rows), 720)
        self.assertEqual(sum(row["period_role"] == "settlement_tail" for row in rows), 171)

    def test_rejects_forecast_issued_after_its_daily_cutoff(self) -> None:
        with self.assertRaisesRegex(ValueError, "published after cutoff"):
            build_study_window_rows(late_forecast_rows=late_forecast_rows())
```

- [ ] **Step 2: Confirm the test fails, then implement the smallest paper-only data layer.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_inputs -v`
Expected before implementation: import failure.

Create immutable config with `core_hours=720`, `context_hours=171`, `tail_hours=171`, `max_spot_duration_h=168`, `completion_slack_h=3`, `cost_guardrail_fraction=0.01`, `hp_risk_quantile=0.95`, and `hp_calibration_hours=336`. Extend `experiments.paper.cli` with `spot-gpu replay`, `spot-gpu pilot`, and `spot-gpu report`, without changing existing Houston 2020 commands.

The input CSV schema is:

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

The preparation script creates the four files named `2025-01-01_30d_d168_h3_energy.csv`, `2025-04-01_30d_d168_h3_energy.csv`, `2025-07-01_30d_d168_h3_energy.csv`, `2025-10-01_30d_d168_h3_energy.csv`, and an `inputs_manifest.json`. The manifest records source/output SHA-256 values, cutoff rules, HSL report IDs, past-only carbon forecast rule and null counts, but no access token, raw data or absolute path.

The raw source manifest names ERCOT DAM `np4-180-er`, wind forecast `NP4-732-CD` ([product page](https://www.ercot.com/mp/data-products/data-product-details?id=NP4-732-CD)), and solar forecast `NP4-737-CD` ([product page](https://www.ercot.com/mp/data-products/data-product-details?id=NP4-737-CD)). It records that HSL forecast values must not be evaluated against EIA actual generation.

- [ ] **Step 3: Keep raw files ignored and only compact inputs versioned.**

Replace the broad output ignore with these rules; add ignored raw paths for the 2024 DAM archive and raw ERCOT forecast directory.

```gitignore
outputs/*
!outputs/paper/
!outputs/paper/ercot_2025_houston_spot_gpu/
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/*.csv
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/*.json
```

Update the two paper data documents from the obsolete 723-hour description to the 1,062-hour contract. Preserve the existing shared 2025 annual table and its legacy generator behavior.

- [ ] **Step 4: Run tests and commit this stage.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_inputs tests.shared.test_ercot_2025_energy tests.paper.test_cli -v`
Expected: all selected tests pass.

```powershell
git add .gitignore data/energy/README.md scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py experiments/paper/ercot_2025_spot_gpu tests/paper/ercot_2025_spot_gpu/test_inputs.py experiments/paper/cli.py docs/paper/experiments/ercot_2025_houston_spot_gpu_experiment.md docs/development/paper/ercot_2025_houston_spot_gpu_energy_inputs.md outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs
git commit -m "feat: prepare paper spot gpu inputs"
```

## Stage 2: Freeze the compute contract

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/{workload,power}.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_compute_contract.py`
- Create: `docs/paper/data/{alibaba_2026_spot_gpu_replay_contract,gpu_power_assumptions}.md`
- Modify: `experiments/paper/ercot_2025_spot_gpu/types.py`

- [ ] **Step 1: Write one workload-and-power test module.**

```python
import unittest

from experiments.paper.ercot_2025_spot_gpu.power import PowerModel
from experiments.paper.ercot_2025_spot_gpu.workload import (
    make_spot_job,
    realized_hp_reservation,
    select_replay_core,
)


class ComputeContractTests(unittest.TestCase):
    def test_frozen_core_uses_median_eligible_spot_gpu_hours(self) -> None:
        selection = select_replay_core(normalized_jobs, core_hours=720, max_duration_h=168)
        self.assertEqual(selection.core_start_seconds, 3_369_600)
        self.assertEqual(selection.core_end_seconds, 5_961_600)

    def test_deadline_adds_duration_and_h(self) -> None:
        job = make_spot_job(submit_hour=10, duration_seconds=7_201, gpu_count=8)
        self.assertEqual(job.required_run_hours, 3)
        self.assertEqual(job.deadline_hour, 16)

    def test_hp_and_power_accounting_are_model_specific(self) -> None:
        self.assertEqual(realized_hp_reservation([hp_job], 4).loc[1, "A100-SXM4-80GB"], hp_job.gpu_count)
        power = PowerModel.baseline().facility_mw({"A100-SXM4-80GB": 10})
        self.assertAlmostEqual(power, 0.003864)
```

- [ ] **Step 2: Confirm failure, then implement the trace and power contract.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_compute_contract -v`
Expected before implementation: import failure.

Normalize trace fields as `gpu_count = gpu_request * worker_num`, `submit_hour = floor(submit_time / 3600)`, and `required_run_hours = ceil(duration / 3600)`. HP has no invented deadline; Spot has `deadline_hour = submit_hour + required_run_hours + H`. Construct HP capacity from the immediate-start proxy, including carry-in HP. Reconstruct inherited Spot state with one fixed EDF warm-up shared by every policy.

Select the workload core by nearest median eligible Spot GPU-hours across all admissible 720-hour blocks, with earliest-start tie break. Serialize the selection rule, source hashes, `3,369,600` start seconds, `5,961,600` end seconds, 7,050 eligible jobs, 122,773.2 eligible GPU-hours and ten over-168-hour exclusions into `workload_selection.json`.

Implement only incremental facility power:

\[
\Delta P_t=PUE\,\kappa_{IT}\sum_m n_{m,t}u_mP_m^{TDP}.
\]

Use low/base/high triples `(1.10, 1.00, 0.50)`, `(1.20, 1.15, 0.70)`, `(1.40, 1.30, 0.90)` for `(PUE, IT-overhead, active-power fraction)`. Document public TDP sources for named GPUs and mark `GPU-series-*` mappings as scenarios, never measurements.

- [ ] **Step 3: Run tests and commit this stage.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_compute_contract -v`
Expected: all selected tests pass.

```powershell
git add experiments/paper/ercot_2025_spot_gpu/workload.py experiments/paper/ercot_2025_spot_gpu/power.py experiments/paper/ercot_2025_spot_gpu/types.py tests/paper/ercot_2025_spot_gpu/test_compute_contract.py docs/paper/data outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/workload_selection.json
git commit -m "feat: freeze spot gpu compute contract"
```

## Stage 3: Implement and verify the rolling scheduler

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/{hp_forecast,envelope,scheduler}.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_scheduler.py`
- Create: `docs/paper/experiments/ercot_2025_spot_gpu_feasibility_gate.md`

- [ ] **Step 1: Write one scheduler test module with the three decisive invariants.**

```python
import unittest

from experiments.paper.ercot_2025_spot_gpu.scheduler import run_replay, schedule_one_day


class SchedulerTests(unittest.TestCase):
    def test_day_d_sees_only_next_24_dam_prices_and_past_carbon(self) -> None:
        decision = schedule_one_day(state, energy_rows, decision_hour=48, policy="P")
        self.assertEqual(decision.price_information_end_hour, 71)
        self.assertEqual(decision.carbon_training_end_hour, 47)

    def test_every_recovered_job_respects_release_deadline_and_gang_capacity(self) -> None:
        replay = run_replay(synthetic_case, policy="B2")
        self.assertTrue(replay.job_completion["is_deadline_feasible"].all())
        self.assertTrue(replay.hourly["spot_capacity_excess_gpus"].eq(0).all())

    def test_realized_hp_has_priority_and_proposed_policy_obeys_guardrail(self) -> None:
        replay = run_replay(synthetic_case, policy="P")
        self.assertTrue(replay.hourly["hp_capacity_invasion_gpus"].eq(0).all())
        self.assertLessEqual(replay.cost_usd, replay.price_optimum_usd + replay.cost_guardrail_usd)
```

- [ ] **Step 2: Confirm failure, then implement all policies in one scheduler path.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_scheduler -v`
Expected before implementation: import failure.

At each daily boundary, forecast HP by model as the maximum of known ongoing occupancy and the 0.95 quantile from the preceding 336 realized HP hours, clipped at physical model capacity. Forecast carbon as the hour-of-day median of the preceding 336 published EIA carbon values; reject a decision with fewer than 168 non-null historical observations. Both audit trails end at the preceding hour.

Build integer cohorts only for equal `(gpu_model, gpu_count, release_hour, deadline_hour, required_run_hours)`. The envelope must schedule a whole gang for a whole hour and be expanded to individual job IDs by EDF recovery. If recovery cannot satisfy a job, raise a named infeasibility error rather than outputting a relaxed schedule.

Implement policies in the same replay loop: B0 static-quota EDF; B1 risk-reserve EDF; B2 risk-reserve plus next-day price; P B2 price optimum followed by `cost <= optimum + max(0.01, 0.01 * abs(optimum))`, forecast-renewable matching, then past-only carbon forecast. Future intervals preserve feasibility but have no price coefficient. Commit only 24 hours, apply realized HP preemption, carry unfinished Spot work, and block new Spot arrivals after core hour 720.

- [ ] **Step 3: Run scheduler tests and commit this stage.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_scheduler -v`
Expected: all selected tests pass.

```powershell
git add experiments/paper/ercot_2025_spot_gpu/hp_forecast.py experiments/paper/ercot_2025_spot_gpu/envelope.py experiments/paper/ercot_2025_spot_gpu/scheduler.py tests/paper/ercot_2025_spot_gpu/test_scheduler.py docs/paper/experiments/ercot_2025_spot_gpu_feasibility_gate.md
git commit -m "feat: add rolling spot gpu scheduler"
```

## Stage 4: Run the feasibility gate and seasonal evaluation matrix

**Files:**

- Create: `experiments/paper/ercot_2025_spot_gpu/{evaluation,reporting,run}.py`
- Create: `tests/paper/ercot_2025_spot_gpu/test_replay_integration.py`
- Create: `docs/paper/results/ercot_2025_houston_spot_gpu_results.md`
- Modify: `experiments/paper/cli.py`, `docs/paper/README.md`

- [ ] **Step 1: Write one fixture-based end-to-end test.**

```python
import tempfile
import unittest
from pathlib import Path

from experiments.paper.ercot_2025_spot_gpu.run import run_study


class ReplayIntegrationTests(unittest.TestCase):
    def test_fixture_run_writes_all_policies_metrics_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = run_study(input_dir=fixture_inputs, output_dir=Path(temporary_directory))
            self.assertEqual(set(result.case_metrics["policy"]), {"B0", "B1", "B2", "P"})
            self.assertIn("spot_incremental_facility_cost_usd", result.case_metrics)
            self.assertIn("renewable_matching_mwh_weighted", result.case_metrics)
            self.assertIn("consumed_co2_kg", result.case_metrics)
            self.assertTrue((Path(temporary_directory) / "run_metadata.json").is_file())
```

- [ ] **Step 2: Confirm failure, then implement evaluation and one orchestrator.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_replay_integration -v`
Expected before implementation: import failure.

Evaluation uses realized EIA signals only: incremental facility MWh, USD DAM cost, MWh-weighted system-renewable matching and consumer-carbon kg (`lbs/kWh × 453.59237`). It writes hourly dispatch, daily/case metrics, job completion, HP reserve audit, solver audit and `run_metadata.json`. Metadata includes input hashes, selected trace core, data location disclaimer, decision cutoffs, policy, power scenario, solver status/gap and eligibility rule.

Before full results, execute the winter pilot with all four policies. It passes only when every daily solve is accepted within 300 seconds, the replay finishes within eight hours, deadline recovery failures are zero and HP invasions are zero. Save the verdict before producing comparative result tables. On failure, switch uniformly to 72-hour eligibility, regenerate the inputs/selection manifest and repeat Stages 2–4 before comparison.

- [ ] **Step 3: Run the test, then run the full seasonal matrix.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_replay_integration tests.paper.test_cli -v`
Expected: all selected tests pass.

Run: `conda run -n scip_env python -m experiments.paper spot-gpu pilot --input-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs --output-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead`
Expected: a timestamped `pilot_feasibility.json` with an explicit pass/fail verdict.

Only after `pass=true`, run: `conda run -n scip_env python -m experiments.paper spot-gpu replay --input-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs --output-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead`.

- [ ] **Step 4: Commit the evaluation stage.**

```powershell
git add experiments/paper/ercot_2025_spot_gpu/evaluation.py experiments/paper/ercot_2025_spot_gpu/reporting.py experiments/paper/ercot_2025_spot_gpu/run.py experiments/paper/cli.py tests/paper/ercot_2025_spot_gpu/test_replay_integration.py docs/paper/results/ercot_2025_houston_spot_gpu_results.md docs/paper/README.md
git commit -m "feat: evaluate paper spot gpu study"
```

## Stage 5: Complete the reproducibility and manuscript handoff

**Files:**

- Modify: `docs/paper/results/ercot_2025_houston_spot_gpu_results.md`
- Modify: `docs/paper/README.md`

- [ ] **Step 1: Run the three-level test set and integrity checks.**

Run: `conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_inputs tests.paper.ercot_2025_spot_gpu.test_compute_contract tests.paper.ercot_2025_spot_gpu.test_scheduler tests.paper.ercot_2025_spot_gpu.test_replay_integration -v`
Expected: all four study test modules pass.

Run: `conda run -n scip_env python -m unittest discover -s tests/paper -t . -v`
Expected: all paper tests pass.

Run: `conda run -n scip_env python -m unittest discover -s tests/shared -t . -v`
Expected: all shared tests pass.

Run: `git diff --check`
Expected: no output and exit code 0.

Run: `git check-ignore -v data/energy/ercot_2024_historical_dam_load_zone_and_hub_prices.zip data/energy/ercot_2025_public_wind_solar_forecasts`
Expected: both raw paths are ignored.

- [ ] **Step 2: Produce the results record and commit it.**

The result record must state the feasibility-gate decision, hashes, exact commands, solver status/gap, source and model limitations, core/tail accounting, excluded/incomplete work and each policy’s seasonal outcomes. It must reject forbidden phrases: “local renewable consumption”, “local wind”, “local solar”, “marginal carbon”, “observed HP SLO”, “observed GPU power”, and “actual Houston workload”.

```powershell
git add docs/paper/results/ercot_2025_houston_spot_gpu_results.md docs/paper/README.md
git commit -m "docs: record verified spot gpu results"
```

## Self-review

- The former ten tasks are now five deliverable stages, each ending in one commit.
- Tests are reduced to four study-specific modules: input contract, compute contract, scheduler invariants and fixture integration. Existing paper/shared suites remain only the final regression gate.
- All requirements from the approved top-level design remain represented: timing semantics, raw-data exclusion, trace boundaries, HP risk reserve, gang feasibility, cost-first policy, renewable/carbon information boundary, 168-to-72-hour rule, seasonal evaluation and bounded claims.
- No career implementation or document is part of this plan.
