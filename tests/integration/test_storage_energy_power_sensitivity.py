from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from dc_energy_opt.experiments import ExperimentResult
from dc_energy_opt.experiments.storage_energy_power_sensitivity import (
    run_storage_energy_power_sensitivity_experiment,
)


class StorageEnergyPowerSensitivityExperimentTests(unittest.TestCase):
    def test_experiment_publishes_one_project_for_each_grid_cell(
        self,
    ) -> None:
        def fake_main_experiment(**kwargs: object) -> ExperimentResult:
            params = kwargs["params"]
            output_dir = Path(kwargs["output_dir"])
            results_dir = output_dir / "results"
            results_dir.mkdir(parents=True)
            storage_cost = (
                90.0
                - float(params.battery_energy_mwh)
                - float(params.battery_charge_power_mw)
            )
            joint_cost = storage_cost - 6.0
            case_metrics = pd.DataFrame(
                {
                    "case": [
                        "renewables_only",
                        "renewables_shift",
                        "renewables_storage",
                        "joint",
                    ],
                    "status": ["optimal"] * 4,
                    "operating_cost_cny": [
                        100.0,
                        92.0,
                        storage_cost,
                        joint_cost,
                    ],
                }
            )
            case_metrics.to_csv(results_dir / "case_metrics.csv", index=False)
            return ExperimentResult(
                hourly_dispatch=pd.DataFrame(),
                daily_metrics=pd.DataFrame(),
                case_metrics=case_metrics,
                metadata={},
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "storage_energy_power"
            workload_path = root / "workload.csv"
            energy_path = root / "energy.csv"
            workload_path.write_text("workload", encoding="utf-8")
            energy_path.write_text("energy", encoding="utf-8")

            with patch(
                "dc_energy_opt.experiments.storage_energy_power_sensitivity."
                "run_houston_2020_experiment",
                side_effect=fake_main_experiment,
            ):
                result = run_storage_energy_power_sensitivity_experiment(
                    workload_data=workload_path,
                    energy_data=energy_path,
                    output_dir=output_dir,
                )

            self.assertEqual(len(result.metrics), 9)
            self.assertEqual(
                len(list((output_dir / "experiments").iterdir())),
                9,
            )
            self.assertTrue(
                (
                    output_dir
                    / "results"
                    / "storage_energy_power_sensitivity.csv"
                ).is_file()
            )
            self.assertEqual(
                sorted(path.name for path in (output_dir / "figures").iterdir()),
                [
                    "storage_energy_power_joint_cost.png",
                    "storage_energy_power_shift_effect.png",
                ],
            )
            self.assertTrue((output_dir / "analysis.md").is_file())


if __name__ == "__main__":
    unittest.main()
