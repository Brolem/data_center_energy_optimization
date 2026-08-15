from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from dc_energy_opt.config import Parameters
from experiments.career.ercot_2025_spot_gpu.rolling import (
    run_rolling_market_dispatch,
)
from experiments.career.ercot_2025_spot_gpu.settlement import (
    build_decision_metrics,
    settle_schedule,
)


def _energy_frame(prices: np.ndarray) -> pd.DataFrame:
    timestamps = pd.date_range("2025-08-01 00:00:00", periods=len(prices), freq="h")
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price_usd_per_mwh": prices,
            "solar_available_mw": np.zeros(len(prices)),
            "wind_available_mw": np.zeros(len(prices)),
        }
    )


class RollingSettlementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.params = Parameters(time_limit_s=10.0)
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_directory = Path(self.temporary_directory.name)
        self.workload = np.full(24, 0.10)
        self.forecast_energy = _energy_frame(np.full(27, 40.0))
        self.actual_energy = _energy_frame(np.linspace(10.0, 90.0, 27))

    def test_final_window_commits_analysis_and_settlement_closure_hours(self) -> None:
        schedule, daily_metrics = run_rolling_market_dispatch(
            workload_arrival_pu=self.workload,
            energy_scenario=self.forecast_energy,
            params=self.params,
            case_name="baseline_forecast",
            model_output_dir=self.output_directory,
            show_log=False,
        )

        self.assertEqual(len(schedule), 27)
        self.assertEqual(len(daily_metrics), 1)
        self.assertEqual((schedule["period_role"] == "analysis").sum(), 24)
        self.assertEqual(
            (schedule["period_role"] == "settlement_closure").sum(), 3
        )
        self.assertAlmostEqual(
            schedule["stored_energy_end_mwh"].iloc[-1],
            self.params.battery_soc_initial * self.params.battery_energy_mwh,
        )

    def test_actual_price_changes_settlement_without_changing_planned_actions(self) -> None:
        schedule, _ = run_rolling_market_dispatch(
            workload_arrival_pu=self.workload,
            energy_scenario=self.forecast_energy,
            params=self.params,
            case_name="baseline_forecast",
            model_output_dir=self.output_directory / "planned",
            show_log=False,
        )
        first_settlement = settle_schedule(
            planned_schedule=schedule,
            actual_energy=self.actual_energy,
            params=self.params,
        )
        changed_actual_energy = self.actual_energy.copy()
        changed_actual_energy.loc[0, "price_usd_per_mwh"] = 1_000.0
        changed_settlement = settle_schedule(
            planned_schedule=schedule,
            actual_energy=changed_actual_energy,
            params=self.params,
        )

        pd.testing.assert_frame_equal(
            first_settlement.loc[
                :, ["workload_scheduled_pu", "charge_mw", "discharge_mw"]
            ],
            changed_settlement.loc[
                :, ["workload_scheduled_pu", "charge_mw", "discharge_mw"]
            ],
        )
        self.assertNotEqual(
            first_settlement["actual_grid_settlement_usd"].sum(),
            changed_settlement["actual_grid_settlement_usd"].sum(),
        )
        self.assertTrue((first_settlement["actual_grid_power_mw"] >= 0.0).all())
        np.testing.assert_allclose(
            first_settlement["actual_grid_power_mw"],
            first_settlement["dc_power_mw"]
            + first_settlement["charge_mw"]
            - first_settlement["discharge_mw"]
            - first_settlement["actual_solar_used_mw"]
            - first_settlement["actual_wind_used_mw"],
        )

    def test_settlement_clips_only_a_small_grid_balance_residual(self) -> None:
        planned = pd.DataFrame(
            {
                "timestamp_utc": ["2025-08-01T00:00:00Z"],
                "workload_scheduled_pu": [0.1],
                "dc_power_mw": [1.0],
                "charge_mw": [0.0],
                "discharge_mw": [0.0],
                "solar_used_mw": [1.0000005],
                "wind_used_mw": [0.0],
            }
        )
        actual = _energy_frame(np.array([40.0]))
        actual["solar_available_mw"] = 1.0000005
        planned["timestamp_utc"] = pd.to_datetime(
            actual["timestamp_utc"], format="%Y-%m-%dT%H:%M:%SZ"
        )

        settlement = settle_schedule(
            planned_schedule=planned,
            actual_energy=actual,
            params=self.params,
        )

        self.assertEqual(float(settlement["actual_grid_power_mw"].iloc[0]), 0.0)

    def test_metrics_define_regret_against_oracle_actual_settlement(self) -> None:
        schedule, daily_metrics = run_rolling_market_dispatch(
            workload_arrival_pu=self.workload,
            energy_scenario=self.forecast_energy,
            params=self.params,
            case_name="oracle_actual",
            model_output_dir=self.output_directory / "oracle",
            show_log=False,
        )
        oracle_settlement = settle_schedule(
            planned_schedule=schedule,
            actual_energy=self.actual_energy,
            params=self.params,
        )
        baseline_settlement = oracle_settlement.copy()
        baseline_settlement["actual_grid_settlement_usd"] += 2.0
        baseline_settlement["workload_scheduled_pu"] += 1e-7
        baseline_daily_metrics = daily_metrics.copy()
        baseline_daily_metrics["case"] = "baseline_forecast"

        metrics = build_decision_metrics(
            settlements_by_case={
                "oracle_actual": oracle_settlement,
                "baseline_forecast": baseline_settlement,
            },
            daily_metrics_by_case={
                "oracle_actual": daily_metrics,
                "baseline_forecast": baseline_daily_metrics,
            },
        )

        oracle_metrics = metrics.loc[metrics["case"] == "oracle_actual"].iloc[0]
        baseline_metrics = metrics.loc[
            metrics["case"] == "baseline_forecast"
        ].iloc[0]
        self.assertAlmostEqual(oracle_metrics["decision_regret_usd"], 0.0)
        self.assertAlmostEqual(baseline_metrics["decision_regret_usd"], 54.0)
        self.assertAlmostEqual(baseline_metrics["spot_work_completion_rate"], 1.0)
        self.assertLessEqual(baseline_metrics["spot_work_completion_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
