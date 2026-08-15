from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from dc_energy_opt.config import Parameters
from dc_energy_opt.optimization.market_window import build_and_solve_market_window
from dc_energy_opt.optimization.types import PendingFlexibleTask


MARKET_ENERGY_COLUMNS = (
    "timestamp_utc",
    "price_usd_per_mwh",
    "solar_available_mw",
    "wind_available_mw",
)


def _validate_inputs(
    *,
    workload_arrival_pu: np.ndarray,
    energy_scenario: pd.DataFrame,
) -> tuple[np.ndarray, pd.DataFrame]:
    workload = np.asarray(workload_arrival_pu, dtype=float).reshape(-1)
    if len(workload) == 0 or len(workload) % 24 != 0:
        raise ValueError("workload_arrival_pu 必须包含完整整数天的小时数据。")
    if not np.isfinite(workload).all() or (workload < 0.0).any():
        raise ValueError("workload_arrival_pu 必须为有限非负值。")
    if tuple(energy_scenario.columns) != MARKET_ENERGY_COLUMNS:
        raise ValueError("市场能源场景字段顺序不符合正式契约。")
    scenario = energy_scenario.copy()
    if len(scenario) != len(workload) + 3:
        raise ValueError("市场能源场景必须包含分析期和 3 小时结算尾段。")
    timestamps = pd.to_datetime(
        scenario["timestamp_utc"],
        format="%Y-%m-%dT%H:%M:%SZ",
        errors="coerce",
    )
    if timestamps.isna().any() or timestamps.duplicated().any():
        raise ValueError("timestamp_utc 必须可解析且不重复。")
    expected = pd.Series(
        pd.date_range(timestamps.iloc[0], periods=len(scenario), freq="h"),
        name="timestamp_utc",
    )
    if not timestamps.reset_index(drop=True).equals(expected):
        raise ValueError("timestamp_utc 必须逐小时连续。")
    scenario["timestamp_utc"] = timestamps
    for column, allow_negative in (
        ("price_usd_per_mwh", True),
        ("solar_available_mw", False),
        ("wind_available_mw", False),
    ):
        values = pd.to_numeric(scenario[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"{column} 必须为有限数值。")
        if not allow_negative and (values < 0.0).any():
            raise ValueError(f"{column} 必须为非负数值。")
        scenario[column] = values
    return workload, scenario


def _next_day_tasks(
    tasks: tuple[PendingFlexibleTask, ...],
) -> tuple[PendingFlexibleTask, ...]:
    return tuple(
        PendingFlexibleTask(
            origin_hour=task.origin_hour - 24,
            remaining_cpu_pu=task.remaining_cpu_pu,
        )
        for task in tasks
    )


def run_rolling_market_dispatch(
    *,
    workload_arrival_pu: np.ndarray,
    energy_scenario: pd.DataFrame,
    params: Parameters,
    case_name: str,
    model_output_dir: Path,
    show_log: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Commit daily forecast-driven plans and a final three-hour closure."""
    workload, scenario = _validate_inputs(
        workload_arrival_pu=workload_arrival_pu,
        energy_scenario=energy_scenario,
    )
    analysis_days = len(workload) // 24
    model_output_dir = Path(model_output_dir)
    model_output_dir.mkdir(parents=True, exist_ok=True)
    stored_energy_mwh = params.battery_soc_initial * params.battery_energy_mwh
    carry_in_tasks: tuple[PendingFlexibleTask, ...] = ()
    committed_results: list[pd.DataFrame] = []
    daily_rows: list[dict] = []
    for day_index in range(analysis_days):
        start = day_index * 24
        stop = start + 24
        current_workload = workload[start:stop]
        if day_index + 1 < analysis_days:
            preview_workload = workload[stop : stop + 3]
        else:
            preview_workload = np.zeros(3, dtype=float)
        window_workload = np.concatenate((current_workload, preview_workload))
        window_energy = scenario.iloc[start : start + 27].reset_index(drop=True)
        is_final_day = day_index + 1 == analysis_days
        commit_hours = 27 if is_final_day else 24
        terminal_energy = (
            params.battery_soc_initial * params.battery_energy_mwh
            if is_final_day
            else None
        )
        result, metrics, state = build_and_solve_market_window(
            workload_arrival_pu=window_workload,
            solar_available_mw=window_energy["solar_available_mw"].to_numpy(dtype=float),
            wind_available_mw=window_energy["wind_available_mw"].to_numpy(dtype=float),
            price_usd_per_mwh=window_energy["price_usd_per_mwh"].to_numpy(dtype=float),
            params=params,
            enable_shift=True,
            enable_storage=True,
            case_name=f"{case_name}_day_{day_index + 1:02d}",
            lp_output_dir=model_output_dir / f"day_{day_index + 1:02d}",
            show_log=show_log,
            initial_stored_energy_mwh=stored_energy_mwh,
            terminal_stored_energy_mwh=terminal_energy,
            flex_arrival_hours=24,
            carry_in_tasks=carry_in_tasks,
            commit_hours=commit_hours,
            return_state=True,
        )
        committed = result.iloc[:commit_hours].copy()
        committed["timestamp_utc"] = window_energy["timestamp_utc"].iloc[:commit_hours].to_numpy()
        committed["case"] = case_name
        committed["day"] = day_index + 1
        committed["period_role"] = "analysis"
        if is_final_day:
            committed.loc[committed.index >= 24, "period_role"] = "settlement_closure"
        committed_results.append(committed)
        daily_rows.append(
            {
                "case": case_name,
                "day": day_index + 1,
                "committed_hours": commit_hours,
                **metrics,
            }
        )
        stored_energy_mwh = state.stored_energy_mwh
        carry_in_tasks = _next_day_tasks(state.pending_flexible_tasks)
    return pd.concat(committed_results, ignore_index=True), pd.DataFrame(daily_rows)
