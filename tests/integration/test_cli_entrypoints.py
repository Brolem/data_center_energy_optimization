from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import run_day_ahead_experiment
import run_first_version
import plot_day_ahead_day
import plot_daily_case_costs
import run_flex_ratio_sensitivity
import dc_energy_opt
from dc_energy_opt.config import Parameters
from dc_energy_opt.data import load_and_prepare, load_houston_energy_scenario
from dc_energy_opt.optimization import build_and_solve, run_rolling_day_ahead
from dc_energy_opt.experiments import ExperimentResult
from dc_energy_opt.experiments.flex_ratio_sensitivity import (
    FlexRatioSensitivityResult,
)


class CliEntrypointTests(unittest.TestCase):
    def test_flex_ratio_sensitivity_command_delegates_and_prints_summary(
        self,
    ) -> None:
        sensitivity_metrics = pd.DataFrame(
            {
                "scenario": [
                    "renewables_shift",
                    "renewables_shift",
                    "joint",
                    "joint",
                ],
                "baseline_case": [
                    "renewables_only",
                    "renewables_only",
                    "renewables_storage",
                    "renewables_storage",
                ],
                "flex_ratio": [0.0, 0.1, 0.0, 0.1],
                "status": ["optimal"] * 4,
                "operating_cost_cny": [100.0, 95.0, 80.0, 76.0],
                "baseline_operating_cost_cny": [100.0] * 2 + [80.0] * 2,
                "cost_savings_pct": [0.0, 5.0, 0.0, 5.0],
                "marginal_cost_savings_cny_per_flex_ratio": [
                    float("nan"),
                    50.0,
                    float("nan"),
                    40.0,
                ],
                "saturation_onset": [float("nan")] * 4,
            }
        )
        result = FlexRatioSensitivityResult(
            metrics=sensitivity_metrics,
            metadata={},
        )
        workload_path = Path("sensitivity-workload.csv")
        energy_path = Path("sensitivity-energy.csv")
        output_dir = Path("sensitivity-output")

        with (
            patch(
                "run_flex_ratio_sensitivity.run_flex_ratio_sensitivity_experiment",
                return_value=result,
            ) as run_experiment,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            run_flex_ratio_sensitivity.main(
                [
                    "--workload-data",
                    str(workload_path),
                    "--energy-data",
                    str(energy_path),
                    "--flex-ratios",
                    "0,0.1",
                    "--output-dir",
                    str(output_dir),
                ]
            )

        run_experiment.assert_called_once_with(
            workload_data=workload_path,
            energy_data=energy_path,
            output_dir=output_dir,
            flex_ratios=(0.0, 0.1),
            show_solver_log=False,
        )
        printed = stdout.getvalue()
        self.assertIn("renewables_shift", printed)
        self.assertIn("joint", printed)
        self.assertIn("baseline", printed)
        self.assertIn("saturation", printed)
        self.assertNotIn(str(output_dir), printed)

    def test_daily_case_cost_command_reads_existing_csv_and_delegates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            daily_metrics_path = root / "daily_metrics.csv"
            hourly_dispatch_path = root / "hourly_dispatch.csv"
            pd.DataFrame(
                {
                    "case": ["renewables_only"],
                    "day": [1],
                    "operating_cost_cny": [100.0],
                    "settlement_tail_operating_cost_cny": [0.0],
                }
            ).to_csv(daily_metrics_path, index=False)
            pd.DataFrame(
                {
                    "case": ["renewables_only"],
                    "day": [1],
                    "timestamp_lst": ["2020-05-01 00:00:00"],
                    "period_role": ["analysis"],
                }
            ).to_csv(hourly_dispatch_path, index=False)
            output_dir = root / "figures"

            with patch(
                "plot_daily_case_costs.make_daily_case_cost_plots"
            ) as make_cost_plots:
                plot_daily_case_costs.main(
                    [
                        "--daily-metrics",
                        str(daily_metrics_path),
                        "--hourly-dispatch",
                        str(hourly_dispatch_path),
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            actual_daily, actual_hourly, actual_output = (
                make_cost_plots.call_args.args
            )
            self.assertEqual(len(actual_daily), 1)
            self.assertEqual(len(actual_hourly), 1)
            self.assertEqual(actual_output, output_dir)

    def test_daily_plot_command_reads_existing_csv_and_delegates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            hourly_path = root / "hourly_dispatch.csv"
            pd.DataFrame(
                {
                    "case": [
                        "renewables_only",
                        "renewables_shift",
                        "renewables_storage",
                        "joint",
                    ],
                    "day": [28, 28, 28, 28],
                    "period_role": ["analysis"] * 4,
                    "dc_power_mw": [2.0, 2.0, 2.0, 2.0],
                    "electricity_price_cny_per_kwh": [0.5] * 4,
                    "hourly_operating_cost_cny": [800.0, 700.0, 600.0, 500.0],
                }
            ).to_csv(hourly_path, index=False)
            daily_metrics_path = root / "daily_metrics.csv"
            pd.DataFrame(
                {
                    "case": ["renewables_shift", "joint"],
                    "day": [28, 28],
                    "primary_task_delay_cpu_hours": [5.0, 6.0],
                    "secondary_task_delay_cpu_hours": [3.0, 4.0],
                }
            ).to_csv(daily_metrics_path, index=False)
            output_dir = root / "figures"
            daily_output = output_dir / "day_28"
            with (
                patch(
                    "plot_day_ahead_day.make_daily_plots",
                    return_value=daily_output,
                ) as make_daily,
                patch(
                    "plot_day_ahead_day.make_task_delay_objective_plot",
                ) as make_delay_plot,
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                plot_day_ahead_day.main(
                    [
                        "--hourly-dispatch",
                        str(hourly_path),
                        "--daily-metrics",
                        str(daily_metrics_path),
                        "--day",
                        "28",
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            hourly_results, day_number, actual_output = (
                make_daily.call_args.args
            )
            self.assertEqual(len(hourly_results), 4)
            self.assertEqual(day_number, 28)
            self.assertEqual(actual_output, output_dir)
            plotted_metrics, plotted_path = make_delay_plot.call_args.args
            self.assertEqual(len(plotted_metrics), 2)
            self.assertEqual(
                plotted_path,
                daily_output / "task_delay_objectives.png",
            )
            self.assertEqual(
                make_delay_plot.call_args.kwargs,
                {"day_number": 28},
            )
            printed = stdout.getvalue()
            self.assertIn(
                "Grid-only accounting baseline: 1000.0000 CNY",
                printed,
            )
            self.assertIn("Required grid peak: 2.0000 MW", printed)
            self.assertIn(
                "Wind + solar contribution: 200.0000 CNY (20.0000%)",
                printed,
            )
            self.assertIn("renewables_only", printed)
            self.assertIn("joint", printed)
            self.assertNotIn(str(daily_output), printed)

    @staticmethod
    def _experiment() -> ExperimentResult:
        return ExperimentResult(
            hourly_dispatch=pd.DataFrame(
                {
                    "case": ["renewables_only", "renewables_only"],
                    "dc_power_mw": [2.0, 1.0],
                    "electricity_price_cny_per_kwh": [0.5, 0.2],
                }
            ),
            daily_metrics=pd.DataFrame(),
            case_metrics=pd.DataFrame(
                {
                    "case": [
                        "renewables_only",
                        "renewables_shift",
                        "renewables_storage",
                        "joint",
                    ],
                    "status": ["optimal"] * 4,
                    "operating_cost_cny": [1000.0, 900.0, 950.0, 850.0],
                    "operating_cost_savings_vs_renewables_only_pct": [
                        0.0,
                        10.0,
                        5.0,
                        15.0,
                    ],
                    "total_task_delay_cpu_hours": [0.0, 3.0, 0.0, 2.0],
                    "maximum_task_delay_h": [0, 2, 0, 1],
                }
            ),
            metadata={"scenario_status": "houston_2020_main_experiment"},
        )

    def test_formal_defaults_are_exact(self) -> None:
        arguments = run_day_ahead_experiment.parse_args([])

        self.assertEqual(
            arguments.workload_data,
            Path("data/workload/google_2019_28d_5min.csv"),
        )
        self.assertEqual(
            arguments.energy_data,
            Path("data/energy/houston_2020_may_hourly.csv"),
        )
        self.assertEqual(
            arguments.output_dir,
            Path("outputs/houston_2020_main"),
        )
        self.assertFalse(arguments.show_solver_log)

    def test_formal_package_exports_current_interfaces(self) -> None:
        self.assertIs(dc_energy_opt.Parameters, Parameters)
        self.assertIs(dc_energy_opt.load_and_prepare, load_and_prepare)
        self.assertIs(
            dc_energy_opt.load_houston_energy_scenario,
            load_houston_energy_scenario,
        )
        self.assertIs(dc_energy_opt.build_and_solve, build_and_solve)
        self.assertIs(
            dc_energy_opt.run_rolling_day_ahead,
            run_rolling_day_ahead,
        )

    def test_legacy_entrypoint_does_not_export_internal_interfaces(self) -> None:
        for name in (
            "Parameters",
            "load_and_prepare",
            "load_houston_energy_scenario",
            "build_and_solve",
            "run_rolling_day_ahead",
            "make_plots",
            "run_houston_2020_experiment",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(run_first_version, name))

    def test_formal_parser_rejects_legacy_flags(self) -> None:
        with patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                run_day_ahead_experiment.parse_args(["--input", "old.csv"])

    def test_formal_main_delegates_and_prints_summary(self) -> None:
        output_dir = Path("formal-output")
        workload_path = Path("formal-workload.csv")
        energy_path = Path("formal-energy.csv")
        with (
            patch(
                "run_day_ahead_experiment.run_houston_2020_experiment",
                return_value=self._experiment(),
            ) as run_experiment,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            run_day_ahead_experiment.main(
                [
                    "--workload-data",
                    str(workload_path),
                    "--energy-data",
                    str(energy_path),
                    "--output-dir",
                    str(output_dir),
                    "--show-solver-log",
                ]
            )

        run_experiment.assert_called_once_with(
            workload_data=workload_path,
            energy_data=energy_path,
            output_dir=output_dir,
            show_solver_log=True,
        )
        printed = stdout.getvalue()
        self.assertIn(
            "Grid-only accounting baseline: 1200.0000 CNY",
            printed,
        )
        self.assertIn("Required grid peak: 2.0000 MW", printed)
        self.assertIn(
            "Wind + solar contribution: 200.0000 CNY (16.6667%)",
            printed,
        )
        self.assertIn("operating_cost", printed)
        self.assertIn("total_delay", printed)
        self.assertIn("max_delay", printed)
        self.assertIn("renewables_only", printed)
        self.assertIn("joint", printed)
        self.assertNotIn("houston_2020_main_experiment", printed)
        self.assertNotIn("Operating cost metrics:", printed)

    def test_legacy_flags_map_to_the_same_formal_experiment_call(self) -> None:
        workload_path = Path("legacy-workload.csv")
        energy_path = Path("legacy-energy.csv")
        output_dir = Path("legacy-output")
        formal_arguments = [
            "--workload-data",
            str(workload_path),
            "--energy-data",
            str(energy_path),
            "--output-dir",
            str(output_dir),
            "--show-solver-log",
        ]
        legacy_arguments = [
            "--input",
            str(workload_path),
            "--energy-scenario",
            str(energy_path),
            "--output-dir",
            str(output_dir),
            "--show-scip-log",
        ]

        with patch(
            "run_day_ahead_experiment.run_houston_2020_experiment",
            return_value=self._experiment(),
        ) as run_experiment:
            with patch("sys.stdout", new_callable=io.StringIO):
                run_day_ahead_experiment.main(formal_arguments)
            formal_call = run_experiment.call_args
            run_experiment.reset_mock()
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                run_first_version.main(legacy_arguments)

        self.assertEqual(run_experiment.call_args, formal_call)
        self.assertIn(
            "run_first_version.py is deprecated; use "
            "run_day_ahead_experiment.py.",
            stdout.getvalue(),
        )

    def test_legacy_migration_notice_is_ascii_safe(self) -> None:
        with (
            patch(
                "run_day_ahead_experiment.run_houston_2020_experiment",
                return_value=self._experiment(),
            ),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            run_first_version.main([])

        self.assertTrue(stdout.getvalue().isascii())

    def test_legacy_dash_prefixed_paths_reach_the_formal_experiment(self) -> None:
        with (
            patch(
                "run_day_ahead_experiment.run_houston_2020_experiment",
                return_value=self._experiment(),
            ) as run_experiment,
            patch("sys.stdout", new_callable=io.StringIO),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            run_first_version.main(
                [
                    "--input=-workload.csv",
                    "--energy-scenario=-energy.csv",
                    "--output-dir=-output",
                ]
            )

        run_experiment.assert_called_once_with(
            workload_data=Path("-workload.csv"),
            energy_data=Path("-energy.csv"),
            output_dir=Path("-output"),
            show_solver_log=False,
        )

    def test_legacy_defaults_map_exactly_to_formal_defaults(self) -> None:
        legacy_defaults = run_first_version.parse_args([])
        formal_defaults = run_day_ahead_experiment.parse_args([])

        self.assertEqual(legacy_defaults.input, formal_defaults.workload_data)
        self.assertEqual(
            legacy_defaults.energy_scenario,
            formal_defaults.energy_data,
        )
        self.assertEqual(legacy_defaults.output_dir, formal_defaults.output_dir)
        self.assertFalse(legacy_defaults.show_scip_log)
        self.assertFalse(formal_defaults.show_solver_log)

        with patch(
            "run_day_ahead_experiment.run_houston_2020_experiment",
            return_value=self._experiment(),
        ) as run_experiment:
            with patch("sys.stdout", new_callable=io.StringIO):
                run_day_ahead_experiment.main([])
            formal_call = run_experiment.call_args
            run_experiment.reset_mock()
            with patch("sys.stdout", new_callable=io.StringIO):
                run_first_version.main([])

        self.assertEqual(run_experiment.call_args, formal_call)


if __name__ == "__main__":
    unittest.main()
