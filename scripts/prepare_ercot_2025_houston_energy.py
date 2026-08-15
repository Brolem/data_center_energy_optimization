from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dc_energy_opt.config import Parameters


DATA_DIRECTORY = PROJECT_ROOT / "data" / "energy"
PAPER_INPUT_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "paper"
    / "ercot_2025_houston_spot_gpu"
    / "day_ahead"
    / "inputs"
)

ERCOT_PRICE_ARCHIVE = "ercot_2025_historical_dam_load_zone_and_hub_prices.zip"
EIA_WORKBOOK = "eia_930_erco_full_history.xlsx"

SOURCE_HASHES = {
    ERCOT_PRICE_ARCHIVE: "30DF71EBB306BBE8C6CC075598D2E5BD47079B8AB9E0442979F3331353618320",
    EIA_WORKBOOK: "0EFF7C52C9014F83EDF83831C21C130E7055DD1DCCE24235369040EFE8AA41E0",
}

ERCOT_PRICE_COLUMNS = (
    "Delivery Date",
    "Hour Ending",
    "Repeated Hour Flag",
    "Settlement Point",
    "Settlement Point Price",
)
EIA_COLUMNS = (
    "BA",
    "UTC time",
    "Local date",
    "Hour",
    "Local time",
    "NG: SUN",
    "NG: WND",
    "CO2 Emissions Intensity for Consumed Electricity",
)
ERCOT_MONTH_SHEETS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
PAPER_WINDOW_STARTS = (
    dt.date(2025, 1, 1),
    dt.date(2025, 4, 1),
    dt.date(2025, 7, 1),
    dt.date(2025, 10, 1),
)
DEFAULT_CLOSURE_HOURS = Parameters().max_delay_h

ANNUAL_COLUMNS = (
    "timestamp_utc",
    "local_date",
    "local_hour",
    "local_time_end",
    "delivery_date",
    "hour_ending",
    "repeated_hour_flag",
    "dam_lz_houston_usd_per_mwh",
    "erco_solar_generation_mwh",
    "erco_wind_generation_mwh",
    "erco_consumed_co2_intensity_lbs_per_kwh",
)
WINDOW_PREFIX_COLUMNS = (
    "window_id",
    "window_hour",
    "is_settlement_closure",
)
WINDOW_COLUMNS = WINDOW_PREFIX_COLUMNS + ANNUAL_COLUMNS

XLSX_NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELATIONSHIPS_NAMESPACE = "{http://schemas.openxmlformats.org/package/2006/relationships}"
OFFICE_RELATIONSHIP = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
COLUMN_REFERENCE = re.compile(r"([A-Z]+)[0-9]+$")
CSV_LINETERMINATOR = "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _validated_source_paths(source_directory: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for filename, expected_hash in SOURCE_HASHES.items():
        path = source_directory / filename
        if not path.is_file():
            raise FileNotFoundError(f"missing raw energy source: {path}")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"{filename} SHA-256 mismatch: {actual_hash} != {expected_hash}"
            )
        paths[filename] = path
    return paths


def _shared_strings(archive: ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(text.text or "" for text in item.iter(f"{XLSX_NAMESPACE}t"))
        for item in root.findall(f"{XLSX_NAMESPACE}si")
    ]


def _worksheet_path(archive: ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall(
            f"{RELATIONSHIPS_NAMESPACE}Relationship"
        )
    }
    for sheet in workbook.findall(f"{XLSX_NAMESPACE}sheets/{XLSX_NAMESPACE}sheet"):
        if sheet.attrib.get("name") != sheet_name:
            continue
        relationship_id = sheet.attrib.get(f"{OFFICE_RELATIONSHIP}id")
        if relationship_id is None or relationship_id not in targets:
            raise ValueError(f"worksheet relationship missing for {sheet_name}")
        target = targets[relationship_id].lstrip("/")
        if target.startswith("xl/"):
            return target
        return f"xl/{target}"
    raise ValueError(f"worksheet not found: {sheet_name}")


def _column_index(cell_reference: str) -> int:
    match = COLUMN_REFERENCE.fullmatch(cell_reference)
    if match is None:
        raise ValueError(f"invalid XLSX cell reference: {cell_reference}")
    result = 0
    for letter in match.group(1):
        result = result * 26 + ord(letter) - ord("A") + 1
    return result - 1


def _cell_value(cell: ET.Element, shared_strings: Sequence[str]) -> str | float | None:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(
            text.text or "" for text in cell.iter(f"{XLSX_NAMESPACE}t")
        )
    value = cell.find(f"{XLSX_NAMESPACE}v")
    if value is None or value.text is None:
        return None
    if cell_type == "s":
        try:
            return shared_strings[int(value.text)]
        except (IndexError, ValueError) as error:
            raise ValueError("invalid shared-string index") from error
    if cell_type in ("str", "b", "e"):
        return value.text
    try:
        return float(value.text)
    except ValueError:
        return value.text


