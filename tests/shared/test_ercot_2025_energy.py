import datetime as dt
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from dc_energy_opt.config import Parameters
from scripts import prepare_ercot_2025_houston_energy as preparation


def _price_row(
    delivery_date: str,
    hour_ending: str,
    repeated_hour_flag: str,
    price: float,
) -> dict[str, object]:
    return {
        "delivery_date": delivery_date,
        "hour_ending": hour_ending,
        "repeated_hour_flag": repeated_hour_flag,
        "dam_lz_houston_usd_per_mwh": price,
    }


def _eia_row(
    local_date: str,
    local_hour: int,
    timestamp_utc: str,
    local_time_end: str,
    carbon_intensity: float | None = 0.8,
) -> dict[str, object]:
    return {
        "local_date": local_date,
        "local_hour": local_hour,
        "timestamp_utc": timestamp_utc,
        "local_time_end": local_time_end,
        "erco_solar_generation_mwh": 10.0 + local_hour,
        "erco_wind_generation_mwh": 20.0 + local_hour,
        "erco_consumed_co2_intensity_lbs_per_kwh": carbon_intensity,
    }


class Ercot2025AnnualMergeTests(unittest.TestCase):
    def test_merges_same_local_date_by_source_sequence(self) -> None:
        rows = preparation.build_annual_rows(
            [
                _price_row("2025-01-01", "01:00", "N", 20.0),
                _price_row("2025-01-01", "02:00", "N", 30.0),
            ],
            [
                _eia_row("2025-01-01", 1, "2025-01-01T07:00:00Z", "01:00"),
                _eia_row("2025-01-01", 2, "2025-01-01T08:00:00Z", "02:00"),
            ],
        )

        self.assertEqual(list(rows[0]), list(preparation.ANNUAL_COLUMNS))
        self.assertEqual(rows[0]["timestamp_utc"], "2025-01-01T07:00:00Z")
        self.assertEqual(rows[0]["hour_ending"], "01:00")
        self.assertEqual(rows[1]["dam_lz_houston_usd_per_mwh"], 30.0)
        self.assertEqual(rows[1]["erco_solar_generation_mwh"], 12.0)

    def test_spring_dst_short_day_keeps_all_23_source_hours(self) -> None:
        price_rows = [
            _price_row("2025-03-09", f"{hour:02d}:00", "N", float(hour))
            for hour in [1, 2, *range(4, 25)]
        ]
        eia_rows = [
            _eia_row(
                "2025-03-09",
                hour,
                f"2025-03-09T{hour + 6:02d}:00:00Z",
                f"{hour:02d}:00",
            )
            for hour in range(1, 24)
        ]

        rows = preparation.build_annual_rows(price_rows, eia_rows)

        self.assertEqual(len(rows), 23)
        self.assertEqual(rows[1]["hour_ending"], "02:00")
        self.assertEqual(rows[2]["hour_ending"], "04:00")
        self.assertEqual(rows[-1]["local_hour"], 23)

    def test_fall_dst_repeated_hour_preserves_ercot_record_order(self) -> None:
        price_rows = [
            _price_row("2025-11-02", "01:00", "N", 11.0),
            _price_row("2025-11-02", "02:00", "N", 22.0),
            _price_row("2025-11-02", "02:00", "Y", 33.0),
        ]
        eia_rows = [
            _eia_row("2025-11-02", 1, "2025-11-02T06:00:00Z", "01:00"),
            _eia_row("2025-11-02", 2, "2025-11-02T07:00:00Z", "01:00"),
            _eia_row("2025-11-02", 3, "2025-11-02T08:00:00Z", "02:00"),
        ]

        rows = preparation.build_annual_rows(price_rows, eia_rows)

        self.assertEqual(
            [row["timestamp_utc"] for row in rows],
            [
                "2025-11-02T06:00:00Z",
                "2025-11-02T07:00:00Z",
                "2025-11-02T08:00:00Z",
            ],
        )
        self.assertEqual(
            [row["repeated_hour_flag"] for row in rows], ["N", "N", "Y"]
        )
        self.assertEqual(
            [row["dam_lz_houston_usd_per_mwh"] for row in rows],
            [11.0, 22.0, 33.0],
        )

    def test_rejects_unequal_daily_record_counts(self) -> None:
        with self.assertRaisesRegex(ValueError, "record counts"):
            preparation.build_annual_rows(
                [_price_row("2025-01-01", "01:00", "N", 20.0)],
                [
                    _eia_row(
                        "2025-01-01",
                        1,
                        "2025-01-01T07:00:00Z",
                        "01:00",
                    ),
                    _eia_row(
                        "2025-01-01",
                        2,
                        "2025-01-01T08:00:00Z",
                        "02:00",
                    ),
                ],
            )

    def test_rejects_different_local_date_sets(self) -> None:
        with self.assertRaisesRegex(ValueError, "local-date sets"):
            preparation.build_annual_rows(
                [_price_row("2025-01-01", "01:00", "N", 20.0)],
                [
                    _eia_row(
                        "2025-01-02",
                        1,
                        "2025-01-02T07:00:00Z",
                        "01:00",
                    )
                ],
            )

    def test_preserves_unpublished_consumed_carbon_intensity_as_blank(self) -> None:
        rows = preparation.build_annual_rows(
            [_price_row("2025-12-03", "01:00", "N", 20.0)],
            [
                _eia_row(
                    "2025-12-03",
                    1,
                    "2025-12-03T07:00:00Z",
                    "01:00",
                    carbon_intensity=None,
                )
            ],
        )

        self.assertIsNone(
            rows[0]["erco_consumed_co2_intensity_lbs_per_kwh"]
        )


