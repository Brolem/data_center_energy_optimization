from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from dc_energy_opt.experiments.houston_2020 import (
    run_houston_2020_experiment,
)
from dc_energy_opt.reporting import PLOT_FILENAMES


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKLOAD_PATH = PROJECT_ROOT / "data" / "workload" / (
    "google_2019_28d_5min.csv"
)
ENERGY_PATH = PROJECT_ROOT / "data" / "energy" / (
    "houston_2020_may_hourly.csv"
)
CASE_ORDER = [
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
]


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class Houston2020ExperimentTests(unittest.TestCase):
    def assert_preserved_without_transactions(
        self,
        output_dir: Path,
        before: dict[str, str],
    ) -> None:
        self.assertEqual(_tree_hashes(output_dir), before)
        self.assertEqual(
            list(output_dir.parent.glob(f".{output_dir.name}-staging-*")),
            [],
        )
        self.assertEqual(
            list(output_dir.parent.glob(f".{output_dir.name}-backup-*")),
            [],
        )

    def test_full_experiment_publishes_exact_tree_and_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "houston_2020_main"

            experiment = run_houston_2020_experiment(
                workload_data=WORKLOAD_PATH,
                energy_data=ENERGY_PATH,
                output_dir=output_dir,
            )

            self.assertEqual(
                sorted(path.name for path in output_dir.iterdir()),
                [
                    "figures",
                    "inputs",
                    "models",
                    "results",
                    "run_metadata.json",
                ],
            )
            self.assertEqual(
                sorted(path.name for path in (output_dir / "inputs").iterdir()),
                [
                    "aligned_28d_hourly.csv",
                    "google_2019_28d_5min.csv",
                    "houston_2020_may_hourly.csv",
                ],
            )
            self.assertEqual(
                sorted(
                    path.name for path in (output_dir / "results").iterdir()
                ),
                [
                    "case_metrics.csv",
                    "daily_metrics.csv",
                    "hourly_dispatch.csv",
                    "hourly_workload.csv",
                ],
            )
            self.assertEqual(
                sorted(path.name for path in (output_dir / "figures").iterdir()),
                sorted(PLOT_FILENAMES),
            )

            self.assertEqual(len(experiment.hourly_dispatch), 2700)
            self.assertEqual(len(experiment.daily_metrics), 112)
            self.assertEqual(
                experiment.case_metrics["case"].tolist(),
                CASE_ORDER,
            )
            self.assertEqual(
                experiment.hourly_dispatch.groupby(
                    "case", sort=False
                ).size().tolist(),
                [675, 675, 675, 675],
            )
            self.assertEqual(
                experiment.daily_metrics.groupby(
                    "case", sort=False
                ).size().tolist(),
                [28, 28, 28, 28],
            )

            lp_files = list((output_dir / "models").rglob("*.lp"))
            self.assertEqual(len(lp_files), 232)
            self.assertEqual(
                list((output_dir / "models").glob("*.lp")),
                [],
            )
            expected_windows = {
                "renewables_only": {
                    *(f"day_{day:02d}" for day in range(1, 29)),
                },
                "renewables_shift": {
                    "warmup",
                    *(f"day_{day:02d}" for day in range(1, 29)),
                },
                "renewables_storage": {
                    "soc_coordination",
                    *(f"day_{day:02d}" for day in range(1, 29)),
                },
                "joint": {
                    "warmup",
                    "soc_coordination",
                    *(f"day_{day:02d}" for day in range(1, 29)),
                },
            }
            for case_name, windows in expected_windows.items():
                case_dir = output_dir / "models" / case_name
                self.assertEqual(
                    {path.name for path in case_dir.iterdir()},
                    windows,
                )
                for window_dir in case_dir.iterdir():
                    self.assertEqual(
                        sorted(path.name for path in window_dir.iterdir()),
                        ["stage_1_cost.lp", "stage_2_delay.lp"],
                    )

            for source_path, snapshot_name in (
                (WORKLOAD_PATH, "google_2019_28d_5min.csv"),
                (ENERGY_PATH, "houston_2020_may_hourly.csv"),
            ):
                self.assertEqual(
                    hashlib.sha256(source_path.read_bytes()).digest(),
                    hashlib.sha256(
                        (output_dir / "inputs" / snapshot_name).read_bytes()
                    ).digest(),
                )
            self.assertEqual(
                len(
                    pd.read_csv(
                        output_dir / "inputs" / "aligned_28d_hourly.csv"
                    )
                ),
                672,
            )
            self.assertEqual(
                len(
                    pd.read_csv(
                        output_dir / "results" / "hourly_workload.csv"
                    )
                ),
                672,
            )

            for column in (
                "analysis_operating_cost_cny",
                "settlement_tail_operating_cost_cny",
                "final_stored_energy_mwh",
                "soc_cycle_error",
                "operating_cost_savings_vs_renewables_only_pct",
            ):
                self.assertIn(column, experiment.case_metrics.columns)
            self.assertTrue(
                (
                    experiment.case_metrics["operating_cost_cny"]
                    - experiment.case_metrics[
                        "analysis_operating_cost_cny"
                    ]
                    - experiment.case_metrics[
                        "settlement_tail_operating_cost_cny"
                    ]
                ).abs().le(1e-7).all()
            )
            storage_rows = experiment.case_metrics[
                experiment.case_metrics["storage_enabled"]
            ]
            self.assertTrue(
                storage_rows["final_stored_energy_mwh"].sub(1.0).abs().le(
                    1e-7
                ).all()
            )
            self.assertAlmostEqual(
                float(
                    experiment.case_metrics.loc[
                        experiment.case_metrics["case"]
                        == "renewables_only",
                        "operating_cost_savings_vs_renewables_only_pct",
                    ].iloc[0]
                ),
                0.0,
            )

            with (output_dir / "run_metadata.json").open(
                encoding="utf-8"
            ) as file:
                written_metadata = json.load(file)
            self.assertEqual(experiment.metadata, written_metadata)
            self.assertEqual(
                experiment.metadata["model_type"],
                "rolling_24_plus_3_deterministic_day_ahead",
            )
            self.assertEqual(
                experiment.metadata["formal_cases"],
                CASE_ORDER,
            )
            self.assertEqual(
                experiment.metadata["cost_baseline_case"],
                "renewables_only",
            )

    def test_invalid_energy_data_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            output_dir = parent / "run"
            output_dir.mkdir()
            (output_dir / "old.bin").write_bytes(b"old\x00\xff")
            before = _tree_hashes(output_dir)
            invalid_energy = parent / "invalid_energy.csv"
            pd.read_csv(ENERGY_PATH).iloc[:-1].to_csv(
                invalid_energy,
                index=False,
            )

            with self.assertRaises(ValueError):
                run_houston_2020_experiment(
                    workload_data=WORKLOAD_PATH,
                    energy_data=invalid_energy,
                    output_dir=output_dir,
                )

            self.assert_preserved_without_transactions(output_dir, before)

    def test_first_csv_failure_preserves_output_and_cleans_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            output_dir = parent / "run"
            output_dir.mkdir()
            (output_dir / "old.bin").write_bytes(b"old\x00\xff")
            before = _tree_hashes(output_dir)

            with (
                patch.object(
                    pd.DataFrame,
                    "to_csv",
                    side_effect=OSError("injected first CSV failure"),
                ),
                self.assertRaisesRegex(
                    OSError, "injected first CSV failure"
                ),
            ):
                run_houston_2020_experiment(
                    workload_data=WORKLOAD_PATH,
                    energy_data=ENERGY_PATH,
                    output_dir=output_dir,
                )

            self.assert_preserved_without_transactions(output_dir, before)

    def test_solver_failure_preserves_output_and_cleans_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            output_dir = parent / "run"
            output_dir.mkdir()
            (output_dir / "old.bin").write_bytes(b"old\x00\xff")
            before = _tree_hashes(output_dir)

            with (
                patch(
                    "dc_energy_opt.experiments.houston_2020.run_rolling_day_ahead",
                    side_effect=RuntimeError("injected solver failure"),
                ),
                self.assertRaisesRegex(
                    RuntimeError, "injected solver failure"
                ),
            ):
                run_houston_2020_experiment(
                    workload_data=WORKLOAD_PATH,
                    energy_data=ENERGY_PATH,
                    output_dir=output_dir,
                )

            self.assert_preserved_without_transactions(output_dir, before)

    def test_plot_failure_preserves_output_and_cleans_staging(self) -> None:
        def fake_solve(**kwargs: object) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
            case_name = str(kwargs["case_name"])
            return (
                pd.DataFrame({"case": [case_name]}),
                {"case": case_name, "operating_cost_cny": 1.0},
                pd.DataFrame({"case": [case_name]}),
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            output_dir = parent / "run"
            output_dir.mkdir()
            (output_dir / "old.bin").write_bytes(b"old\x00\xff")
            before = _tree_hashes(output_dir)

            with (
                patch(
                    "dc_energy_opt.experiments.houston_2020.run_rolling_day_ahead",
                    side_effect=fake_solve,
                ),
                patch(
                    "dc_energy_opt.experiments.houston_2020.make_plots",
                    side_effect=OSError("injected plot failure"),
                ),
                self.assertRaisesRegex(OSError, "injected plot failure"),
            ):
                run_houston_2020_experiment(
                    workload_data=WORKLOAD_PATH,
                    energy_data=ENERGY_PATH,
                    output_dir=output_dir,
                )

            self.assert_preserved_without_transactions(output_dir, before)


if __name__ == "__main__":
    unittest.main()
