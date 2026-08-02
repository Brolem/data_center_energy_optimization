import unittest
from pathlib import Path

from dc_energy_opt.config import Parameters
from dc_energy_opt.data.energy import load_houston_energy_scenario, paper_tou_tariff


class EnergyDataTests(unittest.TestCase):
    def test_committed_houston_file_has_exact_main_window(self) -> None:
        rows = load_houston_energy_scenario(
            Path("data/energy/houston_2020_may_hourly.csv"),
            Parameters(),
        )

        self.assertEqual(len(rows), 699)
        self.assertEqual(str(rows.iloc[0]["timestamp_lst"]), "2020-04-30 00:00:00")
        self.assertEqual(str(rows.iloc[-1]["timestamp_lst"]), "2020-05-29 02:00:00")

    def test_paper_tariff_preserves_exact_prices(self) -> None:
        periods, prices = paper_tou_tariff([0, 8, 9, 13, 18, 23])

        self.assertEqual(
            periods.tolist(),
            ["valley", "flat", "peak", "flat", "peak", "flat"],
        )
        self.assertEqual(
            prices.tolist(),
            [0.1804, 0.4489, 0.7174, 0.4489, 0.7174, 0.4489],
        )
