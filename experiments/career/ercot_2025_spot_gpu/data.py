from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from dc_energy_opt.config import Parameters

from .config import (
    ANALYSIS_HOURS,
    ANALYSIS_LOCAL_DAYS,
    ENERGY_COLUMNS,
    FORECAST_TARGET_COLUMNS,
    SETTLEMENT_CLOSURE_DATE,
    SETTLEMENT_CLOSURE_HOURS,
    SOLAR_SIGNAL_MAX_MWH,
    TEST_END,
    TEST_START,
    TRAIN_END,
    TRAIN_HOURS,
    TRAIN_LOCAL_DAYS,
    TRAIN_START,
    VALIDATION_END,
    VALIDATION_HOURS,
    VALIDATION_LOCAL_DAYS,
    VALIDATION_START,
    WIND_SIGNAL_MAX_MWH,
)


@dataclass(frozen=True)
class EnergySplits:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    test_with_closure: pd.DataFrame


def _require_hourly_utc_timestamps(frame: pd.DataFrame) -> None:
    timestamps = pd.to_datetime(
        frame["timestamp_utc"],
        format="%Y-%m-%dT%H:%M:%SZ",
        errors="coerce",
    )
    if timestamps.isna().any():
        raise ValueError("timestamp_utc 无法解析。")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamp_utc 必须唯一且升序。")
    if not timestamps.iloc[1:].reset_index(drop=True).equals(
        (timestamps.iloc[:-1] + pd.Timedelta(hours=1)).reset_index(drop=True)
    ):
        raise ValueError("timestamp_utc 必须逐小时连续。")


def _require_local_dates(frame: pd.DataFrame) -> None:
    local_dates = pd.to_datetime(
        frame["local_date"], format="%Y-%m-%d", errors="coerce"
    )
    if local_dates.isna().any() or not (
        local_dates.dt.strftime("%Y-%m-%d") == frame["local_date"]
    ).all():
        raise ValueError("local_date 必须使用 YYYY-MM-DD 格式。")


def _coerce_forecast_targets(
    frame: pd.DataFrame,
    *,
    require_complete: bool,
) -> pd.DataFrame:
    checked = frame.copy()
    for column in FORECAST_TARGET_COLUMNS:
        source_missing = checked[column].isna()
        values = pd.to_numeric(checked[column], errors="coerce")
        if (values.isna() & ~source_missing).any():
            raise ValueError(f"{column} 存在无法解析的数值。")
        present_values = values.loc[~values.isna()].to_numpy(dtype=float)
        if not np.isfinite(present_values).all():
            raise ValueError(f"{column} 必须为有限数值。")
        if require_complete and values.isna().any():
            raise ValueError(f"{column} 存在缺失数值。")
        if column == "dam_lz_houston_usd_per_mwh" and values.isna().any():
            raise ValueError(f"{column} 存在缺失数值。")
        if column != "dam_lz_houston_usd_per_mwh" and (present_values < 0.0).any():
            raise ValueError(f"{column} 不得为负值。")
        checked[column] = values
    return checked


def load_energy_table(path: Path) -> pd.DataFrame:
    """Load the shared annual table without applying career-specific imputation."""
    table_path = Path(path)
    if not table_path.is_file():
        raise FileNotFoundError(f"找不到公共年度能源表: {table_path}")
    frame = pd.read_csv(table_path)
    if tuple(frame.columns) != ENERGY_COLUMNS:
        raise ValueError("公共年度能源表字段顺序不符合正式契约。")
    if len(frame) != 8_760:
        raise ValueError("公共年度能源表必须恰好包含 8760 行。")
    _require_hourly_utc_timestamps(frame)
    _require_local_dates(frame)
    return _coerce_forecast_targets(frame, require_complete=False)


