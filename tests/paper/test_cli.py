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

    def test_sensitivity_command_requires_exact_study_name(self) -> None:
        command = self._parse_command(["sensitivity", "flex-ratio"])

        self.assertEqual(command.name, "sensitivity")
        self.assertEqual(command.study, "flex-ratio")
        self.assertEqual(
            command.arguments.output_dir,
            HOUSTON_2020.flex_ratio_sensitivity_output_dir,
        )

    def test_storage_sensitivity_commands_preserve_output_defaults(self) -> None:
        scale = self._parse_command(["sensitivity", "storage-scale"])
        energy_power = self._parse_command(
            ["sensitivity", "storage-energy-power"]
        )

        self.assertEqual(scale.study, "storage-scale")
        self.assertEqual(
            scale.arguments.output_dir,
            HOUSTON_2020.storage_scale_sensitivity_output_dir,
        )
        self.assertEqual(energy_power.study, "storage-energy-power")
        self.assertEqual(
            energy_power.arguments.output_dir,
            HOUSTON_2020.storage_energy_power_sensitivity_output_dir,
        )

    def test_plot_commands_use_existing_result_paths(self) -> None:
        day_ahead = self._parse_command(["plot", "day-ahead"])
        daily_costs = self._parse_command(["plot", "daily-costs"])

        self.assertEqual(day_ahead.name, "plot")
        self.assertEqual(day_ahead.arguments.plot_name, "day-ahead")
        self.assertEqual(day_ahead.arguments.day, 8)
        self.assertEqual(
            day_ahead.arguments.hourly_dispatch,
            Path(
                "outputs/paper/houston_2020/day_ahead/results/"
                "hourly_dispatch.csv"
            ),
        )
        self.assertEqual(daily_costs.arguments.plot_name, "daily-costs")
        self.assertEqual(
            daily_costs.arguments.daily_metrics,
            Path(
                "outputs/paper/houston_2020/day_ahead/results/"
                "daily_metrics.csv"
            ),
        )


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
