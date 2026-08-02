from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import PySAM.Pvwattsv8
import PySAM.Windpower


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dc_energy_opt.config import Parameters
from dc_energy_opt.data import (
    HOUSTON_ENERGY_SCENARIO_COLUMNS,
    _qinghai_tou,
)


SOURCE_HASHES = {
    "wind_data_houston.csv": (
        "10FB3E98B9773039943B5A56B4122BC75BE00D936B4B1D16608D43E4DE8F008F"
    ),
    "29.76_-95.37_psm3-5min_5_2020.csv": (
        "832D8BA81310D39C5E662ADA8454EC479432EE1077E85CB0944905F521770A9A"
    ),
    "pvwatts_config.json": (
        "8530FA2692E9535548EF6A5C25CABCFE540D06584874557967DF4F133A1DD81D"
    ),
    "windpower_config.json": (
        "E5841B843F59EF69A3B98394ED77B32776F45F5CF795EC7644A133FDC61520E4"
    ),
    "Wind_Turbines.csv": (
        "DCFBF9149A82DCE3EAA1DE07002EDE19C73E4EEA31456109ECEACAF27FC0B2C1"
    ),
}


def _sha256_normalized_text(path: Path) -> str:
    normalized_bytes = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized_bytes).hexdigest().upper()


def _validated_source_paths(source_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for filename, expected_hash in SOURCE_HASHES.items():
        path = source_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"缺少 Houston 原始文件: {path}")
        actual_hash = _sha256_normalized_text(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"{filename} SHA-256 不一致: {actual_hash} != {expected_hash}"
            )
        paths[filename] = path
    return paths


def _set_sam_values(model: object, values: dict[str, object]) -> None:
    ignored = {
        "number_inputs",
        "solar_resource_file",
        "wind_resource_filename",
    }
    for name, value in values.items():
        if name not in ignored:
            model.value(name, value)


def _timestamps_from_weather(path: Path, *, skiprows: int) -> pd.DatetimeIndex:
    weather = pd.read_csv(path, skiprows=skiprows)
    timestamps = pd.DatetimeIndex(
        pd.to_datetime(
            weather[["Year", "Month", "Day", "Hour", "Minute"]],
            errors="raise",
        ),
        name="timestamp_lst",
    )
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError(f"{path.name} 的时间戳必须唯一且递增。")
    experiment_timestamps = timestamps[
        (timestamps >= pd.Timestamp("2020-04-30 00:00:00"))
        & (timestamps <= pd.Timestamp("2020-05-29 02:55:00"))
    ]
    expected = pd.date_range(
        "2020-04-30 00:00:00",
        "2020-05-29 02:55:00",
        freq="5min",
        name="timestamp_lst",
    )
    if not experiment_timestamps.equals(expected):
        raise ValueError(f"{path.name} 的主实验五分钟时间段不连续。")
    return timestamps


def _solar_power_mw(paths: dict[str, Path], params: Parameters) -> pd.Series:
    weather_path = paths["29.76_-95.37_psm3-5min_5_2020.csv"]
    timestamps = _timestamps_from_weather(weather_path, skiprows=2)
    model = PySAM.Pvwattsv8.default("PVWattsNone")
    model.SolarResource.solar_resource_file = str(weather_path)
    with paths["pvwatts_config.json"].open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    config["system_capacity"] = params.solar_capacity_mw * 1000.0
    config["dc_ac_ratio"] = params.solar_dc_ac_ratio
    _set_sam_values(model, config)
    model.execute()
    power_mw = np.asarray(model.Outputs.gen, dtype=float) / 1000.0
    if len(power_mw) != len(timestamps):
        raise ValueError("PVWatts 输出长度与太阳能气象数据不一致。")
    power_mw = np.clip(power_mw, 0.0, params.solar_inverter_capacity_mw)
    return pd.Series(power_mw, index=timestamps, name="solar_available_mw")


