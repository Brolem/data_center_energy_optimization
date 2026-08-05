from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
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

    def assert_input_output_collision_rejected_before_work(
        self,
        *,
        workload_data: Path,
        energy_data: Path,
        output_dir: Path,
        input_identifier: str,
        input_path: Path,
    ) -> None:
        with (
            patch(
                "dc_energy_opt.experiments.houston_2020.load_and_prepare",
                side_effect=RuntimeError("data loading reached"),
            ) as load_workload,
            patch(
                "dc_energy_opt.experiments.houston_2020."
                "load_houston_energy_scenario",
                side_effect=RuntimeError("energy loading reached"),
            ) as load_energy,
            patch(
                "dc_energy_opt.experiments.houston_2020."
                "run_rolling_day_ahead",
                side_effect=RuntimeError("solver reached"),
            ) as solve,
            patch(
                "dc_energy_opt.experiments.houston_2020."
                "staged_run_directory",
                side_effect=RuntimeError("staging reached"),
            ) as stage,
            self.assertRaises(ValueError) as context,
        ):
            run_houston_2020_experiment(
                workload_data=workload_data,
                energy_data=energy_data,
                output_dir=output_dir,
            )

        message = str(context.exception)
        self.assertIn(input_identifier, message)
        self.assertIn(str(input_path.resolve(strict=False)), message)
        self.assertIn("output_dir", message)
        self.assertIn(str(output_dir.resolve(strict=False)), message)
        load_workload.assert_not_called()
        load_energy.assert_not_called()
        solve.assert_not_called()
        stage.assert_not_called()
        self.assertEqual(
            list(output_dir.parent.glob(f".{output_dir.name}-staging-*")),
            [],
        )
        self.assertEqual(
            list(output_dir.parent.glob(f".{output_dir.name}-backup-*")),
            [],
        )

    def test_workload_inside_output_root_is_rejected_before_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            output_dir = parent / "run"
            output_dir.mkdir()
            workload_data = output_dir / "workload.csv"
            workload_bytes = b"workload\x00\xff"
            workload_data.write_bytes(workload_bytes)
            energy_data = parent / "energy.csv"
            energy_data.write_bytes(b"energy")
            before = _tree_hashes(output_dir)

            self.assert_input_output_collision_rejected_before_work(
                workload_data=workload_data,
                energy_data=energy_data,
                output_dir=output_dir,
                input_identifier="workload_data",
                input_path=workload_data,
            )

            self.assertEqual(_tree_hashes(output_dir), before)
            self.assertEqual(workload_data.read_bytes(), workload_bytes)

    def test_energy_inside_output_inputs_is_rejected_before_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            output_dir = parent / "run"
            energy_data = output_dir / "inputs" / "energy.csv"
            energy_data.parent.mkdir(parents=True)
            energy_bytes = b"energy\x00\xff"
            energy_data.write_bytes(energy_bytes)
            workload_data = parent / "workload.csv"
            workload_data.write_bytes(b"workload")
            before = _tree_hashes(output_dir)

            self.assert_input_output_collision_rejected_before_work(
                workload_data=workload_data,
                energy_data=energy_data,
                output_dir=output_dir,
                input_identifier="energy_data",
                input_path=energy_data,
            )

            self.assertEqual(_tree_hashes(output_dir), before)
            self.assertEqual(energy_data.read_bytes(), energy_bytes)

    def test_input_equal_to_file_output_is_rejected_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            output_dir = parent / "run.csv"
            original_bytes = b"input and output\x00\xff"
            output_dir.write_bytes(original_bytes)
            energy_data = parent / "energy.csv"
            energy_data.write_bytes(b"energy")

            self.assert_input_output_collision_rejected_before_work(
                workload_data=output_dir,
                energy_data=energy_data,
                output_dir=output_dir,
                input_identifier="workload_data",
                input_path=output_dir,
            )

            self.assertTrue(output_dir.is_file())
            self.assertEqual(output_dir.read_bytes(), original_bytes)

    def test_relative_input_paths_remain_relative_in_metadata(self) -> None:
        hourly = pd.DataFrame(
            {
                "day": np.repeat(np.arange(1, 29), 24),
                "hour": np.tile(np.arange(24), 28),
                "avg_cpu": np.full(672, 0.5),
            }
        )
        energy_scenario = pd.DataFrame(
            {
                "timestamp_lst": pd.date_range(
                    "2020-04-30 00:00:00",
                    periods=699,
                    freq="h",
                ),
                "solar_available_mw": np.zeros(699),
                "wind_available_mw": np.zeros(699),
                "tou_period": ["flat"] * 699,
                "electricity_price_cny_per_kwh": np.full(699, 0.4489),
            }
        )

        def fake_solve(
            **kwargs: object,
        ) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
            case_name = str(kwargs["case_name"])
            return (
                pd.DataFrame({"case": [case_name]}),
                {"case": case_name, "operating_cost_cny": 1.0},
                pd.DataFrame({"case": [case_name]}),
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            previous_cwd = Path.cwd()
            try:
                os.chdir(temporary_path)
                workload_data = Path("workload.csv")
                energy_data = Path("energy.csv")
                output_dir = Path("outputs/run")
                workload_data.write_bytes(b"workload")
                energy_data.write_bytes(b"energy")
                with (
                    patch(
                        "dc_energy_opt.experiments.houston_2020."
                        "load_and_prepare",
                        return_value=(pd.DataFrame({"raw": [1]}), hourly, 8, 28),
                    ) as load_workload,
                    patch(
                        "dc_energy_opt.experiments.houston_2020."
                        "load_houston_energy_scenario",
                        return_value=energy_scenario,
                    ) as load_energy,
                    patch(
                        "dc_energy_opt.experiments.houston_2020."
                        "run_rolling_day_ahead",
                        side_effect=fake_solve,
                    ),
                    patch(
                        "dc_energy_opt.experiments.houston_2020.make_plots"
                    ),
                    patch(
                        "dc_energy_opt.experiments.houston_2020."
                        "make_task_delay_objective_plot"
                    ),
                    patch(
                        "dc_energy_opt.experiments.houston_2020."
                        "software_versions",
                        return_value={},
                    ),
                ):
                    experiment = run_houston_2020_experiment(
                        workload_data=workload_data,
                        energy_data=energy_data,
                        output_dir=output_dir,
                    )

                load_workload.assert_called_once()
                loaded_workload_path = Path(
                    load_workload.call_args.args[0]
                )
                loaded_energy_path = Path(load_energy.call_args.args[0])
                self.assertEqual(
                    loaded_workload_path.name,
                    "google_2019_28d_5min.csv",
                )
                self.assertEqual(
                    loaded_energy_path.name,
                    "houston_2020_may_hourly.csv",
                )
                self.assertEqual(loaded_workload_path.parent.name, "inputs")
                self.assertEqual(loaded_energy_path.parent.name, "inputs")
                metadata = experiment.metadata
                self.assertEqual(metadata["input_file"], "workload.csv")
                self.assertEqual(
                    metadata["energy_scenario_file"],
                    "energy.csv",
                )
                self.assertEqual(
                    metadata["renewable_data_source"]["file"],
                    "energy.csv",
                )
                self.assertEqual(
                    metadata["electricity_price_source"]["file"],
                    "energy.csv",
                )
                absolute_prefix = str(temporary_path.resolve(strict=False))
                for metadata_path in (
                    metadata["input_file"],
                    metadata["energy_scenario_file"],
                    metadata["renewable_data_source"]["file"],
                    metadata["electricity_price_source"]["file"],
                ):
                    self.assertNotIn(absolute_prefix, metadata_path)
            finally:
                os.chdir(previous_cwd)

    def test_model_and_published_input_use_same_immutable_snapshot(self) -> None:
        hourly = pd.DataFrame(
            {
                "day": np.repeat(np.arange(1, 29), 24),
                "hour": np.tile(np.arange(24), 28),
                "avg_cpu": np.full(672, 0.5),
            }
        )
        energy_scenario = pd.DataFrame(
            {
                "timestamp_lst": pd.date_range(
                    "2020-04-30 00:00:00",
                    periods=699,
                    freq="h",
                ),
                "solar_available_mw": np.zeros(699),
                "wind_available_mw": np.zeros(699),
                "tou_period": ["flat"] * 699,
                "electricity_price_cny_per_kwh": np.full(699, 0.4489),
            }
        )

        def fake_solve(
            **kwargs: object,
        ) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
            case_name = str(kwargs["case_name"])
            return (
                pd.DataFrame({"case": [case_name]}),
                {"case": case_name, "operating_cost_cny": 1.0},
                pd.DataFrame({"case": [case_name]}),
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            workload_data = parent / "workload.csv"
            energy_data = parent / "energy.csv"
            output_dir = parent / "run"
            workload_before = b"workload before\x00\xff"
            workload_after = b"workload after\x00\xff"
            energy_before = b"energy before\x00\xff"
            workload_data.write_bytes(workload_before)
            energy_data.write_bytes(energy_before)
            workload_source = workload_data.resolve(strict=False)
            loaded_workload_bytes: list[bytes] = []
            real_copyfile = shutil.copyfile

            def load_workload(path: Path) -> tuple:
                source_path = Path(path)
                loaded_workload_bytes.append(source_path.read_bytes())
                if source_path.resolve(strict=False) == workload_source:
                    workload_data.write_bytes(workload_after)
                return pd.DataFrame({"raw": [1]}), hourly, 8, 28

            def copy_then_mutate_source(
                source: Path,
                target: Path,
            ) -> str:
                copied = real_copyfile(source, target)
                if Path(source).resolve(strict=False) == workload_source:
                    workload_data.write_bytes(workload_after)
                return copied

            with (
                patch(
                    "dc_energy_opt.experiments.houston_2020."
                    "load_and_prepare",
                    side_effect=load_workload,
                ),
                patch(
                    "dc_energy_opt.experiments.houston_2020."
                    "load_houston_energy_scenario",
                    return_value=energy_scenario,
                ),
                patch(
                    "dc_energy_opt.experiments.houston_2020."
                    "run_rolling_day_ahead",
                    side_effect=fake_solve,
                ),
                patch(
                    "dc_energy_opt.experiments.houston_2020.shutil.copyfile",
                    side_effect=copy_then_mutate_source,
                ),
                patch(
                    "dc_energy_opt.experiments.houston_2020.make_plots"
                ),
                patch(
                    "dc_energy_opt.experiments.houston_2020."
                    "make_task_delay_objective_plot"
                ),
                patch(
                    "dc_energy_opt.experiments.houston_2020."
                    "software_versions",
                    return_value={},
                ),
            ):
                run_houston_2020_experiment(
                    workload_data=workload_data,
                    energy_data=energy_data,
                    output_dir=output_dir,
                )

            self.assertEqual(loaded_workload_bytes, [workload_before])
            self.assertEqual(workload_data.read_bytes(), workload_after)
            published_workload = (
                output_dir / "inputs" / "google_2019_28d_5min.csv"
            ).read_bytes()
            self.assertEqual(
                published_workload,
                workload_before,
                "loaded_before_but_published_after",
            )
            self.assertEqual(
                (
                    output_dir / "inputs" / "houston_2020_may_hourly.csv"
                ).read_bytes(),
                energy_before,
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
                sorted([*PLOT_FILENAMES, "task_delay_objectives.png"]),
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
            self.assertIn(
                "primary_task_delay_cpu_hours",
                experiment.daily_metrics.columns,
            )
            self.assertIn(
                "secondary_task_delay_cpu_hours",
                experiment.daily_metrics.columns,
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
