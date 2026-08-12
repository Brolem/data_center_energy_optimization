from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dc_energy_opt.config import HOUSTON_2020


class PaperCliRoutingTests(unittest.TestCase):
    @staticmethod
    def _parse_command(arguments: list[str]) -> object:
        try:
            from experiments.paper.cli import parse_command
        except ModuleNotFoundError as error:
            raise AssertionError(
                "experiments.paper.cli must provide parse_command"
            ) from error
        return parse_command(arguments)

    def test_day_ahead_command_preserves_formal_defaults(self) -> None:
        command = self._parse_command(["day-ahead"])

        self.assertEqual(command.name, "day-ahead")
        self.assertIsNone(command.study)
        self.assertEqual(
            command.arguments.workload_data,
            HOUSTON_2020.workload_data,
        )
        self.assertEqual(
            command.arguments.energy_data,
            HOUSTON_2020.energy_data,
        )
        self.assertEqual(
            command.arguments.output_dir,
            HOUSTON_2020.main_output_dir,
        )
        self.assertFalse(command.arguments.show_solver_log)

    def test_houston_2020_output_paths_are_track_scoped(self) -> None:
        self.assertEqual(
            HOUSTON_2020.main_output_dir,
            Path("outputs/paper/houston_2020/day_ahead"),
        )
        self.assertEqual(
            HOUSTON_2020.flex_ratio_sensitivity_output_dir,
            Path("outputs/paper/houston_2020/sensitivity/flex_ratio"),
        )
        self.assertEqual(
            HOUSTON_2020.storage_scale_sensitivity_output_dir,
            Path("outputs/paper/houston_2020/sensitivity/storage_scale"),
        )
        self.assertEqual(
            HOUSTON_2020.storage_energy_power_sensitivity_output_dir,
            Path(
                "outputs/paper/houston_2020/sensitivity/"
                "storage_energy_power"
            ),
        )

    def test_experiment_commands_preserve_output_defaults(self) -> None:
        cases = (
            (["day-ahead"], None, HOUSTON_2020.main_output_dir),
            (
                ["sensitivity", "flex-ratio"],
                "flex-ratio",
                HOUSTON_2020.flex_ratio_sensitivity_output_dir,
            ),
            (
                ["sensitivity", "storage-scale"],
                "storage-scale",
                HOUSTON_2020.storage_scale_sensitivity_output_dir,
            ),
            (
                ["sensitivity", "storage-energy-power"],
                "storage-energy-power",
                HOUSTON_2020.storage_energy_power_sensitivity_output_dir,
            ),
        )

        for arguments, study, output_dir in cases:
            with self.subTest(arguments=arguments):
                command = self._parse_command(arguments)
                self.assertEqual(command.study, study)
                self.assertEqual(command.arguments.output_dir, output_dir)

    def test_experiment_commands_accept_output_dir_overrides(self) -> None:
        cases = (
            (["day-ahead"], Path("custom/day_ahead")),
            (
                ["sensitivity", "flex-ratio"],
                Path("custom/flex_ratio"),
            ),
            (
                ["sensitivity", "storage-scale"],
                Path("custom/storage_scale"),
            ),
            (
                ["sensitivity", "storage-energy-power"],
                Path("custom/storage_energy_power"),
            ),
        )

        for arguments, output_dir in cases:
            with self.subTest(arguments=arguments):
                command = self._parse_command(
                    [*arguments, "--output-dir", str(output_dir)]
                )
                self.assertEqual(command.arguments.output_dir, output_dir)

    def test_plot_commands_use_existing_result_paths(self) -> None:
        day_ahead = self._parse_command(["plot", "day-ahead"])
        daily_costs = self._parse_command(["plot", "daily-costs"])
        results_dir = HOUSTON_2020.main_output_dir / "results"
        figures_dir = HOUSTON_2020.main_output_dir / "figures"

        self.assertEqual(day_ahead.name, "plot")
        self.assertEqual(day_ahead.arguments.plot_name, "day-ahead")
        self.assertEqual(day_ahead.arguments.day, 8)
        self.assertEqual(
            day_ahead.arguments.hourly_dispatch,
            results_dir / "hourly_dispatch.csv",
        )
        self.assertEqual(
            day_ahead.arguments.daily_metrics,
            results_dir / "daily_metrics.csv",
        )
        self.assertEqual(day_ahead.arguments.output_dir, figures_dir)
        self.assertEqual(daily_costs.arguments.plot_name, "daily-costs")
        self.assertEqual(
            daily_costs.arguments.daily_metrics,
            results_dir / "daily_metrics.csv",
        )
        self.assertEqual(
            daily_costs.arguments.hourly_dispatch,
            results_dir / "hourly_dispatch.csv",
        )
        self.assertEqual(daily_costs.arguments.output_dir, figures_dir)


class PaperCliExecutionTests(unittest.TestCase):
    def test_experiment_commands_route_to_exact_implementations(self) -> None:
        from experiments.paper import cli

        routes = (
            (
                ["day-ahead"],
                "run_houston_2020_experiment",
                "format_experiment_objective_summary",
            ),
            (
                ["sensitivity", "flex-ratio"],
                "run_flex_ratio_sensitivity_experiment",
                "format_sensitivity_summary",
            ),
            (
                ["sensitivity", "storage-scale"],
                "run_storage_scale_sensitivity_experiment",
                "format_storage_scale_sensitivity_summary",
            ),
            (
                ["sensitivity", "storage-energy-power"],
                "run_storage_energy_power_sensitivity_experiment",
                "format_storage_energy_power_sensitivity_summary",
            ),
        )
        for arguments, runner_name, formatter_name in routes:
            with self.subTest(arguments=arguments):
                result = Mock(metrics=object())
                with (
                    patch.object(cli, runner_name, return_value=result) as runner,
                    patch.object(
                        cli, formatter_name, return_value="summary"
                    ) as formatter,
                    patch("builtins.print") as print_output,
                ):
                    cli.main(arguments)

                runner.assert_called_once()
                expected_formatter_argument = (
                    result if arguments == ["day-ahead"] else result.metrics
                )
                formatter.assert_called_once_with(expected_formatter_argument)
                print_output.assert_called_once_with("summary")

    def test_plot_commands_route_to_exact_plotting_functions(self) -> None:
        from experiments.paper import cli

        with patch.object(cli, "plot_day_ahead_results") as plot_day_ahead:
            cli.main(["plot", "day-ahead", "--day", "28"])
        self.assertEqual(plot_day_ahead.call_args.kwargs["day_number"], 28)

        with patch.object(cli, "plot_daily_cost_results") as plot_daily_costs:
            cli.main(["plot", "daily-costs"])
        plot_daily_costs.assert_called_once()


if __name__ == "__main__":
    unittest.main()
