from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from experiments.career.cli import main
from experiments.career.ercot_2025_spot_gpu.config import REPLAY_START_SECONDS
from experiments.career.ercot_2025_spot_gpu.replay import JOB_COLUMNS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENERGY_PATH = PROJECT_ROOT / "data" / "energy" / "ercot_2025_houston_hourly.csv"


class CareerCliTests(unittest.TestCase):
    def test_day_ahead_command_publishes_complete_career_result_tree(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spot_job_path = root / "spot_jobs.csv"
            output_path = root / "career_output"
            pd.DataFrame(
                [
                    {
                        "job_name": "spot_001",
                        "organization": "org",
                        "gpu_model": "model",
                        "cpu_request": 1.0,
                        "gpu_request": 1.0,
                        "worker_num": 1,
                        "submit_time": REPLAY_START_SECONDS,
                        "duration": 3_600,
                        "job_type": "Spot",
                    }
                ],
                columns=JOB_COLUMNS,
            ).to_csv(spot_job_path, index=False)

            exit_code = main(
                [
                    "ercot-2025-spot-gpu-day-ahead",
                    "--energy-path",
                    str(ENERGY_PATH),
                    "--spot-job-path",
                    str(spot_job_path),
                    "--output-dir",
                    str(output_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            for directory in ("inputs", "models", "results", "figures"):
                self.assertTrue((output_path / directory).is_dir())
            for relative_path in (
                "inputs/energy_splits.csv",
                "inputs/spot_replay_720h.csv",
                "inputs/input_manifest.json",
                "models/forecast_validation_metrics.csv",
                "models/test_day_ahead_predictions.csv",
                "results/oracle_actual_hourly_schedule.csv",
                "results/baseline_forecast_hourly_schedule.csv",
                "results/feature_model_forecast_hourly_schedule.csv",
                "results/actual_hourly_settlement.csv",
                "results/decision_metrics.csv",
                "figures/forecast_actual_vs_prediction.png",
                "figures/actual_settlement_comparison.png",
                "run_metadata.json",
            ):
                self.assertTrue((output_path / relative_path).is_file())
            metrics = pd.read_csv(output_path / "results" / "decision_metrics.csv")
            self.assertEqual(
                set(metrics["case"]),
                {"oracle_actual", "baseline_forecast", "feature_model_forecast"},
            )
            oracle = metrics.loc[metrics["case"] == "oracle_actual"].iloc[0]
            self.assertAlmostEqual(oracle["decision_regret_usd"], 0.0)
            published_metadata = (output_path / "run_metadata.json").read_bytes()
            paper_output = PROJECT_ROOT / "outputs" / "paper"
            paper_signature_before = (
                sorted(
                    (str(path.relative_to(paper_output)), path.stat().st_size)
                    for path in paper_output.rglob("*")
                    if path.is_file()
                )
                if paper_output.is_dir()
                else []
            )

            with self.assertRaises(FileNotFoundError):
                main(
                    [
                        "ercot-2025-spot-gpu-day-ahead",
                        "--energy-path",
                        str(root / "missing_energy.csv"),
                        "--spot-job-path",
                        str(spot_job_path),
                        "--output-dir",
                        str(output_path),
                    ]
                )

            self.assertEqual(
                (output_path / "run_metadata.json").read_bytes(), published_metadata
            )
            with self.assertRaisesRegex(ValueError, "outputs/career"):
                main(
                    [
                        "ercot-2025-spot-gpu-day-ahead",
                        "--energy-path",
                        str(root / "missing_energy.csv"),
                        "--spot-job-path",
                        str(spot_job_path),
                        "--output-dir",
                        str(paper_output),
                    ]
                )
            paper_signature_after = (
                sorted(
                    (str(path.relative_to(paper_output)), path.stat().st_size)
                    for path in paper_output.rglob("*")
                    if path.is_file()
                )
                if paper_output.is_dir()
                else []
            )
            self.assertEqual(paper_signature_after, paper_signature_before)


if __name__ == "__main__":
    unittest.main()
