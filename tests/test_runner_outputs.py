from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import run_first_version
import scip_first_version.reporting as reporting
from run_first_version import (
    LEGACY_GENERATED_FILENAMES,
    _archive_source_files,
    _generated_output_names,
    _publish_staged_outputs,
    _validate_archive_targets,
    main,
    parse_args,
)
from scip_first_version.config import Parameters
from scip_first_version.reporting import LEGACY_PLOT_FILENAMES, make_plots


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = Path("data/instance_usage_grouped_300_seconds_month.csv")
SCENARIO_PATH = Path(
    "data/houston_2020_main_experiment_energy_scenario.csv"
)
CASE_ORDER = [
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
]
PLOT_FILES = [
    "day_ahead_power_results.png",
    "compute_scheduling_results.png",
    "battery_operation_results.png",
    "renewable_dispatch_results.png",
    "operating_cost_comparison.png",
]
PLOT_SIZES = {
    "day_ahead_power_results.png": (1800, 1120),
    "compute_scheduling_results.png": (1800, 820),
    "battery_operation_results.png": (1800, 1120),
    "renewable_dispatch_results.png": (1800, 820),
    "operating_cost_comparison.png": (1800, 1050),
}
MIN_SERIES_PIXELS = 100


def _flat_file_hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.iterdir()
        if path.is_file()
    }


def _zero_plot_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly_rows = []
    for case_name in CASE_ORDER:
        for hour in range(27):
            hourly_rows.append(
                {
                    "case": case_name,
                    "hour": hour,
                    "period_role": (
                        "analysis" if hour < 24 else "settlement_tail"
                    ),
                    "cpu_arrival_pu": 0.0,
                    "cpu_scheduled_pu": 0.0,
                    "it_power_mw": 0.0,
                    "dc_power_mw": 0.0,
                    "grid_power_mw": 0.0,
                    "solar_available_mw": 0.0,
                    "solar_used_mw": 0.0,
                    "solar_curtailed_mw": 0.0,
                    "wind_available_mw": 0.0,
                    "wind_used_mw": 0.0,
                    "wind_curtailed_mw": 0.0,
                    "charge_mw": 0.0,
                    "discharge_mw": 0.0,
                    "soc_start": 0.5,
                    "soc_end": 0.5,
                    "electricity_price_cny_per_kwh": 0.0,
                    "hourly_grid_purchase_cost_cny": 0.0,
                    "hourly_solar_om_cost_cny": 0.0,
                    "hourly_wind_om_cost_cny": 0.0,
                    "hourly_battery_om_cost_cny": 0.0,
                    "hourly_battery_degradation_cost_cny": 0.0,
                    "hourly_operating_cost_cny": 0.0,
                }
            )
    metrics = pd.DataFrame(
        {
            "case": CASE_ORDER,
            "grid_purchase_cost_cny": 0.0,
            "solar_om_cost_cny": 0.0,
            "wind_om_cost_cny": 0.0,
            "battery_om_cost_cny": 0.0,
            "battery_degradation_cost_cny": 0.0,
            "operating_cost_cny": 0.0,
        }
    )
    return pd.DataFrame(hourly_rows), metrics


def _count_exact_color(
    image: Image.Image,
    color: tuple[int, int, int],
    box: tuple[int, int, int, int] | None = None,
) -> int:
    target = image.crop(box) if box is not None else image
    pixels = np.asarray(target)
    return int(np.all(pixels == np.asarray(color), axis=2).sum())


