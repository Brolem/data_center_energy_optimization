from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from run_first_version import _archive_source_files, main, parse_args
from scip_first_version.config import Parameters


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = Path("data/instance_usage_grouped_300_seconds_month.csv")
WEATHER_SOURCE_PATH = Path(
    "data/phoenix_nasa_power_20190501_20190528_hourly.csv"
)
SCENARIO_PATH = Path(
    "data/provisional_phoenix_weather_qinghai_tou_scenario.csv"
)
CASE_ORDER = [
    "grid_only",
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
]


class RunnerOutputTests(unittest.TestCase):
    def test_cli_defaults_target_deterministic_day_ahead_inputs(self) -> None:
        with patch("sys.argv", ["run_first_version.py"]):
            arguments = parse_args()

        self.assertIsInstance(arguments.input, Path)
        self.assertIsInstance(arguments.weather_source, Path)
        self.assertIsInstance(arguments.energy_scenario, Path)
        self.assertIsInstance(arguments.output_dir, Path)
        self.assertEqual(arguments.input, INPUT_PATH)
        self.assertEqual(
            arguments.weather_source,
            WEATHER_SOURCE_PATH,
        )
        self.assertEqual(
            arguments.energy_scenario,
            SCENARIO_PATH,
        )
        self.assertEqual(
            arguments.output_dir,
            Path("outputs/day_ahead_deterministic"),
        )
        self.assertIsNone(arguments.day)
        self.assertFalse(arguments.show_scip_log)

    def test_source_archive_skips_copy_when_source_is_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory).resolve()
            source_path = output_dir / "source.csv"
            original_content = "hour,value\n0,1\n"
            source_path.write_text(original_content, encoding="utf-8")

            with patch("run_first_version.shutil.copy2") as copy2:
                _archive_source_files([source_path], output_dir)

            copy2.assert_not_called()
            self.assertEqual(
                source_path.read_text(encoding="utf-8"),
                original_content,
            )

    def test_cli_rejects_colliding_source_basenames_before_solving(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            weather_dir = root / "weather"
            input_dir.mkdir()
            weather_dir.mkdir()
            input_path = input_dir / "shared.csv"
            weather_path = weather_dir / "shared.csv"
            scenario_path = root / "scenario.csv"
            for path in (input_path, weather_path, scenario_path):
                path.write_text("placeholder\n", encoding="utf-8")
            arguments = [
                "run_first_version.py",
                "--input",
                str(input_path),
                "--weather-source",
                str(weather_path),
                "--energy-scenario",
                str(scenario_path),
                "--output-dir",
                str(root / "outputs"),
            ]

            with (
                patch("sys.argv", arguments),
                patch("run_first_version.build_and_solve") as solve,
                self.assertRaises(ValueError) as context,
            ):
                main()

            solve.assert_not_called()
            message = str(context.exception)
            self.assertIn("shared.csv", message)
            self.assertIn(str(input_path.resolve()), message)
            self.assertIn(str(weather_path.resolve()), message)

    @unittest.skipUnless(os.name == "nt", "requires Windows path semantics")
    def test_source_archive_rejects_case_only_target_collision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_dir = root / "first"
            second_dir = root / "second"
            output_dir = root / "outputs"
            first_dir.mkdir()
            second_dir.mkdir()
            output_dir.mkdir()
            first_source = first_dir / "Shared.csv"
            second_source = second_dir / "shared.csv"
            first_source.write_text("first\n", encoding="utf-8")
            second_source.write_text("second\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                _archive_source_files(
                    [first_source, second_source],
                    output_dir,
                )

            self.assertEqual(list(output_dir.iterdir()), [])

    def test_default_cli_generates_deterministic_day_ahead_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "results"
            arguments = [
                "run_first_version.py",
                "--output-dir",
                str(output_dir),
            ]
            with (
                patch("sys.argv", arguments),
                patch("run_first_version.make_plots") as make_plots,
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                main()

            make_plots.assert_called_once()
            self.assertTrue(stdout.getvalue().isascii())
            model_input = pd.read_csv(
                output_dir / "model_input_typical_day.csv"
            )
            hourly = pd.read_csv(output_dir / "hourly_case_results.csv")
            metrics = pd.read_csv(output_dir / "case_metrics.csv")
            with (output_dir / "run_metadata.json").open(
                encoding="utf-8"
            ) as file:
                metadata = json.load(file)

            self.assertEqual(metrics["case"].tolist(), CASE_ORDER)
            self.assertEqual(len(model_input), 24)
            self.assertEqual(len(hourly), 5 * 24)
            self.assertEqual(
                hourly.groupby("case", sort=False).size().index.tolist(),
                CASE_ORDER,
            )
            self.assertEqual(
                hourly.groupby("case", sort=False).size().tolist(),
                [24] * 5,
            )
            self.assertTrue(
                {
                    "cpu_arrival_pu",
                    "hour",
                    "solar_irradiance_wh_m2",
                    "wind_speed_50m_m_s",
                    "solar_available_mw",
                    "wind_available_mw",
                    "tou_period",
                    "electricity_price_cny_per_kwh",
                }.issubset(model_input.columns)
            )
            self.assertTrue(
                {
                    "case",
                    "hour",
                    "cpu_arrival_pu",
                    "cpu_scheduled_pu",
                    "it_power_mw",
                    "dc_power_mw",
                    "grid_power_mw",
                    "solar_available_mw",
                    "solar_used_mw",
                    "solar_curtailed_mw",
                    "wind_available_mw",
                    "wind_used_mw",
                    "wind_curtailed_mw",
                    "charge_mw",
                    "discharge_mw",
                    "soc_start",
                    "soc_end",
                    "charge_active",
                    "discharge_active",
                    "tou_period",
                    "electricity_price_cny_per_kwh",
                    "hourly_grid_purchase_cost_cny",
                    "hourly_solar_om_cost_cny",
                    "hourly_wind_om_cost_cny",
                    "hourly_battery_om_cost_cny",
                    "hourly_operating_cost_cny",
                }.issubset(hourly.columns)
            )
            self.assertTrue(
                {
                    "case",
                    "grid_purchase_cost_cny",
                    "solar_om_cost_cny",
                    "wind_om_cost_cny",
                    "battery_om_cost_cny",
                    "operating_cost_cny",
                    "operating_cost_savings_vs_grid_only_pct",
                    "grid_purchase_energy_mwh",
                    "grid_peak_power_mw",
                    "renewable_available_energy_mwh",
                    "renewable_used_energy_mwh",
                    "renewable_curtailment_energy_mwh",
                    "renewable_curtailment_rate_pct",
                    "battery_charged_energy_mwh",
                    "battery_discharged_energy_mwh",
                    "battery_active_periods",
                    "total_task_delay_cpu_hours",
                    "average_flexible_task_delay_h",
                    "cpu_conservation_error",
                    "soc_cycle_error",
                    "max_simultaneous_charge_discharge_mw2",
                    "primary_solve_status",
                    "secondary_solve_status",
                }.issubset(metrics.columns)
            )
            self.assertAlmostEqual(
                float(
                    metrics.loc[
                        metrics["case"] == "grid_only",
                        "operating_cost_savings_vs_grid_only_pct",
                    ].iloc[0]
                ),
                0.0,
            )

            self.assertEqual(metadata["model_type"], "deterministic_day_ahead")
            self.assertEqual(
                metadata["scenario_status"],
                "provisional_mixed_region_development_scenario",
            )
            self.assertEqual(
                metadata["weather_source"],
                {
                    "file": str(WEATHER_SOURCE_PATH),
                    "location": "Phoenix, Arizona, USA",
                    "latitude": 33.4484,
                    "longitude": -112.0740,
                    "time_standard": "LST",
                    "period": "2019-05-01/2019-05-28",
                },
            )
            self.assertEqual(
                metadata["electricity_price_source"],
                {
                    "file": str(SCENARIO_PATH),
                    "region": "Qinghai, China",
                    "currency": "CNY",
                    "tariff_type": "time_of_use",
                    "source_paper": (
                        "A novel demand response-based distributed "
                        "multi-energy system optimal operation framework "
                        "for data centers"
                    ),
                },
            )
            self.assertEqual(
                metadata["geographic_interpretation"],
                "当前 24 小时场景混合使用菲尼克斯气象和青海电价，"
                "只用于模型开发和模块验证。",
            )
            self.assertEqual(metadata["representative_day"], 8)
            self.assertEqual(metadata["stress_day"], 28)
            self.assertEqual(metadata["selected_day"], 8)
            parameter_values = metadata["parameters"]
            parameters = Parameters()
            self.assertEqual(
                parameter_values["server_idle_power_kw"],
                parameters.server_idle_power_kw,
            )
            self.assertEqual(
                parameter_values["solar_capacity_mw"],
                parameters.solar_capacity_mw,
            )
            self.assertEqual(
                parameter_values["wind_capacity_mw"],
                parameters.wind_capacity_mw,
            )
            self.assertIsInstance(metadata["software_versions"], dict)

            required_files = [
                "model_input_typical_day.csv",
                "all_days_hourly.csv",
                "hourly_case_results.csv",
                "case_metrics.csv",
                "run_metadata.json",
                INPUT_PATH.name,
                WEATHER_SOURCE_PATH.name,
                SCENARIO_PATH.name,
            ]
            required_files.extend(
                f"{case}_{stage}.lp"
                for case in CASE_ORDER
                for stage in ("primary", "secondary")
            )
            for filename in required_files:
                self.assertTrue((output_dir / filename).is_file(), filename)


if __name__ == "__main__":
    unittest.main()
