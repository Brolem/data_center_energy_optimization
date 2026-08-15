from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import (
    ANALYSIS_HOURS,
    REPLAY_START_SECONDS,
    REPLAY_STOP_SECONDS,
    WORKLOAD_PEAK_PU,
)


JOB_COLUMNS = (
    "job_name",
    "organization",
    "gpu_model",
    "cpu_request",
    "gpu_request",
    "worker_num",
    "submit_time",
    "duration",
    "job_type",
)
_NUMERIC_JOB_COLUMNS = (
    "gpu_request",
    "worker_num",
    "submit_time",
    "duration",
)


@dataclass(frozen=True)
class SpotReplay:
    hourly: pd.DataFrame
    spot_job_count: int


def _validate_job_table(jobs: pd.DataFrame) -> pd.DataFrame:
    if tuple(jobs.columns) != JOB_COLUMNS:
        raise ValueError("Spot 作业表字段顺序不符合正式契约。")
    checked = jobs.copy()
    if checked["job_type"].isna().any():
        raise ValueError("job_type 不得缺失。")
    for column in _NUMERIC_JOB_COLUMNS:
        values = pd.to_numeric(checked[column], errors="coerce")
        if values.isna().any():
            raise ValueError(f"{column} 必须为有限数值。")
        numeric_values = values.to_numpy(dtype=float)
        if not np.isfinite(numeric_values).all() or (numeric_values < 0.0).any():
            raise ValueError(f"{column} 必须为有限非负数值。")
        checked[column] = values
    return checked


def build_spot_replay(jobs: pd.DataFrame) -> SpotReplay:
    """Aggregate one fixed, relative-time Spot block into hourly work proxies."""
    checked = _validate_job_table(jobs)
    spot = checked.loc[
        (checked["job_type"] == "Spot")
        & (checked["submit_time"] >= REPLAY_START_SECONDS)
        & (checked["submit_time"] < REPLAY_STOP_SECONDS)
    ].copy()
    spot["replay_hour"] = (
        (spot["submit_time"] - REPLAY_START_SECONDS) // 3_600
    ).astype(int)
    if not spot["replay_hour"].between(0, ANALYSIS_HOURS - 1).all():
        raise ValueError("Spot 作业重放小时超出固定区间。")
    spot["gpu_hour_work"] = (
        spot["gpu_request"]
        * spot["worker_num"]
        * spot["duration"]
        / 3_600.0
    )
    grouped = spot.groupby("replay_hour", sort=True).agg(
        spot_job_count=("job_name", "size"),
        hourly_gpu_hour_work=("gpu_hour_work", "sum"),
    )
    hourly = pd.DataFrame({"replay_hour": np.arange(ANALYSIS_HOURS, dtype=int)})
    hourly = hourly.join(grouped, on="replay_hour")
    hourly["spot_job_count"] = hourly["spot_job_count"].fillna(0).astype(int)
    hourly["hourly_gpu_hour_work"] = hourly["hourly_gpu_hour_work"].fillna(0.0)
    peak_work = float(hourly["hourly_gpu_hour_work"].max())
    if not np.isfinite(peak_work) or peak_work <= 0.0:
        raise ValueError("Spot 重放工作量峰值必须为正数。")
    hourly["workload_arrival_pu"] = (
        WORKLOAD_PEAK_PU * hourly["hourly_gpu_hour_work"] / peak_work
    )
    return SpotReplay(hourly=hourly, spot_job_count=len(spot))