class RunnerOutputTests(unittest.TestCase):
    def assert_plot_has_color(
        self,
        image: Image.Image,
        color: tuple[int, int, int],
        label: str,
        *,
        box: tuple[int, int, int, int] | None = None,
    ) -> None:
        self.assertGreaterEqual(
            _count_exact_color(image, color, box),
            MIN_SERIES_PIXELS,
            label,
        )

    def test_cli_defaults_target_deterministic_day_ahead_inputs(self) -> None:
        with patch("sys.argv", ["run_first_version.py"]):
            arguments = parse_args()

        self.assertIsInstance(arguments.input, Path)
        self.assertIsInstance(arguments.energy_scenario, Path)
        self.assertIsInstance(arguments.output_dir, Path)
        self.assertEqual(arguments.input, INPUT_PATH)
        self.assertEqual(
            arguments.energy_scenario,
            SCENARIO_PATH,
        )
        self.assertEqual(
            arguments.output_dir,
            Path("outputs/day_ahead_deterministic"),
        )
        self.assertFalse(arguments.show_scip_log)

    def test_source_archive_skips_copy_when_source_is_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory).resolve()
            source_path = output_dir / "source.csv"
            original_content = "hour,value\n0,1\n"
            source_path.write_text(original_content, encoding="utf-8")

            with patch("run_first_version.shutil.copy2") as copy2:
                _archive_source_files([source_path], output_dir)

            copy2.assert_not_called()
            self.assertEqual(
                source_path.read_text(encoding="utf-8"),
                original_content,
            )

    def test_cli_rejects_colliding_source_basenames_before_solving(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            scenario_dir = root / "scenario"
            input_dir.mkdir()
            scenario_dir.mkdir()
            input_path = input_dir / "shared.csv"
            scenario_path = scenario_dir / "shared.csv"
            input_path.write_bytes(INPUT_PATH.read_bytes())
            scenario_path.write_bytes(SCENARIO_PATH.read_bytes())
            arguments = [
                "run_first_version.py",
                "--input",
                str(input_path),
                "--energy-scenario",
                str(scenario_path),
                "--output-dir",
                str(root / "outputs"),
            ]

            with (
                patch("sys.argv", arguments),
                patch("run_first_version.run_rolling_day_ahead") as solve,
                self.assertRaises(ValueError) as context,
            ):
                main()

            solve.assert_not_called()
            message = str(context.exception)
            self.assertIn("shared.csv", message)
            self.assertIn(str(input_path.resolve()), message)
            self.assertIn(str(scenario_path.resolve()), message)
            self.assertFalse((root / "outputs").exists())

    @unittest.skipUnless(os.name == "nt", "requires Windows path semantics")
    def test_source_archive_rejects_case_only_target_collision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_dir = root / "first"
            second_dir = root / "second"
            output_dir = root / "outputs"
            first_dir.mkdir()
            second_dir.mkdir()
            output_dir.mkdir()
            first_source = first_dir / "Shared.csv"
            second_source = second_dir / "shared.csv"
            first_source.write_text("first\n", encoding="utf-8")
            second_source.write_text("second\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                _archive_source_files(
                    [first_source, second_source],
                    output_dir,
                )

            self.assertEqual(list(output_dir.iterdir()), [])

    def test_reserved_output_names_reject_legal_source_archives(self) -> None:
        expected_generated_names = {
            "all_days_hourly.csv",
            "model_input_28_days.csv",
            "hourly_case_results.csv",
            "daily_case_metrics.csv",
            "case_metrics.csv",
            "run_metadata.json",
            *(
                f"{case}_day_{day:02d}_{stage}.lp"
                for case in CASE_ORDER
                for day in range(1, 29)
                for stage in ("primary", "secondary")
            ),
            *(
                f"{case}_warmup_{stage}.lp"
                for case in ("renewables_shift", "joint")
                for stage in ("primary", "secondary")
            ),
            *(
                f"{case}_soc_coordination_{stage}.lp"
                for case in ("renewables_storage", "joint")
                for stage in ("primary", "secondary")
            ),
            *PLOT_FILES,
        }
        expected_reserved_names = expected_generated_names | set(
            LEGACY_GENERATED_FILENAMES
        )
        self.assertEqual(len(expected_reserved_names), 257)
        self.assertEqual(
            _generated_output_names(),
            expected_generated_names,
        )
        self.assertEqual(
            run_first_version._reserved_output_names(),
            expected_reserved_names,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "sources"
            output_dir = root / "outputs"
            source_dir.mkdir()
            valid_source_content = b"source\n"
            for reserved_name in sorted(expected_reserved_names):
                source_path = source_dir / reserved_name
                source_path.write_bytes(valid_source_content)
                with self.subTest(reserved_name=reserved_name):
                    with self.assertRaises(ValueError) as context:
                        _validate_archive_targets(
                            [source_path],
                            output_dir,
                        )
                    message = str(context.exception)
                    self.assertIn(str(source_path.resolve()), message)
                    self.assertIn(reserved_name, message)

    def test_legacy_named_input_in_output_dir_is_rejected_unchanged(
        self,
    ) -> None:
        valid_google_input = INPUT_PATH.read_bytes()
        for legacy_name in LEGACY_PLOT_FILENAMES:
            with self.subTest(legacy_name=legacy_name):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    output_dir = root / "outputs"
                    output_dir.mkdir()
                    input_path = output_dir / legacy_name
                    input_path.write_bytes(valid_google_input)
                    (output_dir / "case_metrics.csv").write_bytes(
                        b"old metrics\n"
                    )
                    (output_dir / "unknown-sentinel.bin").write_bytes(
                        b"unknown sentinel\x00\xff"
                    )
                    before = _flat_file_hashes(output_dir)
                    arguments = [
                        "run_first_version.py",
                        "--input",
                        str(input_path),
                        "--energy-scenario",
                        str(SCENARIO_PATH),
                        "--output-dir",
                        str(output_dir),
                    ]

                    with (
                        patch("sys.argv", arguments),
                        patch(
                            "run_first_version.run_rolling_day_ahead"
                        ) as solve,
                        self.assertRaises(ValueError) as context,
                    ):
                        main()

                    solve.assert_not_called()
                    message = str(context.exception)
                    self.assertIn(str(input_path.resolve()), message)
                    self.assertIn(legacy_name, message)
                    self.assertEqual(_flat_file_hashes(output_dir), before)
                    self.assertTrue(input_path.is_file())
                    self.assertEqual(
                        hashlib.sha256(input_path.read_bytes()).digest(),
                        hashlib.sha256(valid_google_input).digest(),
                    )
                    self.assertEqual(
                        list(root.glob(".day-ahead-staging-*")),
                        [],
                    )
                    self.assertEqual(
                        list(root.glob(".day-ahead-backup-*")),
                        [],
                    )

    def test_reserved_name_input_in_output_dir_is_rejected_unchanged(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "outputs"
            output_dir.mkdir()
            input_path = output_dir / "case_metrics.csv"
            input_path.write_bytes(INPUT_PATH.read_bytes())
            (output_dir / "hourly_case_results.csv").write_bytes(
                b"old hourly results\n"
            )
            (output_dir / "unknown-sentinel.bin").write_bytes(
                b"unknown sentinel\x00\xff"
            )
            before = _flat_file_hashes(output_dir)
            arguments = [
                "run_first_version.py",
                "--input",
                str(input_path),
                "--energy-scenario",
                str(SCENARIO_PATH),
                "--output-dir",
                str(output_dir),
            ]

            with (
                patch("sys.argv", arguments),
                patch("run_first_version.run_rolling_day_ahead") as solve,
                self.assertRaises(ValueError) as context,
            ):
                main()

            solve.assert_not_called()
            message = str(context.exception)
            self.assertIn(str(input_path.resolve()), message)
            self.assertIn("case_metrics.csv", message)
            self.assertEqual(_flat_file_hashes(output_dir), before)
            self.assertEqual(list(root.glob(".day-ahead-staging-*")), [])
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    def test_all_days_hourly_named_input_is_rejected_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "outputs"
            output_dir.mkdir()
            input_path = output_dir / "all_days_hourly.csv"
            input_path.write_bytes(INPUT_PATH.read_bytes())
            (output_dir / "case_metrics.csv").write_bytes(b"old metrics\n")
            (output_dir / "unknown-sentinel.bin").write_bytes(
                b"unknown sentinel\x00\xff"
            )
            before = _flat_file_hashes(output_dir)
            arguments = [
                "run_first_version.py",
                "--input",
                str(input_path),
                "--energy-scenario",
                str(SCENARIO_PATH),
                "--output-dir",
                str(output_dir),
            ]

            with (
                patch("sys.argv", arguments),
                patch("run_first_version.run_rolling_day_ahead") as solve,
                self.assertRaises(ValueError) as context,
            ):
                main()

            solve.assert_not_called()
            message = str(context.exception)
            self.assertIn(str(input_path.resolve()), message)
            self.assertIn("all_days_hourly.csv", message)
            self.assertEqual(_flat_file_hashes(output_dir), before)
            self.assertEqual(list(root.glob(".day-ahead-staging-*")), [])
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    def test_invalid_energy_scenario_preserves_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            invalid_scenario = root / "invalid_scenario.csv"
            pd.read_csv(SCENARIO_PATH).iloc[:-1].to_csv(
                invalid_scenario,
                index=False,
            )
            output_dir = root / "outputs"
            output_dir.mkdir()
            for filename, content in {
                "case_metrics.csv": b"old metrics\n",
                INPUT_PATH.name: b"old archived input\n",
                "unknown-sentinel.bin": b"unknown sentinel\x00\xff",
            }.items():
                (output_dir / filename).write_bytes(content)
            before = _flat_file_hashes(output_dir)
            arguments = [
                "run_first_version.py",
                "--input",
                str(INPUT_PATH),
                "--energy-scenario",
                str(invalid_scenario),
                "--output-dir",
                str(output_dir),
            ]

            with (
                patch("sys.argv", arguments),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
                self.assertRaises(ValueError),
            ):
                main()

            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(_flat_file_hashes(output_dir), before)

    def test_first_csv_failure_immediately_cleans_staging_with_traceback(
        self,
    ) -> None:
        retained_exception = None
        retained_traceback = None
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "outputs"
            output_dir.mkdir()
            (output_dir / "case_metrics.csv").write_bytes(b"old metrics\n")
            (output_dir / "unknown-sentinel.bin").write_bytes(
                b"unknown sentinel\x00\xff"
            )
            before = _flat_file_hashes(output_dir)
            arguments = [
                "run_first_version.py",
                "--output-dir",
                str(output_dir),
            ]

            try:
                with (
                    patch("sys.argv", arguments),
                    patch.object(
                        pd.DataFrame,
                        "to_csv",
                        side_effect=OSError("injected first CSV failure"),
                    ),
                    patch("run_first_version.run_rolling_day_ahead") as solve,
                ):
                    main()
            except OSError as error:
                retained_exception = error
                retained_traceback = error.__traceback__
            else:
                self.fail("OSError not raised")

            self.assertEqual(
                str(retained_exception),
                "injected first CSV failure",
            )
            self.assertIsNotNone(retained_traceback)
            solve.assert_not_called()
            self.assertEqual(_flat_file_hashes(output_dir), before)
            self.assertEqual(list(root.glob(".day-ahead-staging-*")), [])
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

        retained_exception = None
        retained_traceback = None

    def test_second_case_failure_preserves_outputs_and_cleans_staging(
        self,
    ) -> None:
        real_run_rolling = run_first_version.run_rolling_day_ahead
        call_count = 0

        def fail_on_second_case(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("injected second-case failure")
            return real_run_rolling(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "outputs"
            output_dir.mkdir()
            for filename, content in {
                "case_metrics.csv": b"old metrics\n",
                "renewables_only_day_01_primary.lp": b"old primary LP\n",
                "unknown-sentinel.bin": b"unknown sentinel\x00\xff",
            }.items():
                (output_dir / filename).write_bytes(content)
            for index, filename in enumerate(LEGACY_PLOT_FILENAMES):
                (output_dir / filename).write_bytes(
                    f"legacy solve {index}\n".encode("ascii")
                )
            before = _flat_file_hashes(output_dir)
            arguments = [
                "run_first_version.py",
                "--output-dir",
                str(output_dir),
            ]

            with (
                patch("sys.argv", arguments),
                patch(
                    "run_first_version.run_rolling_day_ahead",
                    side_effect=fail_on_second_case,
                ),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
                self.assertRaisesRegex(
                    RuntimeError,
                    "injected second-case failure",
                ),
            ):
                main()

            self.assertEqual(call_count, 2)
            self.assertNotIn('"model_type"', stdout.getvalue())
            self.assertNotIn("Operating cost metrics:", stdout.getvalue())
            self.assertEqual(_flat_file_hashes(output_dir), before)
            self.assertEqual(list(root.glob(".day-ahead-staging-*")), [])
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    def test_publish_failure_rolls_back_replaced_files(self) -> None:
        real_replace = os.replace
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_dir = root / "staging"
            output_dir = root / "outputs"
            staging_dir.mkdir()
            output_dir.mkdir()
            (staging_dir / "a.csv").write_bytes(b"new a\n")
            (staging_dir / "b.csv").write_bytes(b"new b\n")
            (output_dir / "a.csv").write_bytes(b"old a\n")
            (output_dir / "b.csv").write_bytes(b"old b\n")
            (output_dir / "unknown.bin").write_bytes(b"unknown\x00\xff")
            before = _flat_file_hashes(output_dir)

            def fail_on_second_publish(source, target):
                source_path = Path(source)
                if (
                    source_path.parent == staging_dir
                    and source_path.name == "b.csv"
                ):
                    raise OSError("injected publish failure")
                return real_replace(source, target)

            with (
                patch(
                    "run_first_version.os.replace",
                    side_effect=fail_on_second_publish,
                ),
                self.assertRaisesRegex(OSError, "injected publish failure"),
            ):
                _publish_staged_outputs(staging_dir, output_dir)

            self.assertEqual(_flat_file_hashes(output_dir), before)
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    def test_publish_removes_legacy_files_and_staged_overlap_wins(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_dir = root / "staging"
            output_dir = root / "outputs"
            staging_dir.mkdir()
            output_dir.mkdir()
            overlap_name = LEGACY_PLOT_FILENAMES[0]
            (staging_dir / overlap_name).write_bytes(b"new plot\n")
            for index, filename in enumerate(LEGACY_PLOT_FILENAMES):
                (output_dir / filename).write_bytes(
                    f"old plot {index}\n".encode("ascii")
                )
            unknown_path = output_dir / "unknown.bin"
            unknown_path.write_bytes(b"unknown\x00\xff")

            _publish_staged_outputs(
                staging_dir,
                output_dir,
                remove_names=set(LEGACY_PLOT_FILENAMES),
            )

            self.assertEqual(
                (output_dir / overlap_name).read_bytes(),
                b"new plot\n",
            )
            for filename in LEGACY_PLOT_FILENAMES[1:]:
                self.assertFalse((output_dir / filename).exists())
            self.assertEqual(unknown_path.read_bytes(), b"unknown\x00\xff")
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    def test_publish_rejects_non_flat_remove_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_dir = root / "staging"
            output_dir = root / "outputs"
            staging_dir.mkdir()
            output_dir.mkdir()
            unknown_path = output_dir / "unknown.bin"
            unknown_path.write_bytes(b"unknown\x00\xff")

            for remove_name in ("", ".", "..", "nested/plot.png"):
                with self.subTest(remove_name=remove_name):
                    with self.assertRaises(ValueError):
                        _publish_staged_outputs(
                            staging_dir,
                            output_dir,
                            remove_names={remove_name},
                        )

            self.assertEqual(unknown_path.read_bytes(), b"unknown\x00\xff")
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    def test_publish_failure_restores_removed_legacy_files(self) -> None:
        real_replace = os.replace
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_dir = root / "staging"
            output_dir = root / "outputs"
            staging_dir.mkdir()
            output_dir.mkdir()
            (staging_dir / "a.csv").write_bytes(b"new a\n")
            (staging_dir / "b.csv").write_bytes(b"new b\n")
            (output_dir / "a.csv").write_bytes(b"old a\n")
            for index, filename in enumerate(LEGACY_PLOT_FILENAMES):
                (output_dir / filename).write_bytes(
                    f"legacy plot {index}\n".encode("ascii")
                )
            for filename in LEGACY_GENERATED_FILENAMES:
                if filename not in LEGACY_PLOT_FILENAMES:
                    (output_dir / filename).write_bytes(b"legacy output\n")
            (output_dir / "unknown.bin").write_bytes(b"unknown\x00\xff")
            before = _flat_file_hashes(output_dir)

            def fail_during_publish(source, target):
                source_path = Path(source)
                if (
                    source_path.parent == staging_dir
                    and source_path.name == "b.csv"
                ):
                    raise OSError("injected legacy publish failure")
                return real_replace(source, target)

            with (
                patch(
                    "run_first_version.os.replace",
                    side_effect=fail_during_publish,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "injected legacy publish failure",
                ),
            ):
                _publish_staged_outputs(
                    staging_dir,
                    output_dir,
                    remove_names=set(LEGACY_GENERATED_FILENAMES),
                )

            self.assertEqual(_flat_file_hashes(output_dir), before)
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    @unittest.skipUnless(os.name == "nt", "requires Windows attributes")
    def test_publish_rollback_removes_readonly_new_file(self) -> None:
        real_replace = os.replace
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_dir = root / "staging"
            output_dir = root / "outputs"
            staging_dir.mkdir()
            output_dir.mkdir()
            staged_first = staging_dir / "a.csv"
            staged_first.write_bytes(b"readonly new a\n")
            staged_first.chmod(stat.S_IREAD)
            (staging_dir / "b.csv").write_bytes(b"new b\n")
            (output_dir / "a.csv").write_bytes(b"old a\n")
            (output_dir / "b.csv").write_bytes(b"old b\n")
            (output_dir / "unknown.bin").write_bytes(b"unknown\x00\xff")
            before = _flat_file_hashes(output_dir)
            readonly_before = {
                path.name: bool(
                    path.stat().st_file_attributes
                    & stat.FILE_ATTRIBUTE_READONLY
                )
                for path in output_dir.iterdir()
            }

            def fail_on_second_publish(source, target):
                source_path = Path(source)
                if (
                    source_path.parent == staging_dir
                    and source_path.name == "b.csv"
                ):
                    raise OSError("injected readonly publish failure")
                return real_replace(source, target)

            with (
                patch(
                    "run_first_version.os.replace",
                    side_effect=fail_on_second_publish,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "injected readonly publish failure",
                ),
            ):
                _publish_staged_outputs(staging_dir, output_dir)

            self.assertEqual(_flat_file_hashes(output_dir), before)
            self.assertEqual(
                {
                    path.name: bool(
                        path.stat().st_file_attributes
                        & stat.FILE_ATTRIBUTE_READONLY
                    )
                    for path in output_dir.iterdir()
                },
                readonly_before,
            )
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    @unittest.skipUnless(os.name == "nt", "requires Windows attributes")
    def test_publish_rollback_restores_readonly_old_target(self) -> None:
        real_replace = os.replace
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_dir = root / "staging"
            output_dir = root / "outputs"
            staging_dir.mkdir()
            output_dir.mkdir()
            (staging_dir / "a.csv").write_bytes(b"new a\n")
            (staging_dir / "b.csv").write_bytes(b"new b\n")
            old_target = output_dir / "a.csv"
            old_target.write_bytes(b"readonly old a\n")
            old_target.chmod(stat.S_IREAD)
            (output_dir / "b.csv").write_bytes(b"old b\n")
            (output_dir / "unknown.bin").write_bytes(b"unknown\x00\xff")
            before = _flat_file_hashes(output_dir)

            def fail_on_second_publish(source, target):
                source_path = Path(source)
                if (
                    source_path.parent == staging_dir
                    and source_path.name == "b.csv"
                ):
                    raise OSError("injected readonly target failure")
                return real_replace(source, target)

            with (
                patch(
                    "run_first_version.os.replace",
                    side_effect=fail_on_second_publish,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "injected readonly target failure",
                ),
            ):
                _publish_staged_outputs(staging_dir, output_dir)

            self.assertEqual(_flat_file_hashes(output_dir), before)
            self.assertTrue(
                old_target.stat().st_file_attributes
                & stat.FILE_ATTRIBUTE_READONLY
            )
            self.assertEqual(
                (output_dir / "unknown.bin").read_bytes(),
                b"unknown\x00\xff",
            )
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    def test_publish_restore_failure_preserves_backup_directory(self) -> None:
        real_replace = os.replace
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_dir = root / "staging"
            output_dir = root / "outputs"
            staging_dir.mkdir()
            output_dir.mkdir()
            (staging_dir / "a.csv").write_bytes(b"new a\n")
            (staging_dir / "b.csv").write_bytes(b"new b\n")
            (output_dir / "a.csv").write_bytes(b"old a\n")
            (output_dir / "b.csv").write_bytes(b"old b\n")
            (output_dir / "unknown.bin").write_bytes(b"unknown\x00\xff")

            def fail_publish_and_restore(source, target):
                source_path = Path(source)
                if (
                    source_path.parent == staging_dir
                    and source_path.name == "b.csv"
                ):
                    raise OSError("injected publish failure")
                if (
                    source_path.parent.name.startswith(
                        ".day-ahead-backup-"
                    )
                    and source_path.name == "a.csv"
                ):
                    raise OSError("injected restore failure")
                return real_replace(source, target)

            with (
                patch(
                    "run_first_version.os.replace",
                    side_effect=fail_publish_and_restore,
                ),
                self.assertRaises(RuntimeError) as context,
            ):
                _publish_staged_outputs(staging_dir, output_dir)

            backup_directories = list(
                root.glob(".day-ahead-backup-*")
            )
            self.assertEqual(len(backup_directories), 1)
            backup_dir = backup_directories[0]
            self.assertIn(str(backup_dir), str(context.exception))
            self.assertEqual(
                (backup_dir / "a.csv").read_bytes(),
                b"old a\n",
            )
            self.assertEqual(
                (output_dir / "unknown.bin").read_bytes(),
                b"unknown\x00\xff",
            )

    def test_plot_failure_preserves_outputs_and_cleans_staging(self) -> None:
        def fail_after_partial_plot_write(
            all_results,
            metrics,
            plot_output_dir,
        ) -> None:
            del all_results, metrics
            plot_output_dir.mkdir(parents=True, exist_ok=True)
            (plot_output_dir / PLOT_FILES[0]).write_bytes(b"partial plot")
            raise RuntimeError("injected plot failure")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "outputs"
            output_dir.mkdir()
            (output_dir / "case_metrics.csv").write_bytes(b"old metrics\n")
            (output_dir / "unknown-sentinel.bin").write_bytes(
                b"unknown sentinel\x00\xff"
            )
            for index, filename in enumerate(LEGACY_PLOT_FILENAMES):
                (output_dir / filename).write_bytes(
                    f"legacy plot {index}\n".encode("ascii")
                )
            for filename in LEGACY_GENERATED_FILENAMES:
                if filename not in LEGACY_PLOT_FILENAMES:
                    (output_dir / filename).write_bytes(b"legacy output\n")
            before = _flat_file_hashes(output_dir)
            arguments = [
                "run_first_version.py",
                "--output-dir",
                str(output_dir),
            ]

            with (
                patch("sys.argv", arguments),
                patch(
                    "run_first_version.make_plots",
                    side_effect=fail_after_partial_plot_write,
                ),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
                self.assertRaisesRegex(
                    RuntimeError,
                    "injected plot failure",
                ),
            ):
                main()

            self.assertNotIn('"model_type"', stdout.getvalue())
            self.assertNotIn("Operating cost metrics:", stdout.getvalue())
            self.assertEqual(_flat_file_hashes(output_dir), before)
            self.assertEqual(list(root.glob(".day-ahead-staging-*")), [])
            self.assertEqual(list(root.glob(".day-ahead-backup-*")), [])

    def test_default_cli_generates_deterministic_day_ahead_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "results"
            output_dir.mkdir()
            unknown_path = output_dir / "unknown-sentinel.bin"
            unknown_content = b"unknown sentinel\x00\xff"
            unknown_path.write_bytes(unknown_content)
            for index, filename in enumerate(LEGACY_PLOT_FILENAMES):
                (output_dir / filename).write_bytes(
                    f"legacy plot {index}\n".encode("ascii")
                )
            for filename in LEGACY_GENERATED_FILENAMES:
                if filename not in LEGACY_PLOT_FILENAMES:
                    (output_dir / filename).write_bytes(b"legacy output\n")
            arguments = [
                "run_first_version.py",
                "--output-dir",
                str(output_dir),
            ]
            with (
                patch("sys.argv", arguments),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                main()

            self.assertTrue(stdout.getvalue().isascii())
            self.assertEqual(unknown_path.read_bytes(), unknown_content)
            for filename in LEGACY_GENERATED_FILENAMES:
                self.assertFalse((output_dir / filename).exists())
            model_input = pd.read_csv(
                output_dir / "model_input_28_days.csv"
            )
            hourly = pd.read_csv(output_dir / "hourly_case_results.csv")
            daily = pd.read_csv(output_dir / "daily_case_metrics.csv")
            metrics = pd.read_csv(output_dir / "case_metrics.csv")
            with (output_dir / "run_metadata.json").open(
                encoding="utf-8"
            ) as file:
                metadata = json.load(file)

            self.assertEqual(metrics["case"].tolist(), CASE_ORDER)
            self.assertEqual(len(model_input), 672)
            self.assertEqual(len(hourly), 4 * 675)
            self.assertEqual(len(daily), 4 * 28)
            self.assertEqual(
                hourly.groupby("case", sort=False).size().index.tolist(),
                CASE_ORDER,
            )
            self.assertEqual(
                hourly.groupby("case", sort=False).size().tolist(),
                [675] * 4,
            )
            self.assertTrue(
                {
                    "cpu_arrival_pu",
                    "hour",
                    "timestamp_lst",
                    "solar_available_mw",
                    "wind_available_mw",
                    "tou_period",
                    "electricity_price_cny_per_kwh",
                }.issubset(model_input.columns)
            )
            self.assertTrue(
                {
                    "case",
                    "hour",
                    "cpu_arrival_pu",
                    "cpu_scheduled_pu",
                    "it_power_mw",
                    "dc_power_mw",
                    "grid_power_mw",
                    "solar_available_mw",
                    "solar_used_mw",
                    "solar_curtailed_mw",
                    "wind_available_mw",
                    "wind_used_mw",
                    "wind_curtailed_mw",
                    "charge_mw",
                    "discharge_mw",
                    "soc_start",
                    "soc_end",
                    "stored_energy_start_mwh",
                    "stored_energy_end_mwh",
                    "charge_active",
                    "discharge_active",
                    "period_role",
                    "timestamp_lst",
                    "day",
                    "hour_of_day",
                    "tou_period",
                    "electricity_price_cny_per_kwh",
                    "hourly_grid_purchase_cost_cny",
                    "hourly_solar_om_cost_cny",
                    "hourly_wind_om_cost_cny",
                    "hourly_battery_om_cost_cny",
                    "hourly_battery_degradation_cost_cny",
                    "hourly_operating_cost_cny",
                }.issubset(hourly.columns)
            )
            self.assertTrue(
                {
                    "case",
                    "grid_purchase_cost_cny",
                    "solar_om_cost_cny",
                    "wind_om_cost_cny",
                    "battery_om_cost_cny",
                    "battery_degradation_cost_cny",
                    "operating_cost_cny",
                    "operating_cost_savings_vs_renewables_only_pct",
                    "grid_purchase_energy_mwh",
                    "grid_peak_power_mw",
                    "renewable_available_energy_mwh",
                    "renewable_used_energy_mwh",
                    "renewable_curtailment_energy_mwh",
                    "renewable_curtailment_rate_pct",
                    "battery_charged_energy_mwh",
                    "battery_discharged_energy_mwh",
                    "battery_throughput_energy_mwh",
                    "battery_equivalent_full_cycles",
                    "cross_day_task_cpu_pu_hours",
                    "total_task_delay_cpu_hours",
                    "average_flexible_task_delay_h",
                    "maximum_task_delay_h",
                    "cpu_conservation_error",
                    "soc_cycle_error",
                    "max_simultaneous_charge_discharge_mw2",
                    "grid_binding_hours",
                    "grid_minimum_margin_mw",
                }.issubset(metrics.columns)
            )
            self.assertAlmostEqual(
                float(
                    metrics.loc[
                        metrics["case"] == "renewables_only",
                        "operating_cost_savings_vs_renewables_only_pct",
                    ].iloc[0]
                ),
                0.0,
            )

            self.assertEqual(
                metadata["model_type"],
                "rolling_24_plus_3_deterministic_day_ahead",
            )
            self.assertEqual(
                metadata["scenario_status"],
                "houston_2020_main_experiment",
            )
            self.assertEqual(
                metadata["renewable_data_source"]["location"],
                "Houston, Texas, USA",
            )
            self.assertEqual(
                metadata["electricity_price_source"],
                {
                    "file": str(SCENARIO_PATH),
                    "currency": "CNY",
                    "tariff_type": "time_of_use",
                    "geographic_role": "exogenous paper tariff",
                    "source_paper": (
                        "A novel demand response-based distributed "
                        "multi-energy system optimal operation framework "
                        "for data centers"
                    ),
                },
            )
            self.assertEqual(
                metadata["geographic_interpretation"],
                "风光出力来自 Houston；购电价沿用论文分段电价，"
                "作为外生价格信号，不主张二者具有地理一致性。",
            )
            self.assertEqual(metadata["representative_day"], 8)
            self.assertEqual(metadata["stress_day"], 28)
            self.assertEqual(metadata["formal_cases"], CASE_ORDER)
            self.assertEqual(metadata["cost_baseline_case"], "renewables_only")
            parameter_values = metadata["parameters"]
            parameters = Parameters()
            self.assertEqual(
                parameter_values["server_idle_power_kw"],
                parameters.server_idle_power_kw,
            )
            self.assertEqual(
                parameter_values["solar_capacity_mw"],
                parameters.solar_capacity_mw,
            )
            self.assertEqual(
                parameter_values["solar_inverter_capacity_mw"],
                parameters.solar_inverter_capacity_mw,
            )
            self.assertEqual(
                parameter_values["wind_capacity_mw"],
                parameters.wind_capacity_mw,
            )
            software = metadata["software_versions"]
            self.assertIsInstance(software, dict)
            self.assertTrue(
                {
                    "python",
                    "pyscipopt",
                    "scip",
                    "pillow",
                    "nrel_pysam",
                    "pandas",
                    "numpy",
                }.issubset(software)
            )
            self.assertEqual(software["pandas"], pd.__version__)
            self.assertEqual(software["numpy"], np.__version__)

            required_files = [
                "model_input_28_days.csv",
                "all_days_hourly.csv",
                "hourly_case_results.csv",
                "daily_case_metrics.csv",
                "case_metrics.csv",
                "run_metadata.json",
                INPUT_PATH.name,
                SCENARIO_PATH.name,
                "renewables_only_day_01_primary.lp",
                "renewables_only_day_28_secondary.lp",
                "renewables_shift_warmup_primary.lp",
                "renewables_storage_soc_coordination_secondary.lp",
                "joint_day_28_secondary.lp",
            ]
            for filename in required_files:
                self.assertTrue((output_dir / filename).is_file(), filename)
            for source_path in (
                INPUT_PATH,
                SCENARIO_PATH,
            ):
                self.assertEqual(
                    hashlib.sha256(source_path.read_bytes()).digest(),
                    hashlib.sha256(
                        (output_dir / source_path.name).read_bytes()
                    ).digest(),
                )
            self.assertEqual(len(list(output_dir.glob("*.lp"))), 232)

            self.assertEqual(
                sorted(path.name for path in output_dir.glob("*.png")),
                sorted(PLOT_FILES),
            )
            for filename in PLOT_FILES:
                plot_path = output_dir / filename
                self.assertGreater(plot_path.stat().st_size, 0, filename)
                with Image.open(plot_path) as image:
                    self.assertEqual(image.size, PLOT_SIZES[filename])
                    self.assertEqual(image.mode, "RGB")
                    image.verify()

            with Image.open(
                output_dir / "day_ahead_power_results.png"
            ) as power_plot:
                joint_color = (220, 38, 38)
                power_boxes = [
                    (121, 207, 861, 545),
                    (1001, 207, 1741, 545),
                    (121, 722, 861, 1040),
                    (1001, 722, 1741, 1040),
                ]
                for label, box in zip(
                    ("DC", "grid", "solar used", "wind used"),
                    power_boxes,
                    strict=True,
                ):
                    self.assert_plot_has_color(
                        power_plot,
                        joint_color,
                        f"power series: {label}",
                        box=box,
                    )

            with Image.open(
                output_dir / "compute_scheduling_results.png"
            ) as compute_plot:
                self.assert_plot_has_color(
                    compute_plot,
                    (51, 65, 85),
                    "CPU arrival",
                )
                self.assert_plot_has_color(
                    compute_plot,
                    (220, 38, 38),
                    "CPU scheduled",
                )

            with Image.open(
                output_dir / "battery_operation_results.png"
            ) as battery_plot:
                for label, color in [
                    ("battery charge", (37, 99, 235)),
                    ("battery discharge", (234, 88, 12)),
                    ("SOC start", (124, 58, 237)),
                    ("SOC end", (5, 150, 105)),
                ]:
                    self.assert_plot_has_color(battery_plot, color, label)

            with Image.open(
                output_dir / "renewable_dispatch_results.png"
            ) as renewable_plot:
                for label, color in [
                    ("renewable available", (100, 116, 139)),
                    ("renewable used", (5, 150, 105)),
                    ("renewable curtailed", (220, 38, 38)),
                ]:
                    self.assert_plot_has_color(renewable_plot, color, label)

            with Image.open(
                output_dir / "operating_cost_comparison.png"
            ) as cost_plot:
                for label, color in [
                    ("grid purchase cost", (79, 70, 229)),
                    ("solar O&M cost", (245, 158, 11)),
                    ("wind O&M cost", (2, 132, 199)),
                    ("battery O&M cost", (234, 88, 12)),
                    ("battery degradation cost", (219, 39, 119)),
                ]:
                    self.assert_plot_has_color(cost_plot, color, label)

    def test_make_plots_handles_complete_all_zero_inputs(self) -> None:
        hourly_results, metrics = _zero_plot_inputs()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "plots"

            make_plots(hourly_results, metrics, output_dir)

            self.assertEqual(
                sorted(path.name for path in output_dir.glob("*.png")),
                sorted(PLOT_FILES),
            )
            for filename in PLOT_FILES:
                with Image.open(output_dir / filename) as image:
                    self.assertEqual(image.size, PLOT_SIZES[filename])
                    self.assertEqual(image.mode, "RGB")
                    image.verify()

    def test_make_plots_rejects_empty_inputs_before_writing_png(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "plots"

            with self.assertRaises(ValueError):
                make_plots(pd.DataFrame(), pd.DataFrame(), output_dir)

            self.assertFalse(
                any((output_dir / filename).is_file() for filename in PLOT_FILES)
            )

    def test_make_plots_validates_cases_hours_and_numeric_columns(
        self,
    ) -> None:
        hourly_results, metrics = _zero_plot_inputs()
        duplicate_hour = hourly_results.copy()
        duplicate_hour.loc[
            (duplicate_hour["case"] == "joint")
            & (duplicate_hour["hour"] == 23),
            "hour",
        ] = 22
        nonfinite = hourly_results.copy()
        nonfinite.loc[0, "dc_power_mw"] = np.nan
        malformed_inputs = [
            (
                "hourly_results case",
                hourly_results[hourly_results["case"] != "joint"],
                metrics,
            ),
            ("hour", duplicate_hour, metrics),
            (
                "metrics case",
                hourly_results,
                pd.concat([metrics, metrics.iloc[[0]]], ignore_index=True),
            ),
            (
                "dc_power_mw",
                hourly_results.drop(columns="dc_power_mw"),
                metrics,
            ),
            ("dc_power_mw", nonfinite, metrics),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for index, (
                message_fragment,
                invalid_hourly,
                invalid_metrics,
            ) in enumerate(malformed_inputs):
                output_dir = root / str(index)
                with self.subTest(message_fragment=message_fragment):
                    with self.assertRaisesRegex(
                        ValueError, message_fragment
                    ):
                        make_plots(
                            invalid_hourly,
                            invalid_metrics,
                            output_dir,
                        )
                    self.assertFalse(
                        any(
                            (output_dir / filename).is_file()
                            for filename in PLOT_FILES
                        )
                    )

    def test_make_plots_rejects_invalid_physical_semantics_before_writing(
        self,
    ) -> None:
        hourly_results, metrics = _zero_plot_inputs()

        negative_power = hourly_results.copy()
        negative_power.loc[0, "dc_power_mw"] = -1e-6

        negative_hourly_cost = hourly_results.copy()
        negative_hourly_cost.loc[
            0, "hourly_operating_cost_cny"
        ] = -1e-6

        negative_metric_cost = metrics.copy()
        negative_metric_cost.loc[0, "operating_cost_cny"] = -1e-6

        invalid_soc = hourly_results.copy()
        invalid_soc.loc[0, "soc_end"] = 0.900001

        fractional_hour = hourly_results.copy()
        fractional_hour["hour"] = fractional_hour["hour"].astype(float)
        fractional_hour.loc[0, "hour"] = 0.5

        inconsistent_cpu_arrival = hourly_results.copy()
        inconsistent_cpu_arrival.loc[
            (inconsistent_cpu_arrival["case"] == "joint")
            & (inconsistent_cpu_arrival["hour"] == 0),
            "cpu_arrival_pu",
        ] = 0.01

        invalid_inputs = [
            ("dc_power_mw", negative_power, metrics),
            (
                "hourly_operating_cost_cny",
                negative_hourly_cost,
                metrics,
            ),
            (
                "operating_cost_cny",
                hourly_results,
                negative_metric_cost,
            ),
            ("soc_end", invalid_soc, metrics),
            ("integer", fractional_hour, metrics),
            (
                "joint.*cpu_arrival_pu",
                inconsistent_cpu_arrival,
                metrics,
            ),
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for index, (
                message_pattern,
                invalid_hourly,
                invalid_metrics,
            ) in enumerate(invalid_inputs):
                output_dir = root / str(index)
                with self.subTest(message_pattern=message_pattern):
                    with self.assertRaisesRegex(
                        ValueError, message_pattern
                    ):
                        make_plots(
                            invalid_hourly,
                            invalid_metrics,
                            output_dir,
                        )
                    self.assertFalse(
                        any(
                            (output_dir / filename).is_file()
                            for filename in PLOT_FILES
                        )
                    )

    def test_boundary_negative_costs_render_as_zero_without_negative_zero(
        self,
    ) -> None:
        hourly_results, metrics = _zero_plot_inputs()
        component_columns = [
            "grid_purchase_cost_cny",
            "solar_om_cost_cny",
            "wind_om_cost_cny",
            "battery_om_cost_cny",
            "battery_degradation_cost_cny",
        ]
        metrics.loc[:, component_columns] = -1e-10
        metrics.loc[:, "operating_cost_cny"] = 0.0
        drawn_text: list[str] = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(
            image_draw: ImageDraw.ImageDraw,
            xy: tuple[float, float] | tuple[int, int],
            text: str,
            *args: object,
            **kwargs: object,
        ) -> None:
            drawn_text.append(str(text))
            original_text(image_draw, xy, text, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "plots"
            with patch.object(
                ImageDraw.ImageDraw,
                "text",
                new=record_text,
            ):
                make_plots(hourly_results, metrics, output_dir)

            self.assertEqual(drawn_text.count("CNY 0"), len(CASE_ORDER))
            self.assertNotIn("CNY -0", drawn_text)
            for filename in PLOT_FILES:
                with Image.open(output_dir / filename) as image:
                    image.verify()

    def test_normalized_nonnegative_cost_obeys_exact_tolerance(self) -> None:
        for value in (-1e-10, -5e-11, -1e-20, -0.0):
            with self.subTest(value=value):
                self.assertEqual(
                    reporting._normalized_nonnegative_cost(value),
                    0.0,
                )

        self.assertEqual(
            reporting._normalized_nonnegative_cost(12.5),
            12.5,
        )
        with self.assertRaises(ValueError):
            reporting._normalized_nonnegative_cost(-1.000001e-10)


if __name__ == "__main__":
    unittest.main()
