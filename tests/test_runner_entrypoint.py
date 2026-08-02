from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import run_first_version
from dc_energy_opt.experiments import ExperimentResult


class RunnerEntrypointTests(unittest.TestCase):
    def test_cli_defaults_use_the_formal_houston_output_directory(self) -> None:
        with patch("sys.argv", ["run_first_version.py"]):
            arguments = run_first_version.parse_args()

        self.assertEqual(
            arguments.input,
            Path("data/workload/google_2019_28d_5min.csv"),
        )
        self.assertEqual(
            arguments.energy_scenario,
            Path("data/energy/houston_2020_may_hourly.csv"),
        )
        self.assertEqual(
            arguments.output_dir,
            Path("outputs/houston_2020_main"),
        )
        self.assertFalse(arguments.show_scip_log)

    def test_main_delegates_experiment_and_prints_metadata_and_metrics(
        self,
    ) -> None:
        case_metrics = pd.DataFrame(
            {
                "case": ["renewables_only"],
                "status": ["optimal"],
                "grid_purchase_cost_cny": [1.0],
                "solar_om_cost_cny": [2.0],
                "wind_om_cost_cny": [3.0],
                "battery_om_cost_cny": [4.0],
                "battery_degradation_cost_cny": [5.0],
                "operating_cost_cny": [15.0],
                "operating_cost_savings_vs_renewables_only_pct": [0.0],
                "renewable_curtailment_energy_mwh": [0.0],
                "renewable_curtailment_rate_pct": [0.0],
                "battery_equivalent_full_cycles": [0.0],
                "cross_day_task_cpu_pu_hours": [0.0],
                "average_flexible_task_delay_h": [0.0],
                "maximum_task_delay_h": [0],
                "grid_binding_hours": [0],
                "grid_minimum_margin_mw": [1.0],
                "solve_time_s": [2.0],
                "mip_gap": [0.0],
            }
        )
        experiment = ExperimentResult(
            hourly_dispatch=pd.DataFrame(),
            daily_metrics=pd.DataFrame(),
            case_metrics=case_metrics,
            metadata={"scenario_status": "houston_2020_main_experiment"},
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "run"
            workload_path = Path(temporary_directory) / "workload.csv"
            energy_path = Path(temporary_directory) / "energy.csv"
            arguments = [
                "run_first_version.py",
                "--input",
                str(workload_path),
                "--energy-scenario",
                str(energy_path),
                "--output-dir",
                str(output_dir),
                "--show-scip-log",
            ]
            with (
                patch("sys.argv", arguments),
                patch(
                    "run_first_version.run_houston_2020_experiment",
                    return_value=experiment,
                ) as run_experiment,
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                run_first_version.main()

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


if __name__ == "__main__":
    unittest.main()
