from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "verify_reorganization_equivalence.py"

LEGACY_FILENAMES = {
    "hourly": "hourly_case_results.csv",
    "daily": "daily_case_metrics.csv",
    "case": "case_metrics.csv",
}
CURRENT_FILENAMES = {
    "hourly": "hourly_dispatch.csv",
    "daily": "daily_metrics.csv",
    "case": "case_metrics.csv",
}


def _tables() -> dict[str, pd.DataFrame]:
    return {
        "hourly": pd.DataFrame(
            {
                "case": ["renewables_only", "joint"],
                "hour": [0, 1],
                "grid_power_mw": [1.0, 2.0],
                "period_role": ["analysis", "settlement_tail"],
            }
        ),
        "daily": pd.DataFrame(
            {
                "case": ["renewables_only", "joint"],
                "day": [1, 1],
                "operating_cost_cny": [10.0, 9.0],
            }
        ),
        "case": pd.DataFrame(
            {
                "case": ["renewables_only", "joint"],
                "status": ["optimal", "optimal"],
                "storage_enabled": [False, True],
                "operating_cost_cny": [100.0, 90.0],
                "rolling_solve_time_s": [1.0, 2.0],
                "warmup_solve_time_s": [0.0, 0.0],
                "soc_coordination_solve_time_s": [0.0, 3.0],
                "solve_time_s": [1.0, 5.0],
            }
        ),
    }


def _write_result_set(
    directory: Path,
    *,
    layout: str,
    tables: dict[str, pd.DataFrame],
) -> None:
    directory.mkdir(parents=True)
    filenames = LEGACY_FILENAMES if layout == "legacy" else CURRENT_FILENAMES
    for table_name, frame in tables.items():
        frame.to_csv(directory / filenames[table_name], index=False)


class EquivalenceVerificationTests(unittest.TestCase):
    def _run(
        self,
        reference_dir: Path,
        actual_dir: Path,
        *,
        reference_layout: str = "legacy",
        actual_layout: str = "current",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--reference-dir",
                str(reference_dir),
                "--actual-dir",
                str(actual_dir),
                "--reference-layout",
                reference_layout,
                "--actual-layout",
                actual_layout,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_legacy_and_current_results_allow_tolerance_and_new_timings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            reference_tables = _tables()
            actual_tables = {name: frame.copy() for name, frame in _tables().items()}
            actual_tables["hourly"].loc[0, "grid_power_mw"] += 5e-10
            actual_tables["case"].loc[0, "rolling_solve_time_s"] = 99.0
            actual_tables["case"].loc[1, "solve_time_s"] = 101.0
            reference_dir = root / "reference"
            actual_dir = root / "actual"
            _write_result_set(
                reference_dir,
                layout="legacy",
                tables=reference_tables,
            )
            _write_result_set(
                actual_dir,
                layout="current",
                tables=actual_tables,
            )

            completed = self._run(reference_dir, actual_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertTrue(report["equivalent"])
            self.assertEqual(report["tables"]["hourly"]["rows"], 2)
            self.assertAlmostEqual(
                report["tables"]["hourly"]["max_abs_diff"],
                5e-10,
            )
            self.assertEqual(report["tables"]["daily"]["max_abs_diff"], 0.0)
            self.assertEqual(report["tables"]["case"]["max_abs_diff"], 0.0)

    def test_current_layout_can_be_compared_with_current_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            left = root / "formal"
            right = root / "compatibility"
            _write_result_set(left, layout="current", tables=_tables())
            _write_result_set(right, layout="current", tables=_tables())

            completed = self._run(
                left,
                right,
                reference_layout="current",
                actual_layout="current",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["equivalent"])

    def test_column_order_and_row_count_are_exact(self) -> None:
        for change, expected_message in (
            ("column_order", "列名或列顺序不一致"),
            ("row_count", "行数不一致"),
        ):
            with self.subTest(change=change):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    reference_tables = _tables()
                    actual_tables = {
                        name: frame.copy() for name, frame in _tables().items()
                    }
                    if change == "column_order":
                        columns = list(actual_tables["hourly"].columns)
                        actual_tables["hourly"] = actual_tables["hourly"][
                            list(reversed(columns))
                        ]
                    else:
                        actual_tables["daily"] = actual_tables["daily"].iloc[:1]
                    reference_dir = root / "reference"
                    actual_dir = root / "actual"
                    _write_result_set(
                        reference_dir,
                        layout="legacy",
                        tables=reference_tables,
                    )
                    _write_result_set(
                        actual_dir,
                        layout="current",
                        tables=actual_tables,
                    )

                    completed = self._run(reference_dir, actual_dir)

                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn(expected_message, completed.stderr)

    def test_text_and_out_of_tolerance_numeric_values_are_rejected(self) -> None:
        for change, expected_message in (
            ("text", "文本或布尔值不一致"),
            ("numeric", "数值差超过绝对容差"),
        ):
            with self.subTest(change=change):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    reference_tables = _tables()
                    actual_tables = {
                        name: frame.copy() for name, frame in _tables().items()
                    }
                    if change == "text":
                        actual_tables["case"].loc[1, "status"] = "infeasible"
                    else:
                        actual_tables["daily"].loc[
                            0, "operating_cost_cny"
                        ] += 2e-9
                    reference_dir = root / "reference"
                    actual_dir = root / "actual"
                    _write_result_set(
                        reference_dir,
                        layout="legacy",
                        tables=reference_tables,
                    )
                    _write_result_set(
                        actual_dir,
                        layout="current",
                        tables=actual_tables,
                    )

                    completed = self._run(reference_dir, actual_dir)

                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn(expected_message, completed.stderr)

    def test_timing_values_must_be_finite_and_nonnegative(self) -> None:
        for invalid_value in (-1.0, float("inf")):
            with self.subTest(invalid_value=invalid_value):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    reference_tables = _tables()
                    actual_tables = {
                        name: frame.copy() for name, frame in _tables().items()
                    }
                    actual_tables["case"].loc[
                        0, "warmup_solve_time_s"
                    ] = invalid_value
                    reference_dir = root / "reference"
                    actual_dir = root / "actual"
                    _write_result_set(
                        reference_dir,
                        layout="legacy",
                        tables=reference_tables,
                    )
                    _write_result_set(
                        actual_dir,
                        layout="current",
                        tables=actual_tables,
                    )

                    completed = self._run(reference_dir, actual_dir)

                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("计时字段必须有限且非负", completed.stderr)


if __name__ == "__main__":
    unittest.main()
