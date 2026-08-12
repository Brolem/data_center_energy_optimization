import hashlib
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd

import dc_energy_opt.data as energy_data
from dc_energy_opt.config import Parameters
from dc_energy_opt.data.energy import load_houston_energy_scenario, paper_tou_tariff
from scripts import prepare_houston_2020_energy
from scripts.prepare_houston_2020_energy import (
    _load_ge_turbine,
    _sha256_normalized_text,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOUSTON_SCENARIO_PATH = (
    PROJECT_ROOT / "data" / "energy" / "houston_2020_may_hourly.csv"
)


class HoustonEnergyScenarioTests(unittest.TestCase):
    def test_source_hash_normalizes_only_crlf_line_endings(self) -> None:
        content_lf = b"first line\nsecond line\n"
        expected = hashlib.sha256(content_lf).hexdigest().upper()
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            lf_path = root / "lf.txt"
            crlf_path = root / "crlf.txt"
            lf_path.write_bytes(content_lf)
            crlf_path.write_bytes(content_lf.replace(b"\n", b"\r\n"))

            self.assertEqual(_sha256_normalized_text(lf_path), expected)
            self.assertEqual(_sha256_normalized_text(crlf_path), expected)

    def _valid_scenario(self) -> pd.DataFrame:
        timestamps = pd.date_range(
            "2020-04-30 00:00:00",
            "2020-05-29 02:00:00",
            freq="h",
        )
        periods, prices = energy_data.paper_tou_tariff(
            timestamps.hour.to_numpy()
        )
        return pd.DataFrame(
            {
                "timestamp_lst": timestamps.strftime("%Y-%m-%dT%H:%M:%S"),
                "solar_available_mw": np.zeros(len(timestamps)),
                "wind_available_mw": np.zeros(len(timestamps)),
                "tou_period": periods,
                "electricity_price_cny_per_kwh": prices,
            }
        )

    def test_loader_accepts_exact_main_window_schema_and_tariff(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            scenario_path = Path(temporary_directory) / "houston.csv"
            self._valid_scenario().to_csv(scenario_path, index=False)

            scenario = energy_data.load_houston_energy_scenario(
                scenario_path,
                Parameters(),
            )

        self.assertEqual(len(scenario), 699)
        self.assertEqual(
            list(scenario.columns),
            [
                "timestamp_lst",
                "solar_available_mw",
                "wind_available_mw",
                "tou_period",
                "electricity_price_cny_per_kwh",
            ],
        )
        self.assertEqual(scenario.loc[0, "tou_period"], "valley")
        self.assertEqual(
            scenario.loc[0, "electricity_price_cny_per_kwh"],
            0.1804,
        )

    def test_loader_rejects_capacity_and_timestamp_violations(self) -> None:
        invalid_scenarios = {}
        solar_over_capacity = self._valid_scenario()
        solar_over_capacity.loc[0, "solar_available_mw"] = (
            Parameters().solar_inverter_capacity_mw + 0.001
        )
        invalid_scenarios["solar"] = solar_over_capacity

        wind_over_capacity = self._valid_scenario()
        wind_over_capacity.loc[0, "wind_available_mw"] = 6.601
        invalid_scenarios["wind"] = wind_over_capacity

        missing_hour = self._valid_scenario().drop(index=1)
        invalid_scenarios["timestamp"] = missing_hour

        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            for label, invalid_scenario in invalid_scenarios.items():
                with self.subTest(label=label):
                    scenario_path = temporary_path / f"{label}.csv"
                    invalid_scenario.to_csv(scenario_path, index=False)
                    with self.assertRaises(ValueError):
                        energy_data.load_houston_energy_scenario(
                            scenario_path,
                            Parameters(),
                        )

    def test_committed_houston_scenario_is_complete(self) -> None:
        scenario = energy_data.load_houston_energy_scenario(
            HOUSTON_SCENARIO_PATH,
            Parameters(),
        )

        self.assertEqual(len(scenario), 699)
        self.assertGreater(scenario["solar_available_mw"].sum(), 0.0)
        self.assertGreater(scenario["wind_available_mw"].sum(), 0.0)

    def test_turbine_loader_skips_unrelated_malformed_rows(self) -> None:
        catalog = "\n".join(
            [
                "Name,kW Rating,Rotor Diameter,IEC Wind Speed Class,Wind Speed Array,Power Curve Array",
                "units,units,units,units,units,units",
                "metadata,metadata,metadata,metadata,metadata,metadata",
                "Broken,row,with,too,many,fields,ignored",
                "GE 1.5sle,1500,77,IIa,0|1|2,0|0|1500",
            ]
        )
        with TemporaryDirectory() as temporary_directory:
            catalog_path = Path(temporary_directory) / "Wind_Turbines.csv"
            catalog_path.write_text(catalog, encoding="utf-8")

            turbine = _load_ge_turbine(catalog_path)

        self.assertEqual(turbine["Name"], "GE 1.5sle")
        self.assertEqual(turbine["kW Rating"], 1500)
        self.assertEqual(turbine["Rotor Diameter"], 77)


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
