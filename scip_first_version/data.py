from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import Parameters


ENERGY_SCENARIO_COLUMNS = [
    "hour",
    "solar_irradiance_wh_m2",
    "wind_speed_50m_m_s",
    "solar_available_mw",
    "wind_available_mw",
    "tou_period",
    "electricity_price_cny_per_kwh",
]

WEATHER_SOURCE_COLUMNS = [
    "timestamp_lst",
    "solar_irradiance_wh_m2",
    "wind_speed_50m_m_s",
]

HOUSTON_ENERGY_SCENARIO_COLUMNS = [
    "timestamp_lst",
    "solar_available_mw",
    "wind_available_mw",
    "tou_period",
    "electricity_price_cny_per_kwh",
]


def load_phoenix_weather_source(csv_path: Path) -> pd.DataFrame:
    source = pd.read_csv(csv_path)
    if list(source.columns) != WEATHER_SOURCE_COLUMNS:
        raise ValueError(
            "Phoenix 气象源字段应严格为: "
            f"{WEATHER_SOURCE_COLUMNS}"
        )
    if len(source) != 672:
        raise ValueError("Phoenix 气象源必须恰好包含 672 个小时。")
    if source.isna().any().any():
        raise ValueError("Phoenix 气象源存在缺失值。")

    source = source.copy()
    try:
        source["timestamp_lst"] = pd.to_datetime(
            source["timestamp_lst"],
            format="%Y-%m-%dT%H:%M:%S",
            errors="raise",
        )
        for column in WEATHER_SOURCE_COLUMNS[1:]:
            source[column] = pd.to_numeric(source[column], errors="raise")
    except (TypeError, ValueError) as error:
        raise ValueError("Phoenix 气象源包含无法解析的数据。") from error

    expected_timestamps = pd.date_range(
        "2019-05-01 00:00:00",
        "2019-05-28 23:00:00",
        freq="h",
    )
    if source["timestamp_lst"].duplicated().any():
        raise ValueError("timestamp_lst 不得重复。")
    if not source["timestamp_lst"].equals(
        pd.Series(expected_timestamps, name="timestamp_lst")
    ):
        raise ValueError(
            "timestamp_lst 必须按 LST 从 2019-05-01 00:00 连续有序至 "
            "2019-05-28 23:00。"
        )

    weather_values = source[WEATHER_SOURCE_COLUMNS[1:]].to_numpy(dtype=float)
    if not np.isfinite(weather_values).all():
        raise ValueError("Phoenix 气象源数值必须为有限值。")
    if (weather_values < 0.0).any():
        raise ValueError("Phoenix 气象源数值不得为负数。")
    return source


