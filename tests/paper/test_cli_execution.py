from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from experiments.paper import cli
from experiments.paper.houston_2020.plotting import daily_costs, day_ahead


class PaperCliExecutionTests(unittest.TestCase):
    def test_day_ahead_delegates_with_exact_arguments(self) -> None:
        result = Mock()
        workload_path = Path("formal-workload.csv")
        energy_path = Path("formal-energy.csv")
        output_dir = Path("formal-output")
        with (
            patch.object(
                cli,
                "run_houston_2020_experiment",
                return_value=result,
            ) as run_experiment,
            patch.object(
                cli,
                "format_experiment_objective_summary",
                return_value="summary",
            ),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            cli.main(
                [
                    "day-ahead",
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
        self.assertEqual(stdout.getvalue(), "summary\n")

    def test_flex_ratio_delegates_with_exact_ratio_values(self) -> None:
        result = Mock(metrics=object())
        with (
            patch.object(
                cli,
                "run_flex_ratio_sensitivity_experiment",
                return_value=result,
            ) as run_experiment,
            patch.object(cli, "format_sensitivity_summary", return_value="summary"),
            patch("builtins.print"),
        ):
            cli.main(
                [
                    "sensitivity",
                    "flex-ratio",
                    "--flex-ratios",
                    "0,0.1",
                ]
            )

        self.assertEqual(run_experiment.call_args.kwargs["flex_ratios"], (0.0, 0.1))

    def test_daily_cost_plot_reads_existing_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            daily_metrics_path = root / "daily_metrics.csv"
            hourly_dispatch_path = root / "hourly_dispatch.csv"
            pd.DataFrame({"case": ["renewables_only"]}).to_csv(
                daily_metrics_path, index=False
            )
            pd.DataFrame({"case": ["renewables_only"]}).to_csv(
                hourly_dispatch_path, index=False
            )
            output_dir = root / "figures"

            with patch.object(
                daily_costs, "make_daily_case_cost_plots"
            ) as make_cost_plots:
                daily_costs.plot_daily_cost_results(
                    daily_metrics=daily_metrics_path,
                    hourly_dispatch=hourly_dispatch_path,
                    output_dir=output_dir,
                )

            actual_daily, actual_hourly, actual_output = make_cost_plots.call_args.args
            self.assertEqual(len(actual_daily), 1)
            self.assertEqual(len(actual_hourly), 1)
            self.assertEqual(actual_output, output_dir)

    def test_day_ahead_plot_reads_existing_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            hourly_path = root / "hourly_dispatch.csv"
            daily_metrics_path = root / "daily_metrics.csv"
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
                    "dc_power_mw": [2.0] * 4,
                    "electricity_price_cny_per_kwh": [0.5] * 4,
                    "hourly_operating_cost_cny": [800.0, 700.0, 600.0, 500.0],
                }
            ).to_csv(hourly_path, index=False)
            pd.DataFrame({"day": [28]}).to_csv(daily_metrics_path, index=False)
            output_dir = root / "figures"
            daily_output = output_dir / "day_28"

            with (
                patch.object(
                    day_ahead,
                    "make_daily_plots",
                    return_value=daily_output,
                ) as make_daily,
                patch.object(
                    day_ahead, "make_task_delay_objective_plot"
                ) as make_delay_plot,
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                day_ahead.plot_day_ahead_results(
                    hourly_dispatch=hourly_path,
                    daily_metrics=daily_metrics_path,
                    day_number=28,
                    output_dir=output_dir,
                )

            self.assertEqual(make_daily.call_args.args[1:], (28, output_dir))
            self.assertEqual(
                make_delay_plot.call_args.args[1],
                daily_output / "task_delay_objectives.png",
            )
            self.assertIn("Grid-only accounting baseline: 1000.0000 CNY", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
