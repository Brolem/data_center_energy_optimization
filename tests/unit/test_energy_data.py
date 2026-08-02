import hashlib
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from dc_energy_opt.config import Parameters
from dc_energy_opt.data.energy import load_houston_energy_scenario, paper_tou_tariff
from scripts import prepare_houston_2020_energy


class EnergyDataTests(unittest.TestCase):
    def test_gitattributes_preserves_both_formal_csv_byte_sequences(self) -> None:
        lines = Path(".gitattributes").read_text(encoding="utf-8").splitlines()

        self.assertEqual(
            lines,
            [
                "data/workload/google_2019_28d_5min.csv -text",
                "data/energy/houston_2020_may_hourly.csv -text -diff",
            ],
        )

    def test_gitattributes_sets_both_energy_byte_attributes(self) -> None:
        lines = Path(".gitattributes").read_text(encoding="utf-8").splitlines()
        tokens = lines[1].split()

        self.assertEqual(tokens[0], "data/energy/houston_2020_may_hourly.csv")
        self.assertEqual(set(tokens[1:]), {"-text", "-diff"})

    def test_committed_houston_file_preserves_raw_sha256(self) -> None:
        path = Path("data/energy/houston_2020_may_hourly.csv")

        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            "1E075995C24141BA358B0452EE829C6006FAB25B3E83C6868587EDD837BDD7E0",
        )

    def test_houston_generator_declares_crlf_line_terminator(self) -> None:
        self.assertEqual(
            prepare_houston_2020_energy.CSV_LINETERMINATOR,
            "\r\n",
        )

    def test_houston_generator_writes_csv_with_explicit_crlf(self) -> None:
        scenario = pd.DataFrame(
            {
                "solar_available_mw": [1.0],
                "wind_available_mw": [2.0],
            }
        )
        with TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "houston.csv"
            with (
                patch.object(
                    prepare_houston_2020_energy,
                    "parse_args",
                    return_value=Namespace(
                        source_dir=Path("unused"),
                        output=output_path,
                    ),
                ),
                patch.object(
                    prepare_houston_2020_energy,
                    "build_scenario",
                    return_value=scenario,
                ),
                patch.object(pd.DataFrame, "to_csv") as to_csv,
                patch("builtins.print"),
            ):
                prepare_houston_2020_energy.main()

        to_csv.assert_called_once_with(
            output_path,
            index=False,
            lineterminator="\r\n",
        )

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
