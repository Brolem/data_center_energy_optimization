from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from dc_energy_opt.config import Parameters
from experiments.career.ercot_2025_spot_gpu.data import (
    ENERGY_COLUMNS,
    build_energy_splits,
    load_energy_table,
    map_generation_signal_to_available_mw,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENERGY_PATH = PROJECT_ROOT / "data" / "energy" / "ercot_2025_houston_hourly.csv"
TARGET_COLUMNS = (
    "dam_lz_houston_usd_per_mwh",
    "erco_solar_generation_mwh",
    "erco_wind_generation_mwh",
)


class Ercot2025CareerInputContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = pd.read_csv(ENERGY_PATH)

    def _write_table(self, frame: pd.DataFrame) -> Path:
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        path = Path(temporary_directory.name) / "energy.csv"
        frame.to_csv(path, index=False)
        return path

    def test_load_preserves_the_exact_shared_schema_and_negative_price(self) -> None:
        loaded = load_energy_table(ENERGY_PATH)

        self.assertEqual(loaded.columns.tolist(), list(ENERGY_COLUMNS))
        self.assertTrue(
            (loaded["dam_lz_houston_usd_per_mwh"] < 0.0).any()
        )

    def test_load_rejects_reordered_columns_before_reading_values(self) -> None:
        reordered = self.frame.loc[:, list(reversed(self.frame.columns))]

        with self.assertRaisesRegex(ValueError, "字段顺序"):
            load_energy_table(self._write_table(reordered))

    def test_build_splits_rejects_missing_forecast_target_inside_summer_window(self) -> None:
        missing = self.frame.copy()
        missing.loc[0, "erco_solar_generation_mwh"] = float("nan")
        loaded = load_energy_table(self._write_table(missing))

        with self.assertRaisesRegex(ValueError, "缺失"):
            build_energy_splits(loaded)

    def test_build_splits_rejects_missing_forecast_target_inside_closure(self) -> None:
        missing = self.frame.copy()
        closure_index = missing.index[
            (missing["local_date"] == "2025-08-31")
            & (missing["local_hour"] == 1)
        ][0]
        missing.loc[closure_index, "erco_wind_generation_mwh"] = float("nan")
        loaded = load_energy_table(self._write_table(missing))

        with self.assertRaisesRegex(ValueError, "缺失"):
            build_energy_splits(loaded)

    def test_load_rejects_nonconsecutive_utc_timestamps(self) -> None:
        discontinuous = self.frame.drop(index=1).reset_index(drop=True)
        appended = discontinuous.iloc[[-1]].copy()
        appended.loc[:, "timestamp_utc"] = "2026-01-01T07:00:00Z"
        discontinuous = pd.concat((discontinuous, appended), ignore_index=True)

        with self.assertRaisesRegex(ValueError, "逐小时连续"):
            load_energy_table(self._write_table(discontinuous))

    def test_builds_the_fixed_summer_splits_and_three_hour_closure(self) -> None:
        splits = build_energy_splits(load_energy_table(ENERGY_PATH))

        self.assertEqual(len(splits.train), 4_343)
        self.assertEqual(len(splits.validation), 720)
        self.assertEqual(len(splits.test), 720)
        self.assertEqual(len(splits.test_with_closure), 723)
        self.assertEqual(
            splits.train["local_date"].iloc[0], "2025-01-01"
        )
        self.assertEqual(
            splits.train["local_date"].iloc[-1], "2025-06-30"
        )
        self.assertEqual(
            splits.validation["local_date"].iloc[0], "2025-07-01"
        )
        self.assertEqual(
            splits.test["local_date"].iloc[0], "2025-08-01"
        )
        self.assertEqual(
            splits.test_with_closure["local_date"].iloc[-1], "2025-08-31"
        )
        self.assertFalse(
            splits.test_with_closure.loc[:, TARGET_COLUMNS].isna().any().any()
        )

    def test_maps_system_generation_signals_to_configured_capacity(self) -> None:
        params = Parameters()

        solar_available, wind_available = map_generation_signal_to_available_mw(
            solar_generation_mwh=np.array([0.0, 29_503.0]),
            wind_generation_mwh=np.array([0.0, 28_264.0]),
            params=params,
        )

        np.testing.assert_allclose(
            solar_available,
            np.array([0.0, params.solar_inverter_capacity_mw]),
        )
        np.testing.assert_allclose(
            wind_available,
            np.array([0.0, params.wind_capacity_mw]),
        )


if __name__ == "__main__":
    unittest.main()
