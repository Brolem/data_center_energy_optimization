from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


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
