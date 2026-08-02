from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Parameters


HOUSTON_ENERGY_SCENARIO_COLUMNS = [
    "timestamp_lst",
    "solar_available_mw",
    "wind_available_mw",
    "tou_period",
    "electricity_price_cny_per_kwh",
]


def paper_tou_tariff(hours: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hour_values = np.asarray(hours, dtype=int)
    valley = (hour_values >= 0) & (hour_values < 8)
    peak = ((hour_values >= 9) & (hour_values < 13)) | (
        (hour_values >= 18) & (hour_values < 23)
    )
    periods = np.select([valley, peak], ["valley", "peak"], default="flat")
    prices = np.select([valley, peak], [0.1804, 0.7174], default=0.4489)
    return periods, prices


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

    periods, prices = paper_tou_tariff(
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
