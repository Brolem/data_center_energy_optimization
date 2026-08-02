from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from scip_first_version.config import Parameters
from scip_first_version.data import _qinghai_tou
from scip_first_version.rolling import run_rolling_day_ahead


class RollingDayAheadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.params = replace(
            Parameters(),
            time_limit_s=10.0,
            relative_gap=1e-8,
        )

    def energy_scenario(self, analysis_days: int) -> pd.DataFrame:
        timestamps = pd.date_range(
            "2020-04-30 00:00:00",
            periods=24 + analysis_days * 24 + 3,
            freq="h",
        )
        periods, prices = _qinghai_tou(timestamps.hour.to_numpy(dtype=int))
        return pd.DataFrame(
            {
                "timestamp_lst": timestamps,
                "solar_available_mw": np.zeros(len(timestamps)),
                "wind_available_mw": np.zeros(len(timestamps)),
                "tou_period": periods,
                "electricity_price_cny_per_kwh": prices,
            }
        )

    def test_two_day_run_marks_analysis_and_settlement_tail(self) -> None:
        cpu_arrival = np.full(48, 0.20)
        with tempfile.TemporaryDirectory() as temporary_directory:
            hourly, metrics, daily = run_rolling_day_ahead(
                cpu_arrival=cpu_arrival,
                energy_scenario=self.energy_scenario(2),
                params=self.params,
                case_name="renewables_only",
                enable_shift=False,
                enable_storage=False,
                output_dir=Path(temporary_directory),
                show_log=False,
            )

        self.assertEqual(len(hourly), 51)
        self.assertEqual(hourly["case"].unique().tolist(), ["renewables_only"])
        self.assertEqual(
            hourly["period_role"].value_counts().to_dict(),
            {"analysis": 48, "settlement_tail": 3},
        )
        self.assertEqual(hourly.loc[48:, "cpu_arrival_pu"].tolist(), [0.0] * 3)
        self.assertAlmostEqual(
            float(hourly["cpu_scheduled_pu"].sum()),
            float(cpu_arrival.sum()),
        )
        self.assertEqual(len(daily), 2)
        self.assertEqual(metrics["analysis_hours"], 48)
        self.assertEqual(metrics["settlement_tail_hours"], 3)
        self.assertAlmostEqual(
            metrics["operating_cost_cny"],
            metrics["analysis_operating_cost_cny"]
            + metrics["settlement_tail_operating_cost_cny"],
        )
        self.assertAlmostEqual(
            metrics["settlement_tail_operating_cost_cny"],
            float(
                hourly.loc[
                    hourly["period_role"] == "settlement_tail",
                    "hourly_operating_cost_cny",
                ].sum()
            ),
        )
        self.assertGreater(metrics["settlement_tail_operating_cost_cny"], 0.0)
        self.assertAlmostEqual(metrics["cpu_conservation_error"], 0.0)

    def test_joint_run_preserves_cross_day_soc_and_task_constraints(self) -> None:
        cpu_arrival = np.full(48, 0.55)
        cpu_arrival[23] = 0.90
        energy = self.energy_scenario(2)
        energy.loc[:, "solar_available_mw"] = 0.40
        with tempfile.TemporaryDirectory() as temporary_directory:
            hourly, metrics, daily = run_rolling_day_ahead(
                cpu_arrival=cpu_arrival,
                energy_scenario=energy,
                params=self.params,
                case_name="joint",
                enable_shift=True,
                enable_storage=True,
                output_dir=Path(temporary_directory),
                show_log=False,
            )

        self.assertAlmostEqual(float(hourly.loc[0, "soc_start"]), 0.50)
        self.assertAlmostEqual(float(hourly.iloc[-1]["soc_end"]), 0.50)
        np.testing.assert_allclose(
            hourly["soc_end"].to_numpy(dtype=float)[:-1],
            hourly["soc_start"].to_numpy(dtype=float)[1:],
            rtol=0.0,
            atol=1e-8,
        )
        self.assertGreaterEqual(float(hourly["soc_start"].min()), 0.10 - 1e-8)
        self.assertLessEqual(float(hourly["soc_end"].max()), 0.90 + 1e-8)
        self.assertLessEqual(float(hourly["charge_mw"].max()), 0.50 + 1e-8)
        self.assertLessEqual(float(hourly["discharge_mw"].max()), 0.50 + 1e-8)
        self.assertLessEqual(metrics["maximum_task_delay_h"], 3)
        self.assertAlmostEqual(metrics["cpu_conservation_error"], 0.0, places=7)
        self.assertAlmostEqual(metrics["final_stored_energy_mwh"], 1.0)
        self.assertTrue(
            daily["window_terminal_stored_energy_mwh"].between(0.2, 1.8).all()
        )
        np.testing.assert_allclose(
            daily["committed_end_stored_energy_mwh"],
            daily["coordinated_committed_stored_energy_mwh"],
            rtol=0.0,
            atol=1e-8,
        )
        np.testing.assert_allclose(
            daily["actual_window_terminal_stored_energy_mwh"],
            daily["window_terminal_stored_energy_mwh"],
            rtol=0.0,
            atol=1e-8,
        )
        self.assertAlmostEqual(
            float(daily.iloc[-1]["window_terminal_stored_energy_mwh"]),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