class Ercot2025WindowTests(unittest.TestCase):
    def test_default_closure_hours_uses_formal_maximum_delay(self) -> None:
        self.assertEqual(
            preparation.DEFAULT_CLOSURE_HOURS,
            Parameters().max_delay_h,
        )

    def test_fixed_window_has_720_main_hours_and_h_closure_hours(self) -> None:
        start = dt.datetime(2025, 1, 1)
        annual_rows = []
        for hour in range(723):
            current = start + dt.timedelta(hours=hour)
            annual_rows.append(
                {
                    "timestamp_utc": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "local_date": current.strftime("%Y-%m-%d"),
                }
            )

        rows = preparation.build_paper_window_rows(
            annual_rows,
            window_start=dt.date(2025, 1, 1),
            closure_hours=3,
        )

        self.assertEqual(len(rows), 723)
        self.assertEqual(sum(row["is_settlement_closure"] == "0" for row in rows), 720)
        self.assertEqual(sum(row["is_settlement_closure"] == "1" for row in rows), 3)
        self.assertEqual(rows[0]["window_hour"], 0)
        self.assertEqual(rows[719]["window_hour"], 719)
        self.assertEqual(rows[720]["timestamp_utc"], "2025-01-31T00:00:00Z")
        self.assertEqual(rows[-1]["window_hour"], 722)

    def test_rejects_short_closure(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not contain"):
            preparation.build_paper_window_rows(
                [
                    {
                        "timestamp_utc": "2025-01-01T00:00:00Z",
                        "local_date": "2025-01-01",
                    }
                ],
                window_start=dt.date(2025, 1, 1),
                closure_hours=3,
            )


class Ercot2025AnnualValidationTests(unittest.TestCase):
    def test_allows_unpublished_carbon_intensity_without_imputation(self) -> None:
        start = dt.datetime(2025, 1, 1, 7)
        rows = []
        for offset in range(8760):
            timestamp = start + dt.timedelta(hours=offset)
            rows.append(
                {
                    "timestamp_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "local_date": "2025-01-01",
                    "local_hour": 1,
                    "local_time_end": "01:00:00",
                    "delivery_date": "2025-01-01",
                    "hour_ending": "01:00",
                    "repeated_hour_flag": "N",
                    "dam_lz_houston_usd_per_mwh": 20.0,
                    "erco_solar_generation_mwh": 10.0,
                    "erco_wind_generation_mwh": 20.0,
                    "erco_consumed_co2_intensity_lbs_per_kwh": None,
                }
            )

        preparation.validate_annual_rows(rows)


class EiaMissingValueTests(unittest.TestCase):
    def test_preserves_unpublished_renewable_and_carbon_values_as_blank(self) -> None:
        source_row = {
            "BA": "ERCO",
            "UTC time": 45658.2916666667,
            "Local date": 45658.0,
            "Hour": 1.0,
            "Local time": 45658.0416666667,
        }
        with patch.object(
            preparation,
            "iter_xlsx_rows",
            return_value=iter([source_row]),
        ):
            rows = preparation.load_eia_rows(Path("unused.xlsx"))

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["erco_solar_generation_mwh"])
        self.assertIsNone(rows[0]["erco_wind_generation_mwh"])
        self.assertIsNone(
            rows[0]["erco_consumed_co2_intensity_lbs_per_kwh"]
        )

    def test_selects_2025_by_eia_local_date_not_utc_year(self) -> None:
        source_rows = [
            {
                "BA": "ERCO",
                "UTC time": 45658.2916666667,
                "Local date": 45657.0,
                "Hour": 24.0,
                "Local time": 45658.0,
                "NG: SUN": 1.0,
                "NG: WND": 2.0,
                "CO2 Emissions Intensity for Consumed Electricity": 0.7,
            },
            {
                "BA": "ERCO",
                "UTC time": 46023.25,
                "Local date": 46022.0,
                "Hour": 24.0,
                "Local time": 46023.0,
                "NG: SUN": 3.0,
                "NG: WND": 4.0,
                "CO2 Emissions Intensity for Consumed Electricity": 0.6,
            },
        ]
        with patch.object(
            preparation,
            "iter_xlsx_rows",
            return_value=iter(source_rows),
        ):
            rows = preparation.load_eia_rows(Path("unused.xlsx"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["local_date"], "2025-12-31")
        self.assertEqual(rows[0]["timestamp_utc"], "2026-01-01T06:00:00Z")


class MinimalXlsxReaderTests(unittest.TestCase):
    def test_reads_shared_strings_and_numeric_cells_by_sheet_name(self) -> None:
        workbook_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets><sheet name=\"Data\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>"""
        relationships_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/></Relationships>"""
        shared_strings_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><si><t>BA</t></si><si><t>Value</t></si><si><t>ERCO</t></si></sst>"""
        sheet_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData><row r=\"1\"><c r=\"A1\" t=\"s\"><v>0</v></c><c r=\"B1\" t=\"s\"><v>1</v></c></row><row r=\"2\"><c r=\"A2\" t=\"s\"><v>2</v></c><c r=\"B2\"><v>42</v></c></row></sheetData></worksheet>"""
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "source.xlsx"
            with ZipFile(path, "w", ZIP_DEFLATED) as archive:
                archive.writestr("xl/workbook.xml", workbook_xml)
                archive.writestr("xl/_rels/workbook.xml.rels", relationships_xml)
                archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
                archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)

            rows = list(preparation.iter_xlsx_rows(path, "Data"))

        self.assertEqual(rows, [{"BA": "ERCO", "Value": 42.0}])

    def test_converts_excel_datetime_serial(self) -> None:
        self.assertEqual(
            preparation.excel_serial_to_datetime(45658.0),
            dt.datetime(2025, 1, 1),
        )


class GeneratorCommandTests(unittest.TestCase):
    def test_direct_script_command_resolves_project_imports(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_ercot_2025_houston_energy.py",
                "--help",
            ],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--closure-hours", result.stdout)
