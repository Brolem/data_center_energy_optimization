from __future__ import annotations

import unittest

import pandas as pd

from dc_energy_opt.experiments.storage_scale_sensitivity import (
    DEFAULT_STORAGE_SCALES,
    build_storage_scale_summary,
)


def _case_metrics(
    *,
    renewables_only: float,
    renewables_shift: float,
    renewables_storage: float,
    joint: float,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case": [
                "renewables_only",
                "renewables_shift",
                "renewables_storage",
                "joint",
            ],
            "status": ["optimal"] * 4,
            "operating_cost_cny": [
                renewables_only,
                renewables_shift,
                renewables_storage,
                joint,
            ],
        }
    )


class StorageScaleSensitivityTests(unittest.TestCase):
    def test_build_summary_decomposes_storage_effect_on_shift(self) -> None:
        metrics = build_storage_scale_summary(
            case_metrics_by_scale={
                "energy_2p0_mwh_power_0p5_mw": _case_metrics(
                    renewables_only=100.0,
                    renewables_shift=92.0,
                    renewables_storage=90.0,
                    joint=84.0,
                )
            },
            storage_scales=(DEFAULT_STORAGE_SCALES[0],),
        )

        row = metrics.iloc[0]
        self.assertEqual(float(row["no_storage_shift_savings_cny"]), 8.0)
        self.assertEqual(float(row["storage_shift_savings_cny"]), 6.0)
        self.assertEqual(float(row["storage_effect_on_shift_cny"]), -2.0)


if __name__ == "__main__":
    unittest.main()
