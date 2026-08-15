from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from dc_energy_opt.config import Parameters
from dc_energy_opt.optimization.market_window import (
    build_and_solve_market_window,
)


class MarketSettlementWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.params = replace(Parameters(), time_limit_s=10.0)
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_directory = Path(self.temporary_directory.name)

    def solve(
        self,
        *,
        workload_arrival_pu: np.ndarray,
        solar_available_mw: np.ndarray,
        wind_available_mw: np.ndarray,
        price_usd_per_mwh: np.ndarray,
        enable_shift: bool = False,
        enable_storage: bool = False,
        terminal_stored_energy_mwh: float | None = None,
    ) -> tuple:
        return build_and_solve_market_window(
            workload_arrival_pu=workload_arrival_pu,
            solar_available_mw=solar_available_mw,
            wind_available_mw=wind_available_mw,
            price_usd_per_mwh=price_usd_per_mwh,
            params=self.params,
            enable_shift=enable_shift,
            enable_storage=enable_storage,
            case_name="market_window_test",
            lp_output_dir=self.output_directory,
            show_log=False,
            terminal_stored_energy_mwh=terminal_stored_energy_mwh,
        )

    def test_settles_grid_energy_in_usd_and_accepts_negative_price(self) -> None:
        result, metrics = self.solve(
            workload_arrival_pu=np.array([0.10, 0.10, 0.10]),
            solar_available_mw=np.zeros(3),
            wind_available_mw=np.zeros(3),
            price_usd_per_mwh=np.array([-10.0, 20.0, 30.0]),
        )

        expected_settlement = float(
            (result["price_usd_per_mwh"] * result["grid_power_mw"]).sum()
        )
        self.assertAlmostEqual(metrics["grid_settlement_usd"], expected_settlement)
        self.assertLess(result.loc[0, "price_usd_per_mwh"], 0.0)
        self.assertTrue(
            (result["hourly_grid_settlement_usd"] == (
                result["price_usd_per_mwh"] * result["grid_power_mw"]
            )).all()
        )
        self.assertFalse(
            any("_cny_" in key for key in [*result.columns, *metrics])
        )
        self.assertTrue((self.output_directory / "stage_1_settlement.lp").is_file())
        self.assertTrue((self.output_directory / "stage_2_delay.lp").is_file())
        self.assertTrue((self.output_directory / "stage_3_curtailment.lp").is_file())
        self.assertTrue((self.output_directory / "stage_4_throughput.lp").is_file())

    def test_storage_power_balance_and_terminal_energy_hold(self) -> None:
        terminal_energy = (
            self.params.battery_soc_initial * self.params.battery_energy_mwh
        )
        result, metrics = self.solve(
            workload_arrival_pu=np.array([0.10, 0.10, 0.10]),
            solar_available_mw=np.array([0.0, 2.0, 0.0]),
            wind_available_mw=np.zeros(3),
            price_usd_per_mwh=np.array([100.0, 10.0, 100.0]),
            enable_storage=True,
            terminal_stored_energy_mwh=terminal_energy,
        )

        np.testing.assert_allclose(
            result["grid_power_mw"]
            + result["solar_used_mw"]
            + result["wind_used_mw"]
            + result["discharge_mw"],
            result["dc_power_mw"] + result["charge_mw"],
        )
        self.assertLessEqual(
            (result["charge_mw"] * result["discharge_mw"]).max(), 1e-8
        )
        self.assertAlmostEqual(
            result["stored_energy_end_mwh"].iloc[-1], terminal_energy
        )
        self.assertAlmostEqual(metrics["maximum_work_delay_h"], 0.0)

    def test_rejects_profile_length_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "长度"):
            self.solve(
                workload_arrival_pu=np.array([0.10, 0.10, 0.10]),
                solar_available_mw=np.zeros(2),
                wind_available_mw=np.zeros(3),
                price_usd_per_mwh=np.array([10.0, 20.0, 30.0]),
            )


if __name__ == "__main__":
    unittest.main()