def load_houston_energy_scenario(
    csv_path: Path,
    params: Parameters,
) -> pd.DataFrame:
    scenario = pd.read_csv(csv_path)
    if list(scenario.columns) != HOUSTON_ENERGY_SCENARIO_COLUMNS:
        raise ValueError(
            "Houston 能源场景字段应严格为: "
            f"{HOUSTON_ENERGY_SCENARIO_COLUMNS}"
        )
    if len(scenario) != 699:
        raise ValueError("Houston 主实验能源场景必须恰好包含 699 个小时。")
    if scenario.isna().any().any():
        raise ValueError("Houston 2020 能源场景存在缺失值。")

    scenario = scenario.copy()
    try:
        scenario["timestamp_lst"] = pd.to_datetime(
            scenario["timestamp_lst"],
            format="%Y-%m-%dT%H:%M:%S",
            errors="raise",
        )
        for column in (
            "solar_available_mw",
            "wind_available_mw",
            "electricity_price_cny_per_kwh",
        ):
            scenario[column] = pd.to_numeric(
                scenario[column],
                errors="raise",
            )
    except (TypeError, ValueError) as error:
        raise ValueError("Houston 2020 能源场景包含无法解析的数据。") from error

    expected_timestamps = pd.date_range(
        "2020-04-30 00:00:00",
        "2020-05-29 02:00:00",
        freq="h",
    )
    if scenario["timestamp_lst"].duplicated().any():
        raise ValueError("timestamp_lst 不得重复。")
    if not scenario["timestamp_lst"].equals(
        pd.Series(expected_timestamps, name="timestamp_lst")
    ):
        raise ValueError(
            "timestamp_lst 必须按 UTC-06 本地标准时间从 2020-04-30 00:00 "
            "连续有序至 2020-05-29 02:00。"
        )

    numeric_columns = [
        "solar_available_mw",
        "wind_available_mw",
        "electricity_price_cny_per_kwh",
    ]
    numeric_values = scenario[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(numeric_values).all():
        raise ValueError("Houston 2020 能源场景数值必须为有限值。")
    if (numeric_values < 0.0).any():
        raise ValueError("Houston 2020 能源场景数值不得为负数。")
    if (
        scenario["solar_available_mw"]
        > params.solar_inverter_capacity_mw + 1e-9
    ).any():
        raise ValueError("solar_available_mw 不得超过光伏交流逆变器容量。")
    if (
        scenario["wind_available_mw"]
        > params.wind_capacity_mw + 1e-9
    ).any():
        raise ValueError("wind_available_mw 不得超过风电容量。")

    periods, prices = _qinghai_tou(
        scenario["timestamp_lst"].dt.hour.to_numpy(dtype=int)
    )
    if not scenario["tou_period"].equals(
        pd.Series(periods, name="tou_period")
    ):
        raise ValueError("tou_period 与原分段电价时段不一致。")
    if not np.array_equal(
        scenario["electricity_price_cny_per_kwh"].to_numpy(dtype=float),
        prices,
    ):
        raise ValueError("electricity_price_cny_per_kwh 与原分段电价不一致。")
    return scenario


def solar_available_power_mw(
    solar_irradiance_wh_m2: np.ndarray,
    params: Parameters,
) -> np.ndarray:
    irradiance = np.asarray(solar_irradiance_wh_m2, dtype=float)
    available_power_mw = (
        params.solar_panel_area_m2
        * params.solar_base_efficiency
        * irradiance
        / 1_000_000.0
    )
    return np.clip(available_power_mw, 0.0, params.solar_capacity_mw)


def wind_available_power_mw(
    wind_speed_m_s: np.ndarray,
    params: Parameters,
) -> np.ndarray:
    wind_speed = np.asarray(wind_speed_m_s, dtype=float)
    capacity_factor = np.zeros_like(wind_speed_m_s, dtype=float)
    rising = (
        (wind_speed >= params.wind_cut_in_speed_m_s)
        & (wind_speed < params.wind_rated_speed_m_s)
    )
    rated = (
        (wind_speed >= params.wind_rated_speed_m_s)
        & (wind_speed < params.wind_cut_out_speed_m_s)
    )
    capacity_factor[rising] = (
        wind_speed[rising] ** 3 - params.wind_cut_in_speed_m_s ** 3
    ) / (
        params.wind_rated_speed_m_s ** 3
        - params.wind_cut_in_speed_m_s ** 3
    )
    capacity_factor[rated] = 1.0
    return params.wind_capacity_mw * capacity_factor


def _qinghai_tou(hours: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hour_values = np.asarray(hours, dtype=int)
    valley = (hour_values >= 0) & (hour_values < 8)
    peak = ((hour_values >= 9) & (hour_values < 13)) | (
        (hour_values >= 18) & (hour_values < 23)
    )
    periods = np.select(
        [valley, peak],
        ["valley", "peak"],
        default="flat",
    )
    prices = np.select(
        [valley, peak],
        [0.1804, 0.7174],
        default=0.4489,
    )
    return periods, prices


def build_provisional_energy_scenario(
    source_csv_path: Path,
    params: Parameters,
) -> pd.DataFrame:
    source = load_phoenix_weather_source(source_csv_path)
    source_rows = source.copy()
    source_rows["hour"] = source_rows["timestamp_lst"].dt.hour
    source_rows["solar_available_mw"] = solar_available_power_mw(
        source_rows["solar_irradiance_wh_m2"].to_numpy(dtype=float),
        params,
    )
    source_rows["wind_available_mw"] = wind_available_power_mw(
        source_rows["wind_speed_50m_m_s"].to_numpy(dtype=float),
        params,
    )
    scenario = (
        source_rows.groupby("hour", as_index=False)[
            [
                "solar_irradiance_wh_m2",
                "wind_speed_50m_m_s",
                "solar_available_mw",
                "wind_available_mw",
            ]
        ]
        .mean()
    )

    periods, prices = _qinghai_tou(
        scenario["hour"].to_numpy(dtype=int)
    )
    scenario["tou_period"] = periods
    scenario["electricity_price_cny_per_kwh"] = prices
    return scenario[ENERGY_SCENARIO_COLUMNS]


def load_energy_scenario(
    csv_path: Path,
    params: Parameters,
    weather_source_path: Path | None = None,
) -> pd.DataFrame:
    scenario = pd.read_csv(csv_path)
    if list(scenario.columns) != ENERGY_SCENARIO_COLUMNS:
        raise ValueError(
            "能源场景字段应严格为: "
            f"{ENERGY_SCENARIO_COLUMNS}"
        )
    if len(scenario) != 24:
        raise ValueError("能源场景必须恰好包含 24 个小时。")
    if scenario["hour"].tolist() != list(range(24)):
        raise ValueError("hour 必须按 0 到 23 排列且不得重复。")

    numeric_columns = [
        column
        for column in ENERGY_SCENARIO_COLUMNS
        if column != "tou_period"
    ]
    if scenario[numeric_columns].isna().any().any():
        raise ValueError("能源场景数值字段存在缺失值。")
    numeric_values = scenario[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(numeric_values).all():
        raise ValueError("能源场景数值字段必须为有限值。")
    if (numeric_values < 0.0).any():
        raise ValueError("能源场景数值字段不得为负数。")
    if (scenario["solar_available_mw"] > params.solar_capacity_mw).any():
        raise ValueError("solar_available_mw 不得超过光伏容量。")
    if (scenario["wind_available_mw"] > params.wind_capacity_mw).any():
        raise ValueError("wind_available_mw 不得超过风电容量。")

    period_values, expected_prices = _qinghai_tou(
        scenario["hour"].to_numpy(dtype=int)
    )
    expected_periods = pd.Series(
        period_values,
        name="tou_period",
    )
    if not scenario["tou_period"].equals(expected_periods):
        raise ValueError("tou_period 与青海分时时段不一致。")
    if not np.array_equal(
        scenario["electricity_price_cny_per_kwh"].to_numpy(dtype=float),
        expected_prices,
    ):
        raise ValueError("electricity_price_cny_per_kwh 与青海分时电价不一致。")

    if weather_source_path is not None:
        expected = build_provisional_energy_scenario(
            weather_source_path,
            params,
        )
        for column in ENERGY_SCENARIO_COLUMNS:
            if column == "tou_period":
                matches = scenario[column].equals(expected[column])
            else:
                matches = np.allclose(
                    scenario[column].to_numpy(dtype=float),
                    expected[column].to_numpy(dtype=float),
                    rtol=0.0,
                    atol=1e-10,
                )
            if not matches:
                raise ValueError(f"{column} 与气象源重建结果不一致。")
    return scenario


def load_and_prepare(csv_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    raw = pd.read_csv(csv_path)
    expected = {
        "avg_cpu",
        "avg_mem",
        "avg_assigned_mem",
        "avg_cycles_per_instruction",
    }
    missing_columns = expected.difference(raw.columns)
    if missing_columns:
        raise ValueError(f"缺少字段: {sorted(missing_columns)}")
    if len(raw) % 288 != 0:
        raise ValueError("行数不是 288 的整数倍，无法按每天 5 分钟数据切分。")
    if raw[list(expected)].isna().any().any():
        raise ValueError("原始数据存在缺失值，请先处理。")

    raw = raw.copy()
    raw["step_5min"] = np.arange(len(raw))
    raw["day"] = raw["step_5min"] // 288 + 1
    raw["hour"] = (raw["step_5min"] % 288) // 12
    raw["step_in_hour"] = raw["step_5min"] % 12

    hourly = (
        raw.groupby(["day", "hour"], as_index=False)
        .agg(
            avg_cpu=("avg_cpu", "mean"),
            avg_mem=("avg_mem", "mean"),
            avg_assigned_mem=("avg_assigned_mem", "mean"),
            avg_cycles_per_instruction=("avg_cycles_per_instruction", "mean"),
        )
        .sort_values(["day", "hour"])
        .reset_index(drop=True)
    )

    profiles = hourly.pivot(index="day", columns="hour", values="avg_cpu")
    mean_profile = profiles.mean(axis=0)
    representative_day = int(
        np.sqrt(((profiles - mean_profile) ** 2).mean(axis=1)).idxmin()
    )
    stress_day = int(profiles.std(axis=1).idxmax())
    return raw, hourly, representative_day, stress_day
