from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from scip_first_version.config import Parameters
from scip_first_version.data import load_and_prepare
from scip_first_version.model import build_and_solve


class RefactorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.csv_path = Path(
            "data/instance_usage_grouped_300_seconds_month.csv"
        )
        cls.raw, cls.hourly, cls.representative_day, cls.stress_day = (
            load_and_prepare(cls.csv_path)
        )

    def test_data_preparation_preserves_representative_and_stress_days(self) -> None:
        self.assertEqual(len(self.raw), 8064)
        self.assertEqual(len(self.hourly), 28 * 24)
        self.assertEqual(self.representative_day, 8)
        self.assertEqual(self.stress_day, 28)

    def test_legacy_entrypoint_reexports_public_names(self) -> None:
        from run_first_version import (
            Parameters as LegacyParameters,
            build_and_solve as legacy_build_and_solve,
            load_and_prepare as legacy_load_and_prepare,
            make_plots as legacy_make_plots,
        )
        from scip_first_version.reporting import make_plots

        self.assertIs(LegacyParameters, Parameters)
        self.assertIs(legacy_load_and_prepare, load_and_prepare)
        self.assertIs(legacy_build_and_solve, build_and_solve)
        self.assertIs(legacy_make_plots, make_plots)

    def test_default_case_metrics_match_pre_refactor_baseline(self) -> None:
        selected = self.hourly[
            self.hourly["day"] == self.representative_day
        ].sort_values("hour")
        cpu_arrival = selected["avg_cpu"].to_numpy(dtype=float)
        expected_total_variation = {
            "baseline": 14.780637753565614,
            "shift_only": 2.18985803099865,
            "storage_only": 3.7850716035594445,
            "joint": 1.5332981943442832,
        }
        params = Parameters()

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            for case_name, enable_shift, enable_storage in [
                ("baseline", False, False),
                ("shift_only", True, False),
                ("storage_only", False, True),
                ("joint", True, True),
            ]:
                result, metrics = build_and_solve(
                    cpu_arrival=cpu_arrival,
                    params=params,
                    enable_shift=enable_shift,
                    enable_storage=enable_storage,
                    case_name=case_name,
                    output_dir=output_dir,
                    show_log=False,
                )
                self.assertEqual(len(result), 24)
                self.assertAlmostEqual(
                    metrics["total_variation_mw"],
                    expected_total_variation[case_name],
                    delta=1e-6,
                )
                self.assertLessEqual(
                    metrics["cpu_conservation_error"], 1e-9
                )
                self.assertTrue(
                    np.isfinite(metrics["mip_gap"])
                )


if __name__ == "__main__":
    unittest.main()