def _row_cells(row: ET.Element, shared_strings: Sequence[str]) -> dict[int, str | float]:
    cells: dict[int, str | float] = {}
    for cell in row.findall(f"{XLSX_NAMESPACE}c"):
        reference = cell.attrib.get("r")
        if reference is None:
            raise ValueError("XLSX cell is missing its reference")
        value = _cell_value(cell, shared_strings)
        if value is not None:
            cells[_column_index(reference)] = value
    return cells


def iter_xlsx_rows(
    source: Path | BytesIO,
    sheet_name: str,
    *,
    columns: Iterable[str] | None = None,
) -> Iterator[dict[str, str | float]]:
    """Yield non-empty data rows from one named XLSX worksheet."""
    if isinstance(source, BytesIO):
        source.seek(0)
    with ZipFile(source) as archive:
        shared_strings = _shared_strings(archive)
        worksheet_path = _worksheet_path(archive, sheet_name)
        header_by_index: dict[int, str] | None = None
        selected_columns = set(columns) if columns is not None else None
        with archive.open(worksheet_path) as worksheet_file:
            for _, element in ET.iterparse(worksheet_file, events=("end",)):
                if element.tag != f"{XLSX_NAMESPACE}row":
                    continue
                cells = _row_cells(element, shared_strings)
                if header_by_index is None:
                    header_by_index = {
                        index: str(value) for index, value in cells.items()
                    }
                    if selected_columns is not None:
                        missing = selected_columns.difference(
                            header_by_index.values()
                        )
                        if missing:
                            raise ValueError(
                                f"{sheet_name} is missing columns: {sorted(missing)}"
                            )
                    element.clear()
                    continue
                row = {
                    header: value
                    for index, value in cells.items()
                    if (header := header_by_index.get(index)) is not None
                    and (selected_columns is None or header in selected_columns)
                }
                if row:
                    yield row
                element.clear()
        if header_by_index is None:
            raise ValueError(f"worksheet has no header row: {sheet_name}")


def excel_serial_to_datetime(value: float) -> dt.datetime:
    return dt.datetime(1899, 12, 30) + dt.timedelta(days=value)


