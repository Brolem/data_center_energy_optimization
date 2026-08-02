from __future__ import annotations

import inspect
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import get_type_hints

import numpy as np
import pandas as pd

from dc_energy_opt.config import Parameters
from dc_energy_opt.data import paper_tou_tariff
from dc_energy_opt.optimization import PendingFlexibleTask, build_and_solve
from dc_energy_opt.optimization.rolling_day_ahead import (
    _prewarm_carry_in,
    run_rolling_day_ahead,
)


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
        periods, prices = paper_tou_tariff(
            timestamps.hour.to_numpy(dtype=int)
        )
        return pd.DataFrame(
            {
                "timestamp_lst": timestamps,
                "solar_available_mw": np.zeros(len(timestamps)),
                "wind_available_mw": np.zeros(len(timestamps)),
                "tou_period": periods,
                "electricity_price_cny_per_kwh": prices,
            }
        )

    def test_prewarm_carry_in_return_annotation_matches_structure(self) -> None:
        return_annotation = get_type_hints(_prewarm_carry_in)["return"]

        self.assertEqual(
            return_annotation,
            tuple[tuple[PendingFlexibleTask, ...], dict],
        )

    def test_preview_flexible_arrival_is_created_only_next_day(self) -> None:
        horizon = 27
        preview_arrival = 0.90
        nonflex_cpu = (1.0 - self.params.flex_ratio) * preview_arrival
        common = {
            "solar_available_mw": np.zeros(horizon),
            "wind_available_mw": np.zeros(horizon),
            "electricity_price_cny_per_kwh": np.full(horizon, 0.4489),
            "params": self.params,
            "enable_shift": True,
            "enable_storage": False,
            "enable_renewables": False,
            "show_log": False,
            "flex_arrival_hours": 24,
            "commit_hours": 24,
            "return_state": True,
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            current_window_arrival = np.zeros(horizon)
            current_window_arrival[24] = preview_arrival
            current_result, _, current_state = build_and_solve(
                cpu_arrival=current_window_arrival,
                case_name="preview_arrival_current_window",
                output_dir=output_dir,
                **common,
            )

            next_window_arrival = np.zeros(horizon)
            next_window_arrival[0] = preview_arrival
            next_result, next_metrics, next_state = build_and_solve(
                cpu_arrival=next_window_arrival,
                case_name="preview_arrival_next_window",
                output_dir=output_dir,
                **common,
            )

        self.assertAlmostEqual(
            float(current_result.loc[24, "cpu_scheduled_pu"]),
            nonflex_cpu,
        )
        self.assertEqual(current_state.pending_flexible_tasks, ())
        self.assertAlmostEqual(
            float(next_result["cpu_scheduled_pu"].sum()),
            preview_arrival,
        )
        self.assertAlmostEqual(
            next_metrics["committed_flexible_cpu_pu_hours"],
            self.params.flex_ratio * preview_arrival,
        )
        self.assertEqual(next_state.pending_flexible_tasks, ())

        rolling_source = inspect.getsource(run_rolling_day_ahead)
        self.assertIn(
            "次日 3 小时前视只承担 70% 非柔性最低负荷",
            rolling_source,
        )
        self.assertIn(
            "其 30% 柔性任务不在当前截断窗口创建",
            rolling_source,
        )
        self.assertIn(
            "由下一日窗口在完整到期域内创建",
            rolling_source,
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