def _select_date_range(
    frame: pd.DataFrame,
    *,
    start: str,
    end: str,
    label: str,
    expected_local_days: int,
    expected_hours: int,
) -> pd.DataFrame:
    selected = frame.loc[
        frame["local_date"].between(start, end),
    ].reset_index(drop=True)
    if selected["local_date"].nunique() != expected_local_days:
        raise ValueError(f"{label} 的本地日期数量不符合固定划分。")
    if len(selected) != expected_hours:
        raise ValueError(f"{label} 的小时数量不符合固定划分。")
    if selected["local_date"].iloc[0] != start or selected["local_date"].iloc[-1] != end:
        raise ValueError(f"{label} 的起止日期不符合固定划分。")
    return _coerce_forecast_targets(selected, require_complete=True)


def build_energy_splits(frame: pd.DataFrame) -> EnergySplits:
    """Build the fixed chronological train, validation, test, and closure inputs."""
    if tuple(frame.columns) != ENERGY_COLUMNS:
        raise ValueError("公共年度能源表字段顺序不符合正式契约。")
    train = _select_date_range(
        frame,
        start=TRAIN_START,
        end=TRAIN_END,
        label="训练期",
        expected_local_days=TRAIN_LOCAL_DAYS,
        expected_hours=TRAIN_HOURS,
    )
    validation = _select_date_range(
        frame,
        start=VALIDATION_START,
        end=VALIDATION_END,
        label="验证期",
        expected_local_days=VALIDATION_LOCAL_DAYS,
        expected_hours=VALIDATION_HOURS,
    )
    test = _select_date_range(
        frame,
        start=TEST_START,
        end=TEST_END,
        label="测试期",
        expected_local_days=ANALYSIS_LOCAL_DAYS,
        expected_hours=ANALYSIS_HOURS,
    )
    closure = frame.loc[
        (frame["local_date"] == SETTLEMENT_CLOSURE_DATE)
        & frame["local_hour"].isin(range(1, SETTLEMENT_CLOSURE_HOURS + 1))
    ].reset_index(drop=True)
    if len(closure) != SETTLEMENT_CLOSURE_HOURS:
        raise ValueError("测试结算尾段必须恰好包含 3 小时。")
    closure = _coerce_forecast_targets(closure, require_complete=True)
    test_with_closure = pd.concat((test, closure), ignore_index=True)
    _require_hourly_utc_timestamps(test_with_closure)
    return EnergySplits(
        train=train,
        validation=validation,
        test=test,
        test_with_closure=test_with_closure,
    )


def _require_generation_signal(
    values: np.ndarray,
    *,
    name: str,
    maximum_mwh: float,
) -> np.ndarray:
    signal = np.asarray(values, dtype=float).reshape(-1)
    if len(signal) == 0 or not np.isfinite(signal).all():
        raise ValueError(f"{name} 必须为非空有限数值。")
    if (signal < 0.0).any() or (signal > maximum_mwh + 1e-9).any():
        raise ValueError(f"{name} 超出固定情景归一化范围。")
    return signal


def map_generation_signal_to_available_mw(
    *,
    solar_generation_mwh: np.ndarray,
    wind_generation_mwh: np.ndarray,
    params: Parameters,
) -> tuple[np.ndarray, np.ndarray]:
    """Map ERCO system-generation signals to bounded scenario availability."""
    solar = _require_generation_signal(
        solar_generation_mwh,
        name="erco_solar_generation_mwh",
        maximum_mwh=SOLAR_SIGNAL_MAX_MWH,
    )
    wind = _require_generation_signal(
        wind_generation_mwh,
        name="erco_wind_generation_mwh",
        maximum_mwh=WIND_SIGNAL_MAX_MWH,
    )
    if len(solar) != len(wind):
        raise ValueError("光伏与风电信号长度必须一致。")
    solar_available = solar / SOLAR_SIGNAL_MAX_MWH * params.solar_inverter_capacity_mw
    wind_available = wind / WIND_SIGNAL_MAX_MWH * params.wind_capacity_mw
    return solar_available, wind_available
