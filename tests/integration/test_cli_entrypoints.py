from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import run_day_ahead_experiment
import run_first_version
import dc_energy_opt
from dc_energy_opt.config import Parameters
from dc_energy_opt.data import load_and_prepare, load_houston_energy_scenario
from dc_energy_opt.optimization import build_and_solve, run_rolling_day_ahead
from dc_energy_opt.experiments import ExperimentResult


class CliEntrypointTests(unittest.TestCase):
    @staticmethod
    def _experiment() -> ExperimentResult:
        return ExperimentResult(
            hourly_dispatch=pd.DataFrame(),
            daily_metrics=pd.DataFrame(),
            case_metrics=pd.DataFrame(
                {
                    "case": ["renewables_only"],
                    "status": ["optimal"],
                    "operating_cost_cny": [1.0],
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
        self.assertIn("houston_2020_main_experiment", printed)
        self.assertIn("Operating cost metrics:", printed)
        self.assertIn("renewables_only", printed)

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
            "run_first_version.py 已迁移，请改用 run_day_ahead_experiment.py。",
            stdout.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
