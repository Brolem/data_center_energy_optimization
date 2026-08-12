from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from experiments.paper.houston_2020 import ExperimentResult
from experiments.paper.houston_2020.sensitivity.storage_scale import (
    run_storage_scale_sensitivity_experiment,
)


class StorageScaleSensitivityExperimentTests(unittest.TestCase):
    def test_experiment_publishes_one_project_per_storage_scale(self) -> None:
        def fake_main_experiment(**kwargs: object) -> ExperimentResult:
            params = kwargs["params"]
            output_dir = Path(kwargs["output_dir"])
            results_dir = output_dir / "results"
            results_dir.mkdir(parents=True)
            storage_cost = 90.0 - float(params.battery_energy_mwh)
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
            output_dir = root / "storage_scale"
            workload_path = root / "workload.csv"
            energy_path = root / "energy.csv"
            workload_path.write_text("workload", encoding="utf-8")
            energy_path.write_text("energy", encoding="utf-8")
            with patch(
                "experiments.paper.houston_2020.sensitivity.storage_scale."
                "run_houston_2020_experiment",
                side_effect=fake_main_experiment,
            ):
                result = run_storage_scale_sensitivity_experiment(
                    workload_data=workload_path,
                    energy_data=energy_path,
                    output_dir=output_dir,
                )

            self.assertEqual(len(result.metrics), 3)
            for scale_name in (
                "energy_2p0_mwh_power_0p5_mw",
                "energy_4p0_mwh_power_1p0_mw",
                "energy_6p0_mwh_power_1p5_mw",
            ):
                self.assertTrue(
                    (
                        output_dir
                        / "experiments"
                        / scale_name
                        / "results"
                        / "case_metrics.csv"
                    ).is_file()
                )
            self.assertTrue(
                (
                    output_dir
                    / "results"
                    / "storage_scale_sensitivity.csv"
                ).is_file()
            )
            self.assertTrue(
                (
                    output_dir
                    / "figures"
                    / "storage_scale_total_cost.png"
                ).is_file()
            )
            self.assertTrue(
                (
                    output_dir
                    / "figures"
                    / "storage_scale_shift_value.png"
                ).is_file()
            )
            self.assertTrue((output_dir / "analysis.md").is_file())
            self.assertRegex(
                str(result.metadata["run_utc"]),
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            )
            self.assertRegex(
                str(result.metadata["git_commit"]),
                r"^[0-9a-f]{40}$",
            )
            self.assertEqual(
                set(result.metadata["input_sha256"]),
                {"workload", "energy"},
            )


if __name__ == "__main__":
    unittest.main()
