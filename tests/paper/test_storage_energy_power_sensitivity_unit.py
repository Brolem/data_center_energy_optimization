from __future__ import annotations

import unittest

from experiments.paper.houston_2020.sensitivity.storage_energy_power import (
    DEFAULT_STORAGE_ENERGY_POWER_SCALES,
)


class StorageEnergyPowerSensitivityTests(unittest.TestCase):
    def test_default_grid_covers_each_energy_and_power_combination(
        self,
    ) -> None:
        actual_pairs = {
            (scale.battery_energy_mwh, scale.battery_power_mw)
            for scale in DEFAULT_STORAGE_ENERGY_POWER_SCALES
        }

        self.assertEqual(
            actual_pairs,
            {
                (2.0, 0.5),
                (2.0, 1.0),
                (2.0, 1.5),
                (4.0, 0.5),
                (4.0, 1.0),
                (4.0, 1.5),
                (6.0, 0.5),
                (6.0, 1.0),
                (6.0, 1.5),
            },
        )


if __name__ == "__main__":
    unittest.main()
