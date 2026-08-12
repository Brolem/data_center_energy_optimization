from __future__ import annotations

import io
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd

import dc_energy_opt.data as energy_data
from dc_energy_opt.config import Parameters
from dc_energy_opt.optimization import (
    PendingFlexibleTask,
    build_and_solve,
)
from dc_energy_opt.optimization.window_model import _solve_status_is_accepted


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOUSTON_SCENARIO_PATH = (
    PROJECT_ROOT / "data" / "energy" / "houston_2020_may_hourly.csv"
)


class CostOptimizationModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workload_path = (
            PROJECT_ROOT
            / "data"
            / "workload"
            / "google_2019_28d_5min.csv"
        )
        _, hourly, representative_day, _ = energy_data.load_and_prepare(
            workload_path
        )
        if representative_day != 8:
            raise AssertionError(
                f"代表日应为 8，实际为 {representative_day}。"
            )
        cls.cpu_arrival = (
            hourly[hourly["day"] == representative_day]
            .sort_values("hour")["avg_cpu"]
            .to_numpy(dtype=float)
        )
        cls.params = Parameters()
        cls.scenario = energy_data.load_houston_energy_scenario(
            HOUSTON_SCENARIO_PATH,
            cls.params,
        ).iloc[24:48].reset_index(drop=True)
        cls.temporary_directory = TemporaryDirectory()
        cls.output_dir = Path(cls.temporary_directory.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def solve(
        self,
        *,
        cpu_arrival: np.ndarray | None = None,
        solar_available_mw: np.ndarray | None = None,
        wind_available_mw: np.ndarray | None = None,
        electricity_price_cny_per_kwh: np.ndarray | None = None,
        params: Parameters | None = None,
        enable_shift: bool = False,
        enable_storage: bool = False,
        enable_renewables: bool = True,
        case_name: str,
        lp_output_dir: Path | None = None,
    ) -> tuple[pd.DataFrame, dict]:
        return build_and_solve(
            cpu_arrival=(
                self.cpu_arrival if cpu_arrival is None else cpu_arrival
            ),
            solar_available_mw=(
                self.scenario["solar_available_mw"].to_numpy(dtype=float)
                if solar_available_mw is None
                else solar_available_mw
            ),
            wind_available_mw=(
                self.scenario["wind_available_mw"].to_numpy(dtype=float)
                if wind_available_mw is None
                else wind_available_mw
            ),
            electricity_price_cny_per_kwh=(
                self.scenario[
                    "electricity_price_cny_per_kwh"
                ].to_numpy(dtype=float)
                if electricity_price_cny_per_kwh is None
                else electricity_price_cny_per_kwh
            ),
            params=self.params if params is None else params,
            enable_shift=enable_shift,
            enable_storage=enable_storage,
            enable_renewables=enable_renewables,
            case_name=case_name,
            lp_output_dir=lp_output_dir or self.output_dir,
            show_log=False,
        )

    def test_lp_files_use_stage_names_inside_window_directory(self) -> None:
        lp_output_dir = self.output_dir / "day_01"
        lp_output_dir.mkdir()
        self.solve(
            case_name="lp_path_layout",
            lp_output_dir=lp_output_dir,
        )
        self.assertTrue((lp_output_dir / "stage_1_cost.lp").is_file())
        self.assertTrue((lp_output_dir / "stage_2_delay.lp").is_file())
        self.assertFalse(
            (lp_output_dir / "lp_path_layout_primary.lp").exists()
        )
        self.assertFalse(
            (lp_output_dir / "lp_path_layout_secondary.lp").exists()
        )

    def test_default_solve_does_not_print_lp_write_messages(self) -> None:
        lp_output_dir = self.output_dir / "quiet_lp"
        lp_output_dir.mkdir(exist_ok=True)

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.solve(
                case_name="quiet_lp_messages",
                lp_output_dir=lp_output_dir,
            )

        self.assertNotIn("wrote problem to file", stdout.getvalue())

    def test_primary_costs_are_independently_recomputed_in_cny(self) -> None:
        result, metrics = self.solve(case_name="primary_cost_recompute")
        time_step_h = self.params.time_step_h
        expected_grid = float(
            (
                result["electricity_price_cny_per_kwh"]
                * result["grid_power_mw"]
                * time_step_h
                * 1000.0
            ).sum()
        )
        expected_solar = float(
            (
                self.params.solar_om_cost_cny_per_kwh
                * result["solar_used_mw"]
                * time_step_h
                * 1000.0
            ).sum()
        )
        expected_wind = float(
            (
                self.params.wind_om_cost_cny_per_kwh
                * result["wind_used_mw"]
                * time_step_h
                * 1000.0
            ).sum()
        )
        expected_hourly_battery = (
            self.params.battery_om_cost_cny_per_kwh
            * (result["charge_mw"] + result["discharge_mw"])
            * time_step_h
            * 1000.0
        )
        expected_battery = float(expected_hourly_battery.sum())
        expected_hourly_battery_degradation = (
            self.params.battery_degradation_cost_cny_per_kwh
            * result["discharge_mw"]
            * time_step_h
            * 1000.0
        )
        expected_battery_degradation = float(
            expected_hourly_battery_degradation.sum()
        )
        expected_operating = (
            expected_grid
            + expected_solar
            + expected_wind
            + expected_battery
            + expected_battery_degradation
        )

        self.assertAlmostEqual(
            metrics["grid_purchase_cost_cny"], expected_grid, places=7
        )
        self.assertAlmostEqual(
            metrics["solar_om_cost_cny"], expected_solar, places=7
        )
        self.assertAlmostEqual(
            metrics["wind_om_cost_cny"], expected_wind, places=7
        )
        self.assertEqual(metrics["battery_om_cost_cny"], expected_battery)
        np.testing.assert_allclose(
            result["hourly_battery_om_cost_cny"],
            expected_hourly_battery,
            rtol=0.0,
            atol=1e-12,
        )
        self.assertEqual(
            metrics["battery_degradation_cost_cny"],
            expected_battery_degradation,
        )
        np.testing.assert_allclose(
            result["hourly_battery_degradation_cost_cny"],
            expected_hourly_battery_degradation,
            rtol=0.0,
            atol=1e-12,
        )
        self.assertAlmostEqual(
            metrics["operating_cost_cny"], expected_operating, places=7
        )
        self.assertAlmostEqual(
            metrics["primary_operating_cost_cny"],
            expected_operating,
            places=7,
        )
        self.assertTrue(
            np.allclose(
                result["hourly_operating_cost_cny"],
                result[
                    [
                        "hourly_grid_purchase_cost_cny",
                        "hourly_solar_om_cost_cny",
                        "hourly_wind_om_cost_cny",
                        "hourly_battery_om_cost_cny",
                        "hourly_battery_degradation_cost_cny",
                    ]
                ].sum(axis=1),
                rtol=0.0,
                atol=1e-9,
            )
        )
        self.assertTrue(
            (self.output_dir / "stage_1_cost.lp").is_file()
        )
        self.assertIn(
            "battery_om_cost_expr", build_and_solve.__code__.co_varnames
        )
        self.assertIn(
            "battery_degradation_cost_expr",
            build_and_solve.__code__.co_varnames,
        )
        self.assertIn(
            "primary_cost_expr", build_and_solve.__code__.co_varnames
        )
        self.assertEqual(metrics["status"], "optimal")
        self.assertAlmostEqual(
            metrics["solve_time_s"],
            metrics["primary_solve_time_s"]
            + metrics["secondary_solve_time_s"],
        )
        self.assertEqual(
            metrics["mip_gap"],
            max(metrics["primary_gap"], metrics["secondary_gap"]),
        )

    def test_full_cpu_grid_only_is_infeasible_under_fixed_grid_limit(self) -> None:
        cpu_arrival = np.full(24, 0.90)
        zeros = np.zeros(24)
        self.assertAlmostEqual(self.params.it_power_mw(0.90), 6.60)
        self.assertAlmostEqual(self.params.dc_power_mw(0.90), 7.26)
        with self.assertRaisesRegex(RuntimeError, "status=infeasible"):
            self.solve(
                cpu_arrival=cpu_arrival,
                solar_available_mw=zeros,
                wind_available_mw=zeros,
                enable_renewables=False,
                case_name="full_cpu_grid_only",
            )

    def test_renewable_allocation_and_power_balance_hold_hourly(self) -> None:
        result, _ = self.solve(case_name="renewable_balance")

        np.testing.assert_allclose(
            result["solar_used_mw"] + result["solar_curtailed_mw"],
            result["solar_available_mw"],
            rtol=0.0,
            atol=1e-9,
        )
        np.testing.assert_allclose(
            result["wind_used_mw"] + result["wind_curtailed_mw"],
            result["wind_available_mw"],
            rtol=0.0,
            atol=1e-9,
        )
        np.testing.assert_allclose(
            result["grid_power_mw"]
            + result["solar_used_mw"]
            + result["wind_used_mw"],
            result["dc_power_mw"],
            rtol=0.0,
            atol=1e-9,
        )

    def test_high_renewables_cause_positive_curtailment(self) -> None:
        renewable_power = np.full(24, 10.0)
        result, metrics = self.solve(
            solar_available_mw=renewable_power,
            wind_available_mw=renewable_power,
            case_name="high_renewable_curtailment",
        )

        self.assertGreater(
            metrics["renewable_curtailment_energy_mwh"], 0.0
        )
        self.assertGreater(
            float(
                (
                    result["solar_curtailed_mw"]
                    + result["wind_curtailed_mw"]
                ).sum()
            ),
            0.0,
        )
        self.assertGreaterEqual(float(result["grid_power_mw"].min()), 0.0)

    def test_infeasible_cpu_capacity_raises_explicit_error(self) -> None:
        params = replace(self.params, cpu_capacity_pu=0.01)

        with self.assertRaisesRegex(
            RuntimeError,
            r"stage=primary.*case=infeasible_cpu_capacity"
            r".*status=infeasible.*gap=.*primal_bound=.*dual_bound="
            r".*未找到可行解",
        ):
            self.solve(
                params=params,
                enable_renewables=False,
                case_name="infeasible_cpu_capacity",
            )

    def test_solve_status_acceptance_rejects_invalid_results(self) -> None:
        relative_gap = self.params.relative_gap
        scip_infinity = 1e20

        self.assertTrue(
            _solve_status_is_accepted(
                "optimal", 0.0, relative_gap, scip_infinity
            )
        )
        self.assertTrue(
            _solve_status_is_accepted(
                "gaplimit",
                relative_gap + 1e-12,
                relative_gap,
                scip_infinity,
            )
        )
        for status, gap in (
            ("timelimit", 0.0),
            ("gaplimit", relative_gap + 1e-9),
            ("gaplimit", float("nan")),
            ("gaplimit", float("inf")),
            ("gaplimit", scip_infinity),
            ("optimal", scip_infinity),
        ):
            with self.subTest(status=status, gap=gap):
                self.assertFalse(
                    _solve_status_is_accepted(
                        status, gap, relative_gap, scip_infinity
                    )
                )

    def test_storage_rejects_zero_energy_capacity(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            r"battery_energy_mwh 必须大于 0",
        ):
            self.solve(
                params=replace(self.params, battery_energy_mwh=0.0),
                enable_storage=True,
                case_name="zero_storage_energy_capacity",
            )

    def test_explicit_storage_boundaries_return_committed_state(self) -> None:
        horizon = 6
        result, _, state = build_and_solve(
            cpu_arrival=np.full(horizon, 0.50),
            solar_available_mw=np.zeros(horizon),
            wind_available_mw=np.zeros(horizon),
            electricity_price_cny_per_kwh=np.full(horizon, 0.4489),
            params=self.params,
            enable_shift=False,
            enable_storage=True,
            enable_renewables=False,
            case_name="explicit_storage_boundaries",
            lp_output_dir=self.output_dir,
            show_log=False,
            initial_stored_energy_mwh=0.8,
            terminal_stored_energy_mwh=1.2,
            committed_stored_energy_mwh=0.9,
            commit_hours=3,
            return_state=True,
        )

        self.assertAlmostEqual(result.loc[0, "soc_start"], 0.4)
        self.assertAlmostEqual(result.loc[horizon - 1, "soc_end"], 0.6)
        self.assertAlmostEqual(state.stored_energy_mwh, 0.9)
        self.assertEqual(state.pending_flexible_tasks, ())

    def test_storage_boundary_rounding_at_soc_min_is_clamped(self) -> None:
        horizon = 6
        params = replace(
            self.params,
            battery_energy_mwh=6.0,
            battery_charge_power_mw=1.5,
            battery_discharge_power_mw=1.5,
        )
        storage_min_mwh = params.battery_soc_min * params.battery_energy_mwh
        _, _, state = build_and_solve(
            cpu_arrival=np.full(horizon, 0.50),
            solar_available_mw=np.zeros(horizon),
            wind_available_mw=np.zeros(horizon),
            electricity_price_cny_per_kwh=np.full(horizon, 0.4489),
            params=params,
            enable_shift=False,
            enable_storage=True,
            enable_renewables=False,
            case_name="storage_boundary_rounding",
            lp_output_dir=self.output_dir,
            show_log=False,
            initial_stored_energy_mwh=storage_min_mwh,
            terminal_stored_energy_mwh=storage_min_mwh,
            committed_stored_energy_mwh=storage_min_mwh - 5e-16,
            commit_hours=3,
            return_state=True,
        )

        self.assertAlmostEqual(
            state.stored_energy_mwh,
            storage_min_mwh,
            places=12,
        )

    def test_late_flexible_task_is_carried_and_completed_next_day(self) -> None:
        horizon = 27
        cpu_arrival = np.zeros(horizon)
        cpu_arrival[23] = 0.90
        nonflex_cpu = (1.0 - self.params.flex_ratio) * 0.90
        params = replace(
            self.params,
            grid_capacity_mw=self.params.dc_power_mw(nonflex_cpu),
        )
        common = {
            "solar_available_mw": np.zeros(horizon),
            "wind_available_mw": np.zeros(horizon),
            "electricity_price_cny_per_kwh": np.full(horizon, 0.4489),
            "params": params,
            "enable_shift": True,
            "enable_storage": False,
            "enable_renewables": False,
            "lp_output_dir": self.output_dir,
            "show_log": False,
            "flex_arrival_hours": 24,
            "commit_hours": 24,
            "return_state": True,
        }

        first_result, _, first_state = build_and_solve(
            cpu_arrival=cpu_arrival,
            case_name="cross_day_carry_out",
            **common,
        )

        self.assertAlmostEqual(first_result.loc[23, "cpu_scheduled_pu"], nonflex_cpu)
        self.assertEqual(len(first_state.pending_flexible_tasks), 1)
        carried = first_state.pending_flexible_tasks[0]
        self.assertEqual(carried.origin_hour, 23)
        self.assertAlmostEqual(carried.remaining_cpu_pu, 0.27)

        second_result, _, second_state = build_and_solve(
            cpu_arrival=np.zeros(horizon),
            case_name="cross_day_carry_in",
            carry_in_tasks=(
                PendingFlexibleTask(
                    origin_hour=-1,
                    remaining_cpu_pu=carried.remaining_cpu_pu,
                ),
            ),
            **common,
        )

        self.assertAlmostEqual(second_result.loc[0, "cpu_scheduled_pu"], 0.27)
        self.assertAlmostEqual(second_result["cpu_scheduled_pu"].sum(), 0.27)
        self.assertEqual(second_state.pending_flexible_tasks, ())

    def test_disabled_storage_zero_capacity_preserves_finite_soc(self) -> None:
        params = replace(self.params, battery_energy_mwh=0.0)

        result, metrics = self.solve(
            params=params,
            enable_storage=False,
            case_name="disabled_zero_storage_energy_capacity",
        )

        self.assertTrue(
            np.isfinite(result[["soc_start", "soc_end"]]).all().all()
        )
        np.testing.assert_allclose(
            result[["soc_start", "soc_end"]],
            params.battery_soc_initial,
            rtol=0.0,
            atol=0.0,
        )
        self.assertTrue(np.isfinite(metrics["soc_cycle_error"]))
        self.assertEqual(metrics["soc_cycle_error"], 0.0)

    def test_shift_respects_three_hour_deadline_and_conserves_cpu(self) -> None:
        cpu_arrival = np.zeros(6)
        cpu_arrival[0] = 0.5
        prices = np.array([1.0, 1.0, 1.0, 0.5, 0.01, 0.01])
        zeros = np.zeros(6)
        params = replace(self.params, flex_ratio=1.0)

        result, metrics = self.solve(
            cpu_arrival=cpu_arrival,
            solar_available_mw=zeros,
            wind_available_mw=zeros,
            electricity_price_cny_per_kwh=prices,
            params=params,
            enable_shift=True,
            enable_renewables=False,
            case_name="three_hour_shift_deadline",
        )

        self.assertAlmostEqual(result.loc[4, "cpu_scheduled_pu"], 0.0)
        self.assertAlmostEqual(result.loc[5, "cpu_scheduled_pu"], 0.0)
        self.assertAlmostEqual(result["cpu_scheduled_pu"].sum(), 0.5)
        self.assertAlmostEqual(metrics["cpu_conservation_error"], 0.0)

    def test_peak_valley_storage_obeys_physical_limits_and_recomputes_om(
        self,
    ) -> None:
        prices = np.array([0.1804] * 8 + [0.7174] * 16)
        zeros = np.zeros(24)
        result, metrics = self.solve(
            cpu_arrival=np.full(24, 0.50),
            solar_available_mw=zeros,
            wind_available_mw=zeros,
            electricity_price_cny_per_kwh=prices,
            enable_storage=True,
            enable_renewables=False,
            case_name="peak_valley_storage",
        )

        self.assertGreater(float(result["charge_mw"].sum()), 1e-8)
        self.assertGreater(float(result["discharge_mw"].sum()), 1e-8)
        self.assertLessEqual(
            float(result["charge_mw"].max()),
            self.params.battery_charge_power_mw + 1e-8,
        )
        self.assertLessEqual(
            float(result["discharge_mw"].max()),
            self.params.battery_discharge_power_mw + 1e-8,
        )
        self.assertGreaterEqual(float(result["soc_start"].min()), 0.10 - 1e-8)
        self.assertLessEqual(float(result["soc_end"].max()), 0.90 + 1e-8)
        self.assertAlmostEqual(float(result.loc[0, "soc_start"]), 0.50)
        self.assertAlmostEqual(float(result.loc[23, "soc_end"]), 0.50)
        expected_soc_end = result["soc_start"] + (
            self.params.charge_efficiency * result["charge_mw"]
            - result["discharge_mw"] / self.params.discharge_efficiency
        ) * self.params.time_step_h / self.params.battery_energy_mwh
        np.testing.assert_allclose(
            result["soc_end"], expected_soc_end, rtol=0.0, atol=1e-8
        )
        np.testing.assert_allclose(
            result["soc_start"].iloc[1:].to_numpy(),
            result["soc_end"].iloc[:-1].to_numpy(),
            rtol=0.0,
            atol=1e-8,
        )
        for activity_column in ("charge_active", "discharge_active"):
            activity = result[activity_column]
            self.assertTrue(
                ((activity >= -1e-9) & (activity <= 1.0 + 1e-9)).all()
            )
            np.testing.assert_allclose(
                activity,
                np.round(activity),
                rtol=0.0,
                atol=1e-9,
            )
        self.assertTrue(
            (
                result["charge_mw"]
                <= self.params.battery_charge_power_mw
                * result["charge_active"]
                + 1e-9
            ).all()
        )
        self.assertTrue(
            (
                result["discharge_mw"]
                <= self.params.battery_discharge_power_mw
                * result["discharge_active"]
                + 1e-9
            ).all()
        )
        self.assertTrue(
            (
                result["charge_active"] + result["discharge_active"]
                <= 1.0 + 1e-8
            ).all()
        )
        for filename in ("stage_1_cost.lp", "stage_2_delay.lp"):
            lp_text = (self.output_dir / filename).read_text(encoding="utf-8")
            self.assertNotIn("storage_active_period_limit", lp_text)
        expected_hourly_om = (
            self.params.battery_om_cost_cny_per_kwh
            * (result["charge_mw"] + result["discharge_mw"])
            * self.params.time_step_h
            * 1000.0
        )
        np.testing.assert_allclose(
            result["hourly_battery_om_cost_cny"],
            expected_hourly_om,
            rtol=0.0,
            atol=1e-9,
        )
        self.assertAlmostEqual(
            metrics["battery_om_cost_cny"], float(expected_hourly_om.sum())
        )

    def test_flat_price_storage_can_remain_idle(self) -> None:
        zeros = np.zeros(24)
        result, metrics = self.solve(
            cpu_arrival=np.full(24, 0.50),
            solar_available_mw=zeros,
            wind_available_mw=zeros,
            electricity_price_cny_per_kwh=np.full(24, 0.4489),
            enable_storage=True,
            enable_renewables=False,
            case_name="flat_price_storage",
        )

        np.testing.assert_allclose(result["charge_mw"], 0.0, atol=1e-8)
        np.testing.assert_allclose(result["discharge_mw"], 0.0, atol=1e-8)
        self.assertEqual(metrics["battery_active_periods"], 0)

    def test_lexicographic_solves_cost_then_flexible_task_delay(self) -> None:
        cpu_arrival = np.zeros(24)
        cpu_arrival[0] = 0.50
        zeros = np.zeros(24)
        prices = np.full(24, 0.448900)
        prices[1] = 0.448894
        result, metrics = self.solve(
            cpu_arrival=cpu_arrival,
            solar_available_mw=zeros,
            wind_available_mw=zeros,
            electricity_price_cny_per_kwh=prices,
            params=replace(self.params, flex_ratio=1.0),
            enable_shift=True,
            enable_renewables=False,
            case_name="lexicographic_delay",
        )

        self.assertTrue(
            (self.output_dir / "stage_1_cost.lp").is_file()
        )
        self.assertTrue(
            (self.output_dir / "stage_2_delay.lp").is_file()
        )
        self.assertEqual(metrics["primary_solve_status"], "optimal")
        self.assertEqual(metrics["secondary_solve_status"], "optimal")
        self.assertLessEqual(
            metrics["operating_cost_cny"],
            metrics["primary_operating_cost_cny"] + 0.010001,
        )
        self.assertGreater(
            metrics["primary_total_task_delay_cpu_hours"],
            metrics["total_task_delay_cpu_hours"],
        )
        self.assertGreater(
            metrics["primary_committed_task_delay_cpu_hours"],
            metrics["committed_task_delay_cpu_hours"],
        )
        self.assertAlmostEqual(
            metrics["total_task_delay_cpu_hours"], 0.0, places=8
        )
        self.assertAlmostEqual(float(result.loc[0, "cpu_scheduled_pu"]), 0.50)

    def test_storage_never_costs_more_than_no_storage_beyond_tolerance(
        self,
    ) -> None:
        no_storage_result, no_storage_metrics = self.solve(
            case_name="renewables_no_storage"
        )
        storage_result, storage_metrics = self.solve(
            enable_storage=True,
            case_name="renewables_with_storage",
        )

        self.assertEqual(len(storage_result), len(no_storage_result))
        self.assertLessEqual(
            storage_metrics["operating_cost_cny"],
            no_storage_metrics["operating_cost_cny"] + 0.010001,
        )

    def test_storage_power_balance_and_cycle_metrics_match_hourly_results(
        self,
    ) -> None:
        prices = np.array([0.1804] * 8 + [0.7174] * 16)
        result, metrics = self.solve(
            electricity_price_cny_per_kwh=prices,
            enable_storage=True,
            case_name="storage_power_balance",
        )

        np.testing.assert_allclose(
            result["grid_power_mw"]
            + result["solar_used_mw"]
            + result["wind_used_mw"]
            + result["discharge_mw"],
            result["dc_power_mw"] + result["charge_mw"],
            rtol=0.0,
            atol=1e-8,
        )
        self.assertAlmostEqual(
            metrics["soc_cycle_error"],
            abs(float(result.loc[23, "soc_end"] - result.loc[0, "soc_start"])),
        )
        self.assertAlmostEqual(
            metrics["max_simultaneous_charge_discharge_mw2"],
            float((result["charge_mw"] * result["discharge_mw"]).max()),
        )
        self.assertAlmostEqual(metrics["soc_cycle_error"], 0.0, places=8)
        self.assertAlmostEqual(
            metrics["max_simultaneous_charge_discharge_mw2"], 0.0, places=8
        )


if __name__ == "__main__":
    unittest.main()