def _numeric(value: str | float, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _xlsx_payload_from_archive(path: Path) -> BytesIO:
    with ZipFile(path) as archive:
        workbook_names = [
            name
            for name in archive.namelist()
            if not name.endswith("/") and name.lower().endswith(".xlsx")
        ]
        if len(workbook_names) != 1:
            raise ValueError(
                f"{path.name} must contain exactly one XLSX workbook, found {workbook_names}"
            )
        return BytesIO(archive.read(workbook_names[0]))


def load_ercot_price_rows(price_archive: Path) -> list[dict[str, object]]:
    payload = _xlsx_payload_from_archive(price_archive)
    rows: list[dict[str, object]] = []
    for sheet_name in ERCOT_MONTH_SHEETS:
        for source_row in iter_xlsx_rows(
            payload, sheet_name, columns=ERCOT_PRICE_COLUMNS
        ):
            if source_row["Settlement Point"] != "LZ_HOUSTON":
                continue
            delivery_date = dt.datetime.strptime(
                str(source_row["Delivery Date"]), "%m/%d/%Y"
            ).date()
            if delivery_date.year != 2025:
                continue
            rows.append(
                {
                    "delivery_date": delivery_date.isoformat(),
                    "hour_ending": str(source_row["Hour Ending"]),
                    "repeated_hour_flag": str(
                        source_row["Repeated Hour Flag"]
                    ),
                    "dam_lz_houston_usd_per_mwh": _numeric(
                        source_row["Settlement Point Price"],
                        label="ERCOT Settlement Point Price",
                    ),
                }
            )
    if not rows:
        raise ValueError("ERCOT source contains no LZ_HOUSTON rows for 2025")
    return rows


def load_eia_rows(eia_workbook: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source_row in iter_xlsx_rows(
        eia_workbook, "Published Hourly Data", columns=EIA_COLUMNS
    ):
        if source_row["BA"] != "ERCO":
            continue
        utc_time = excel_serial_to_datetime(
            _numeric(source_row["UTC time"], label="EIA UTC time")
        )
        local_date = excel_serial_to_datetime(
            _numeric(source_row["Local date"], label="EIA Local date")
        ).date()
        if local_date.year != 2025:
            continue
        local_time = excel_serial_to_datetime(
            _numeric(source_row["Local time"], label="EIA Local time")
        )
        carbon_intensity = source_row.get(
            "CO2 Emissions Intensity for Consumed Electricity"
        )
        solar_generation = source_row.get("NG: SUN")
        wind_generation = source_row.get("NG: WND")
        rows.append(
            {
                "timestamp_utc": utc_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "local_date": local_date.isoformat(),
                "local_hour": int(
                    _numeric(source_row["Hour"], label="EIA Hour")
                ),
                "local_time_end": local_time.strftime("%H:%M:%S"),
                "erco_solar_generation_mwh": (
                    None
                    if solar_generation in (None, "")
                    else _numeric(solar_generation, label="EIA NG: SUN")
                ),
                "erco_wind_generation_mwh": (
                    None
                    if wind_generation in (None, "")
                    else _numeric(wind_generation, label="EIA NG: WND")
                ),
                "erco_consumed_co2_intensity_lbs_per_kwh": (
                    None
                    if carbon_intensity in (None, "")
                    else _numeric(
                        carbon_intensity,
                        label="EIA consumed CO2 intensity",
                    )
                ),
            }
        )
    if not rows:
        raise ValueError("EIA source contains no ERCO rows for 2025")
    return rows


def _rows_by_local_date(
    rows: Iterable[dict[str, object]], *, date_key: str
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[date_key])].append(row)
    return dict(grouped)


def build_annual_rows(
    price_rows: Iterable[dict[str, object]],
    eia_rows: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    price_by_date = _rows_by_local_date(price_rows, date_key="delivery_date")
    eia_by_date = _rows_by_local_date(eia_rows, date_key="local_date")
    if set(price_by_date) != set(eia_by_date):
        raise ValueError("ERCOT and EIA local-date sets differ")

    annual_rows: list[dict[str, object]] = []
    for local_date in sorted(price_by_date):
        daily_prices = price_by_date[local_date]
        daily_eia = eia_by_date[local_date]
        if len(daily_prices) != len(daily_eia):
            raise ValueError(
                f"record counts differ for local date {local_date}: "
                f"{len(daily_prices)} != {len(daily_eia)}"
            )
        for price, eia in zip(daily_prices, daily_eia, strict=True):
            annual_rows.append(
                {
                    "timestamp_utc": eia["timestamp_utc"],
                    "local_date": eia["local_date"],
                    "local_hour": eia["local_hour"],
                    "local_time_end": eia["local_time_end"],
                    "delivery_date": price["delivery_date"],
                    "hour_ending": price["hour_ending"],
                    "repeated_hour_flag": price["repeated_hour_flag"],
                    "dam_lz_houston_usd_per_mwh": price[
                        "dam_lz_houston_usd_per_mwh"
                    ],
                    "erco_solar_generation_mwh": eia[
                        "erco_solar_generation_mwh"
                    ],
                    "erco_wind_generation_mwh": eia[
                        "erco_wind_generation_mwh"
                    ],
                    "erco_consumed_co2_intensity_lbs_per_kwh": eia[
                        "erco_consumed_co2_intensity_lbs_per_kwh"
                    ],
                }
            )
    return annual_rows


def _utc_timestamp(row: dict[str, object]) -> dt.datetime:
    try:
        return dt.datetime.strptime(
            str(row["timestamp_utc"]), "%Y-%m-%dT%H:%M:%SZ"
        )
    except (KeyError, ValueError) as error:
        raise ValueError("timestamp_utc must use YYYY-MM-DDTHH:MM:SSZ") from error


def validate_annual_rows(rows: Sequence[dict[str, object]]) -> None:
    if len(rows) != 8760:
        raise ValueError(f"annual table must contain 8760 rows, found {len(rows)}")
    timestamps = [_utc_timestamp(row) for row in rows]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("annual timestamp_utc values must be unique and increasing")
    if timestamps[0] != dt.datetime(2025, 1, 1, 7):
        raise ValueError(f"unexpected first 2025 UTC hour: {timestamps[0]}")
    if timestamps[-1] != dt.datetime(2026, 1, 1, 6):
        raise ValueError(f"unexpected final 2025 UTC hour: {timestamps[-1]}")
    for row in rows:
        if tuple(row) != ANNUAL_COLUMNS:
            raise ValueError("annual table columns do not match the formal schema")
        _numeric(row["dam_lz_houston_usd_per_mwh"], label="dam price")
        for column in ANNUAL_COLUMNS[8:]:
            if row[column] not in (None, ""):
                _numeric(row[column], label=column)


def build_paper_window_rows(
    annual_rows: Sequence[dict[str, object]],
    *,
    window_start: dt.date,
    closure_hours: int,
) -> list[dict[str, object]]:
    if closure_hours < 1:
        raise ValueError("closure_hours must be positive")
    window_end = window_start + dt.timedelta(days=30)
    main_rows = [
        row
        for row in annual_rows
        if window_start <= dt.date.fromisoformat(str(row["local_date"])) < window_end
    ]
    if len(main_rows) != 720:
        raise ValueError(
            f"30-day window {window_start.isoformat()} does not contain 720 main hours"
        )
    last_main_timestamp = _utc_timestamp(main_rows[-1])
    annual_index = next(
        (
            index
            for index, row in enumerate(annual_rows)
            if _utc_timestamp(row) == last_main_timestamp
        ),
        None,
    )
    if annual_index is None:
        raise ValueError("main window end is absent from the annual table")
    closure_rows = list(
        annual_rows[annual_index + 1 : annual_index + 1 + closure_hours]
    )
    if len(closure_rows) != closure_hours:
        raise ValueError(
            f"30-day window {window_start.isoformat()} does not contain "
            f"{closure_hours} closure hours"
        )
    selected_rows = [*main_rows, *closure_rows]
    for previous, current in zip(selected_rows, selected_rows[1:], strict=False):
        if _utc_timestamp(current) != _utc_timestamp(previous) + dt.timedelta(hours=1):
            raise ValueError("window UTC timestamps must be consecutive")
    window_id = f"{window_start.isoformat()}_30d_h{closure_hours}h"
    result: list[dict[str, object]] = []
    for window_hour, row in enumerate(selected_rows):
        result.append(
            {
                "window_id": window_id,
                "window_hour": window_hour,
                "is_settlement_closure": "1" if window_hour >= 720 else "0",
                **row,
            }
        )
    return result


def write_csv(path: Path, rows: Sequence[dict[str, object]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=columns,
            lineterminator=CSV_LINETERMINATOR,
        )
        writer.writeheader()
        writer.writerows(rows)


def _relative_to_project(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def generate_inputs(
    *,
    source_directory: Path,
    annual_output: Path,
    paper_input_directory: Path,
    closure_hours: int,
) -> dict[str, object]:
    source_paths = _validated_source_paths(source_directory)
    annual_rows = build_annual_rows(
        load_ercot_price_rows(source_paths[ERCOT_PRICE_ARCHIVE]),
        load_eia_rows(source_paths[EIA_WORKBOOK]),
    )
    validate_annual_rows(annual_rows)
    write_csv(annual_output, annual_rows, ANNUAL_COLUMNS)

    window_outputs: list[Path] = []
    for window_start in PAPER_WINDOW_STARTS:
        window_rows = build_paper_window_rows(
            annual_rows,
            window_start=window_start,
            closure_hours=closure_hours,
        )
        window_output = paper_input_directory / (
            f"{window_start.isoformat()}_30d_h{closure_hours}h_energy.csv"
        )
        write_csv(window_output, window_rows, WINDOW_COLUMNS)
        window_outputs.append(window_output)

    output_paths = [annual_output, *window_outputs]
    manifest = {
        "schema_version": 1,
        "closure_hours": closure_hours,
        "main_window_hours": 720,
        "annual_missing_hours": {
            column: sum(row[column] is None for row in annual_rows)
            for column in ANNUAL_COLUMNS[8:]
        },
        "paper_window_starts": [
            window_start.isoformat() for window_start in PAPER_WINDOW_STARTS
        ],
        "sources": {
            _relative_to_project(path): sha256_file(path)
            for path in source_paths.values()
        },
        "outputs": {
            _relative_to_project(path): sha256_file(path) for path in output_paths
        },
    }
    manifest_path = paper_input_directory / "inputs_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the shared ERCOT 2025 Houston energy table and paper windows."
    )
    parser.add_argument("--source-dir", type=Path, default=DATA_DIRECTORY)
    parser.add_argument(
        "--annual-output",
        type=Path,
        default=DATA_DIRECTORY / "ercot_2025_houston_hourly.csv",
    )
    parser.add_argument(
        "--paper-input-dir", type=Path, default=PAPER_INPUT_DIRECTORY
    )
    parser.add_argument(
        "--closure-hours", type=int, default=DEFAULT_CLOSURE_HOURS
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = generate_inputs(
        source_directory=args.source_dir,
        annual_output=args.annual_output,
        paper_input_directory=args.paper_input_dir,
        closure_hours=args.closure_hours,
    )
    print(
        "generated ERCOT 2025 shared annual table and "
        f"{len(manifest['paper_window_starts'])} paper windows "
        f"with H={manifest['closure_hours']}"
    )


if __name__ == "__main__":
    main()
