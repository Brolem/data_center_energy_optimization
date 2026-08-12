from __future__ import annotations

import importlib
import unittest


class PaperModuleBoundaryTests(unittest.TestCase):
    def test_paper_experiments_live_under_houston_2020_track(self) -> None:
        expected_functions = {
            "experiments.paper.houston_2020.day_ahead": (
                "run_houston_2020_experiment"
            ),
            "experiments.paper.houston_2020.sensitivity.flex_ratio": (
                "run_flex_ratio_sensitivity_experiment"
            ),
            "experiments.paper.houston_2020.sensitivity.storage_scale": (
                "run_storage_scale_sensitivity_experiment"
            ),
            "experiments.paper.houston_2020.sensitivity.storage_energy_power": (
                "run_storage_energy_power_sensitivity_experiment"
            ),
        }

        missing: list[str] = []
        for module_name, function_name in expected_functions.items():
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError:
                missing.append(module_name)
                continue
            self.assertTrue(hasattr(module, function_name))

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
