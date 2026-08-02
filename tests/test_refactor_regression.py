from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

import run_first_version
import scip_first_version
from scip_first_version.config import Parameters
from scip_first_version.data import (
    build_provisional_energy_scenario,
    load_and_prepare,
    load_energy_scenario,
    load_houston_energy_scenario,
    load_phoenix_weather_source,
)
from scip_first_version.model import (
    PendingFlexibleTask,
    WindowSolveState,
    build_and_solve,
)
from scip_first_version.rolling import ROLLING_CASES, run_rolling_day_ahead


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = (
    PROJECT_ROOT / "data" / "houston_2020_main_experiment_energy_scenario.csv"
)


class RefactorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.csv_path = Path(
            "data/instance_usage_grouped_300_seconds_month.csv"
        )
        cls.raw, cls.hourly, cls.representative_day, cls.stress_day = (
            load_and_prepare(cls.csv_path)
        )

    def test_data_preparation_preserves_representative_and_stress_days(self) -> None:
        self.assertEqual(len(self.raw), 8064)
        self.assertEqual(len(self.hourly), 28 * 24)
        self.assertEqual(self.representative_day, 8)
        self.assertEqual(self.stress_day, 28)

    def test_entrypoints_reexport_public_interfaces(self) -> None:
        runner_exports = {
            "Parameters": Parameters,
            "load_and_prepare": load_and_prepare,
            "load_houston_energy_scenario": load_houston_energy_scenario,
            "build_and_solve": build_and_solve,
            "run_rolling_day_ahead": run_rolling_day_ahead,
            "make_plots": run_first_version.make_plots,
            "main": run_first_version.main,
        }
        package_exports = {
            "Parameters": Parameters,
            "build_provisional_energy_scenario": (
                build_provisional_energy_scenario
            ),
            "load_phoenix_weather_source": load_phoenix_weather_source,
            "load_energy_scenario": load_energy_scenario,
            "load_houston_energy_scenario": load_houston_energy_scenario,
            "load_and_prepare": load_and_prepare,
            "build_and_solve": build_and_solve,
            "PendingFlexibleTask": PendingFlexibleTask,
            "WindowSolveState": WindowSolveState,
            "ROLLING_CASES": ROLLING_CASES,
            "run_rolling_day_ahead": run_rolling_day_ahead,
        }

        self.assertEqual(set(run_first_version.__all__), set(runner_exports))
        self.assertEqual(set(scip_first_version.__all__), set(package_exports))
        for name, exported_object in runner_exports.items():
            self.assertIs(getattr(run_first_version, name), exported_object)
        for name, exported_object in package_exports.items():
            self.assertIs(getattr(scip_first_version, name), exported_object)

    def test_default_four_cases_satisfy_rolling_constraints(self) -> None:
        cpu_arrival = self.hourly.sort_values(["day", "hour"])[
            "avg_cpu"
        ].to_numpy(dtype=float)
        params = Parameters()
        scenario = load_houston_energy_scenario(
            SCENARIO_PATH,
            params,
        )
        metrics_by_case = {}

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            for (
                case_name,
                enable_shift,
                enable_storage,
            ) in ROLLING_CASES:
                result, metrics, daily = run_rolling_day_ahead(
                    cpu_arrival=cpu_arrival,
                    energy_scenario=scenario,
                    params=params,
                    case_name=case_name,
                    enable_shift=enable_shift,
                    enable_storage=enable_storage,
                    output_dir=output_dir,
                    show_log=False,
                )
                metrics_by_case[case_name] = metrics
                self.assertEqual(len(result), 675)
                self.assertEqual(len(daily), 28)
                self.assertEqual(result["case"].unique().tolist(), [case_name])
                self.assertGreaterEqual(
                    float(result["grid_power_mw"].min()),
                    0.0,
                )
                self.assertLessEqual(
                    float(result["grid_power_mw"].max()),
                    params.grid_capacity_mw + 1e-8,
                )
                self.assertLessEqual(
                    metrics["cpu_conservation_error"],
                    1e-9,
                )
                self.assertLessEqual(
                    float(result["cpu_scheduled_pu"].max()),
                    params.cpu_capacity_pu + 1e-9,
                )
                np.testing.assert_allclose(
                    result["grid_power_mw"]
                    + result["solar_used_mw"]
                    + result["wind_used_mw"]
                    + result["discharge_mw"],
                    result["dc_power_mw"] + result["charge_mw"],
                    rtol=0.0,
                    atol=1e-7,
                )
                np.testing.assert_allclose(
                    result["solar_used_mw"]
                    + result["solar_curtailed_mw"],
                    result["solar_available_mw"],
                    rtol=0.0,
                    atol=1e-7,
                )
                np.testing.assert_allclose(
                    result["wind_used_mw"]
                    + result["wind_curtailed_mw"],
                    result["wind_available_mw"],
                    rtol=0.0,
                    atol=1e-7,
                )
                self.assertAlmostEqual(
                    metrics["operating_cost_cny"],
                    metrics["grid_purchase_cost_cny"]
                    + metrics["solar_om_cost_cny"]
                    + metrics["wind_om_cost_cny"]
                    + metrics["battery_om_cost_cny"]
                    + metrics["battery_degradation_cost_cny"],
                    delta=1e-6,
                )
                self.assertAlmostEqual(
                    metrics["operating_cost_cny"],
                    float(result["hourly_operating_cost_cny"].sum()),
                    delta=1e-6,
                )
                self.assertTrue(np.isfinite(metrics["mip_gap"]))
                self.assertLessEqual(metrics["maximum_task_delay_h"], 3)
                if enable_shift:
                    self.assertGreater(
                        metrics["warmup_carry_in_task_cpu_pu_hours"],
                        0.0,
                    )
                if enable_storage:
                    self.assertAlmostEqual(
                        float(result["soc_start"].iloc[0]),
                        float(result["soc_end"].iloc[-1]),
                        delta=1e-8,
                    )
                    self.assertLessEqual(
                        float(
                            (
                                result["charge_mw"]
                                * result["discharge_mw"]
                            ).max()
                        ),
                        1e-8,
                    )
                    np.testing.assert_allclose(
                        result["soc_end"],
                        result["soc_start"]
                        + (
                            params.charge_efficiency
                            * result["charge_mw"]
                            - result["discharge_mw"]
                            / params.discharge_efficiency
                        )
                        * params.time_step_h
                        / params.battery_energy_mwh,
                        rtol=0.0,
                        atol=1e-8,
                    )
                else:
                    np.testing.assert_allclose(
                        result[
                            [
                                "charge_mw",
                                "discharge_mw",
                                "charge_active",
                                "discharge_active",
                            ]
                        ],
                        0.0,
                        rtol=0.0,
                        atol=1e-12,
                    )
                    np.testing.assert_allclose(
                        result[["soc_start", "soc_end"]],
                        params.battery_soc_initial,
                        rtol=0.0,
                        atol=1e-12,
                    )

        self.assertLessEqual(
            metrics_by_case["renewables_storage"]["operating_cost_cny"],
            metrics_by_case["renewables_only"]["operating_cost_cny"]
            + 0.010001,
        )
        self.assertLessEqual(
            metrics_by_case["joint"]["operating_cost_cny"],
            metrics_by_case["renewables_shift"]["operating_cost_cny"]
            + 0.010001,
        )


if __name__ == "__main__":
    unittest.main()