def _load_ge_turbine(catalog_path: Path) -> dict[str, object]:
    with catalog_path.open(encoding="utf-8-sig", newline="") as catalog_file:
        rows = csv.reader(catalog_file)
        header = next(rows)
        next(rows)
        next(rows)
        matches = [
            dict(zip(header, row, strict=True))
            for row in rows
            if row and row[0] == "GE 1.5sle" and len(row) == len(header)
        ]
    if len(matches) != 1:
        raise ValueError("Wind_Turbines.csv 必须恰好包含一条 GE 1.5sle。")
    match = matches[0]
    match["kW Rating"] = float(match["kW Rating"])
    match["Rotor Diameter"] = float(match["Rotor Diameter"])
    return match


def _wind_power_mw(paths: dict[str, Path], params: Parameters) -> pd.Series:
    weather_path = paths["wind_data_houston.csv"]
    timestamps = _timestamps_from_weather(weather_path, skiprows=1)
    turbine = _load_ge_turbine(paths["Wind_Turbines.csv"])
    rated_power_kw = float(turbine["kW Rating"])
    rotor_diameter_m = float(turbine["Rotor Diameter"])
    wind_speeds = [
        float(value)
        for value in str(turbine["Wind Speed Array"]).split("|")
    ]
    power_curve_kw = [
        float(value)
        for value in str(turbine["Power Curve Array"]).split("|")
    ]

    model = PySAM.Windpower.default("WindPowerNone")
    model.Resource.wind_resource_filename = str(weather_path)
    with paths["windpower_config.json"].open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    config.update(
        {
            "system_capacity": rated_power_kw,
            "wind_turbine_powercurve_windspeeds": wind_speeds,
            "wind_turbine_powercurve_powerout": power_curve_kw,
            "wind_turbine_rotor_diameter": rotor_diameter_m,
            "wind_farm_xCoordinates": [0.0],
            "wind_farm_yCoordinates": [0.0],
        }
    )
    _set_sam_values(model, config)
    model.execute()
    reference_power_kw = np.asarray(model.Outputs.gen, dtype=float)
    if len(reference_power_kw) != len(timestamps):
        raise ValueError("Windpower 输出长度与风电气象数据不一致。")
    capacity_factor = np.clip(reference_power_kw / rated_power_kw, 0.0, 1.0)
    return pd.Series(
        capacity_factor * params.wind_capacity_mw,
        index=timestamps,
        name="wind_available_mw",
    )


def build_scenario(source_dir: Path, params: Parameters) -> pd.DataFrame:
    paths = _validated_source_paths(source_dir)
    five_minute = pd.concat(
        [_solar_power_mw(paths, params), _wind_power_mw(paths, params)],
        axis=1,
    )
    hourly = five_minute.resample("h").mean().loc[
        "2020-04-30 00:00:00":"2020-05-29 02:00:00"
    ]
    if len(hourly) != 699 or hourly.isna().any().any():
        raise ValueError("Houston 主实验小时场景必须包含 699 行且无缺失值。")
    periods, prices = _qinghai_tou(hourly.index.hour.to_numpy(dtype=int))
    scenario = hourly.reset_index()
    scenario["timestamp_lst"] = scenario["timestamp_lst"].dt.strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    scenario["tou_period"] = periods
    scenario["electricity_price_cny_per_kwh"] = prices
    return scenario[HOUSTON_ENERGY_SCENARIO_COLUMNS]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从论文配套五分钟数据生成 Houston 2020 小时能源场景。"
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_ROOT
            / "data"
            / "houston_2020_main_experiment_energy_scenario.csv"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenario = build_scenario(args.source_dir, Parameters())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scenario.to_csv(args.output, index=False)
    print(
        f"wrote {len(scenario)} rows to {args.output} "
        f"(solar_max={scenario['solar_available_mw'].max():.6f} MW, "
        f"wind_max={scenario['wind_available_mw'].max():.6f} MW)"
    )


if __name__ == "__main__":
    main()
