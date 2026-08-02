from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Parameters
from .data import HOUSTON_ENERGY_SCENARIO_COLUMNS
from .model import PendingFlexibleTask, build_and_solve


ROLLING_CASES = (
    ("renewables_only", False, False),
    ("renewables_shift", True, False),
    ("renewables_storage", False, True),
    ("joint", True, True),
)


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


def _validate_rolling_inputs(
    cpu_arrival: np.ndarray,
    energy_scenario: pd.DataFrame,
) -> tuple[np.ndarray, pd.DataFrame, int]:
    workload = np.asarray(cpu_arrival, dtype=float).reshape(-1)
    if len(workload) == 0 or len(workload) % 24 != 0:
        raise ValueError("cpu_arrival 必须包含完整整数天的小时数据。")
    if not np.isfinite(workload).all() or (workload < 0.0).any():
        raise ValueError("cpu_arrival 必须为有限非负值。")

    scenario = energy_scenario.copy()
    if list(scenario.columns) != HOUSTON_ENERGY_SCENARIO_COLUMNS:
        raise ValueError(
            "energy_scenario 字段应严格为: "
            f"{HOUSTON_ENERGY_SCENARIO_COLUMNS}"
        )
    analysis_days = len(workload) // 24
    expected_energy_hours = 24 + len(workload) + 3
    if len(scenario) != expected_energy_hours:
        raise ValueError(
            "energy_scenario 必须包含 24 小时预热、完整分析期和 "
            "3 小时结算尾段。"
        )
    timestamps = pd.to_datetime(scenario["timestamp_lst"], errors="raise")
    if not timestamps.equals(
        pd.Series(
            pd.date_range(timestamps.iloc[0], periods=len(scenario), freq="h"),
            name="timestamp_lst",
        )
    ):
        raise ValueError("energy_scenario 的 timestamp_lst 必须逐小时连续有序。")
    scenario["timestamp_lst"] = timestamps
    return workload, scenario, analysis_days


def _cost_summary(rows: pd.DataFrame) -> dict[str, float]:
    cost_columns = {
        "grid_purchase_cost_cny": "hourly_grid_purchase_cost_cny",
        "solar_om_cost_cny": "hourly_solar_om_cost_cny",
        "wind_om_cost_cny": "hourly_wind_om_cost_cny",
        "battery_om_cost_cny": "hourly_battery_om_cost_cny",
        "battery_degradation_cost_cny": (
            "hourly_battery_degradation_cost_cny"
        ),
        "operating_cost_cny": "hourly_operating_cost_cny",
    }
    return {
        metric_name: float(rows[column_name].sum())
        for metric_name, column_name in cost_columns.items()
    }


def _prewarm_carry_in(
    *,
    cpu_arrival: np.ndarray,
    energy_scenario: pd.DataFrame,
    params: Parameters,
    case_name: str,
    output_dir: Path,
    show_log: bool,
) -> tuple[tuple[PendingFlexibleTask, ...], dict]:
    warmup_workload = np.concatenate((cpu_arrival[-24:], cpu_arrival[:3]))
    warmup_energy = energy_scenario.iloc[:27].reset_index(drop=True)
    _, metrics, state = build_and_solve(
        cpu_arrival=warmup_workload,
        solar_available_mw=warmup_energy["solar_available_mw"].to_numpy(
            dtype=float
        ),
        wind_available_mw=warmup_energy["wind_available_mw"].to_numpy(
            dtype=float
        ),
        electricity_price_cny_per_kwh=warmup_energy[
            "electricity_price_cny_per_kwh"
        ].to_numpy(dtype=float),
        params=params,
        enable_shift=True,
        enable_storage=False,
        enable_renewables=True,
        case_name=f"{case_name}_warmup",
        output_dir=output_dir,
        show_log=show_log,
        flex_arrival_hours=24,
        commit_hours=24,
        return_state=True,
    )
    return _next_day_tasks(state.pending_flexible_tasks), metrics


def _coordinate_soc_boundaries(
    *,
    cpu_arrival: np.ndarray,
    energy_scenario: pd.DataFrame,
    params: Parameters,
    case_name: str,
    enable_shift: bool,
    carry_in_tasks: tuple[PendingFlexibleTask, ...],
    output_dir: Path,
    show_log: bool,
) -> tuple[list[float], list[float], dict]:
    coordinator_cpu = np.concatenate((cpu_arrival, np.zeros(3)))
    coordinator_energy = energy_scenario.iloc[24:].reset_index(drop=True)
    coordinator_result, coordinator_metrics = build_and_solve(
        cpu_arrival=coordinator_cpu,
        solar_available_mw=coordinator_energy[
            "solar_available_mw"
        ].to_numpy(dtype=float),
        wind_available_mw=coordinator_energy[
            "wind_available_mw"
        ].to_numpy(dtype=float),
        electricity_price_cny_per_kwh=coordinator_energy[
            "electricity_price_cny_per_kwh"
        ].to_numpy(dtype=float),
        params=params,
        enable_shift=enable_shift,
        enable_storage=True,
        enable_renewables=True,
        case_name=f"{case_name}_soc_coordination",
        output_dir=output_dir,
        show_log=show_log,
        initial_stored_energy_mwh=(
            params.battery_soc_initial * params.battery_energy_mwh
        ),
        terminal_stored_energy_mwh=(
            params.battery_soc_initial * params.battery_energy_mwh
        ),
        flex_arrival_hours=len(cpu_arrival),
        carry_in_tasks=carry_in_tasks,
        commit_hours=len(coordinator_cpu),
    )
    committed_boundaries = [
        float(coordinator_result.loc[(day + 1) * 24 - 1, "stored_energy_end_mwh"])
        for day in range(len(cpu_arrival) // 24)
    ]
    terminal_boundaries = [
        float(coordinator_result.loc[day * 24 + 26, "stored_energy_end_mwh"])
        for day in range(len(cpu_arrival) // 24)
    ]
    return committed_boundaries, terminal_boundaries, coordinator_metrics


def run_rolling_day_ahead(
    *,
    cpu_arrival: np.ndarray,
    energy_scenario: pd.DataFrame,
    params: Parameters,
    case_name: str,
    enable_shift: bool,
    enable_storage: bool,
    output_dir: Path,
    show_log: bool,
) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    workload, scenario, analysis_days = _validate_rolling_inputs(
        cpu_arrival,
        energy_scenario,
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    carry_in_tasks: tuple[PendingFlexibleTask, ...] = ()
    warmup_metrics: dict | None = None
    if enable_shift:
        carry_in_tasks, warmup_metrics = _prewarm_carry_in(
            cpu_arrival=workload,
            energy_scenario=scenario,
            params=params,
            case_name=case_name,
            output_dir=output_dir,
            show_log=show_log,
        )
    warmup_carry_in_cpu = float(
        sum(task.remaining_cpu_pu for task in carry_in_tasks)
    )

    initial_energy_mwh = params.battery_soc_initial * params.battery_energy_mwh
    soc_boundaries: list[float] = []
    window_terminal_boundaries: list[float] = []
    coordination_metrics: dict | None = None
    if enable_storage:
        (
            soc_boundaries,
            window_terminal_boundaries,
            coordination_metrics,
        ) = _coordinate_soc_boundaries(
            cpu_arrival=workload,
            energy_scenario=scenario,
            params=params,
            case_name=case_name,
            enable_shift=enable_shift,
            carry_in_tasks=carry_in_tasks,
            output_dir=output_dir,
            show_log=show_log,
        )

    committed_results: list[pd.DataFrame] = []
    daily_rows: list[dict] = []
    rolling_metrics: list[dict] = []
    stored_energy_mwh = initial_energy_mwh
    global_hour_offset = 0
    for day_index in range(analysis_days):
        day_number = day_index + 1
        workload_start = day_index * 24
        workload_stop = workload_start + 24
        current_workload = workload[workload_start:workload_stop]
        if day_index + 1 < analysis_days:
            preview_workload = workload[workload_stop:workload_stop + 3]
        else:
            preview_workload = np.zeros(3)
        window_workload = np.concatenate((current_workload, preview_workload))

        energy_start = 24 + workload_start
        window_energy = scenario.iloc[
            energy_start:energy_start + 27
        ].reset_index(drop=True)
        terminal_energy = (
            window_terminal_boundaries[day_index]
            if enable_storage
            else None
        )
        committed_energy = soc_boundaries[day_index] if enable_storage else None
        result, window_metrics, state = build_and_solve(
            cpu_arrival=window_workload,
            solar_available_mw=window_energy[
                "solar_available_mw"
            ].to_numpy(dtype=float),
            wind_available_mw=window_energy["wind_available_mw"].to_numpy(
                dtype=float
            ),
            electricity_price_cny_per_kwh=window_energy[
                "electricity_price_cny_per_kwh"
            ].to_numpy(dtype=float),
            params=params,
            enable_shift=enable_shift,
            enable_storage=enable_storage,
            enable_renewables=True,
            case_name=f"{case_name}_day_{day_number:02d}",
            output_dir=output_dir,
            show_log=show_log,
            initial_stored_energy_mwh=stored_energy_mwh,
            terminal_stored_energy_mwh=terminal_energy,
            committed_stored_energy_mwh=committed_energy,
            # 次日 3 小时前视只承担 70% 非柔性最低负荷；其 30% 柔性任务不在当前截断窗口创建，
            # 而由下一日窗口在完整到期域内创建。
            flex_arrival_hours=24,
            carry_in_tasks=carry_in_tasks,
            commit_hours=24,
            return_state=True,
        )
        result = result.copy()
        result["timestamp_lst"] = window_energy["timestamp_lst"]
        result["tou_period"] = window_energy["tou_period"]

        committed_hours = 27 if day_number == analysis_days else 24
        committed = result.iloc[:committed_hours].copy()
        committed["case"] = case_name
        committed["hour"] = np.arange(
            global_hour_offset,
            global_hour_offset + committed_hours,
            dtype=int,
        )
        committed["day"] = day_number
        committed["hour_of_day"] = committed["timestamp_lst"].dt.hour
        committed["period_role"] = "analysis"
        if day_number == analysis_days:
            committed.loc[committed.index >= 24, "period_role"] = (
                "settlement_tail"
            )
        committed_results.append(committed)
        global_hour_offset += committed_hours

        analysis_result = result.iloc[:24]
        day_costs = _cost_summary(analysis_result)
        tail_cost = (
            float(result.iloc[24:]["hourly_operating_cost_cny"].sum())
            if day_number == analysis_days
            else 0.0
        )
        daily_rows.append(
            {
                "case": case_name,
                "day": day_number,
                **day_costs,
                "settlement_tail_operating_cost_cny": tail_cost,
                "initial_stored_energy_mwh": stored_energy_mwh,
                "committed_end_stored_energy_mwh": state.stored_energy_mwh,
                "coordinated_committed_stored_energy_mwh": (
                    committed_energy
                    if committed_energy is not None
                    else initial_energy_mwh
                ),
                "window_terminal_stored_energy_mwh": (
                    terminal_energy
                    if terminal_energy is not None
                    else initial_energy_mwh
                ),
                "actual_window_terminal_stored_energy_mwh": float(
                    result.loc[26, "stored_energy_end_mwh"]
                ),
                "carry_in_task_cpu_pu_hours": float(
                    sum(task.remaining_cpu_pu for task in carry_in_tasks)
                ),
                "carry_out_task_cpu_pu_hours": float(
                    sum(
                        task.remaining_cpu_pu
                        for task in state.pending_flexible_tasks
                    )
                ),
                "committed_task_delay_cpu_hours": window_metrics[
                    "committed_task_delay_cpu_hours"
                ],
                "committed_maximum_task_delay_h": window_metrics[
                    "committed_maximum_task_delay_h"
                ],
            }
        )
        rolling_metrics.append(window_metrics)
        stored_energy_mwh = state.stored_energy_mwh
        carry_in_tasks = _next_day_tasks(state.pending_flexible_tasks)

    hourly = pd.concat(committed_results, ignore_index=True)
    daily = pd.DataFrame(daily_rows)
    costs = _cost_summary(hourly)
    analysis_rows = hourly[hourly["period_role"] == "analysis"]
    tail_rows = hourly[hourly["period_role"] == "settlement_tail"]

    renewable_available_energy = float(
        (
            hourly["solar_available_mw"] + hourly["wind_available_mw"]
        ).sum()
        * params.time_step_h
    )
    renewable_used_energy = float(
        (hourly["solar_used_mw"] + hourly["wind_used_mw"]).sum()
        * params.time_step_h
    )
    renewable_curtailment_energy = float(
        (
            hourly["solar_curtailed_mw"] + hourly["wind_curtailed_mw"]
        ).sum()
        * params.time_step_h
    )
    supply_energy = float(
        (
            hourly["grid_power_mw"]
            + hourly["solar_used_mw"]
            + hourly["wind_used_mw"]
            + hourly["discharge_mw"]
        ).sum()
        * params.time_step_h
    )
    if analysis_days == 1:
        task_delay = rolling_metrics[0]["total_task_delay_cpu_hours"]
        maximum_delay = rolling_metrics[0]["maximum_task_delay_h"]
        cross_day_task_cpu = rolling_metrics[0][
            "total_cross_day_task_cpu_pu_hours"
        ]
    else:
        task_delay = sum(
            metric["committed_task_delay_cpu_hours"]
            for metric in rolling_metrics[:-1]
        ) + rolling_metrics[-1]["total_task_delay_cpu_hours"]
        maximum_delay = max(
            [
                metric["committed_maximum_task_delay_h"]
                for metric in rolling_metrics[:-1]
            ]
            + [rolling_metrics[-1]["maximum_task_delay_h"]]
        )
        cross_day_task_cpu = sum(
            metric["committed_cross_day_task_cpu_pu_hours"]
            for metric in rolling_metrics[:-1]
        ) + rolling_metrics[-1]["total_cross_day_task_cpu_pu_hours"]

    flexible_cpu_total = (
        params.flex_ratio * float(workload.sum()) + warmup_carry_in_cpu
        if enable_shift
        else 0.0
    )
    charged_energy = float(hourly["charge_mw"].sum() * params.time_step_h)
    discharged_energy = float(
        hourly["discharge_mw"].sum() * params.time_step_h
    )
    grid_margin = params.grid_capacity_mw - hourly["grid_power_mw"]
    auxiliary_metrics = [
        metric
        for metric in (warmup_metrics, coordination_metrics)
        if metric is not None
    ]
    all_solve_metrics = [*auxiliary_metrics, *rolling_metrics]
    rolling_solve_time_s = float(
        sum(metric["solve_time_s"] for metric in rolling_metrics)
    )
    metrics = {
        "case": case_name,
        "status": (
            "optimal"
            if all(metric["status"] == "optimal" for metric in all_solve_metrics)
            else "gaplimit"
        ),
        "shift_enabled": enable_shift,
        "storage_enabled": enable_storage,
        "renewables_enabled": True,
        **costs,
        "analysis_operating_cost_cny": float(
            analysis_rows["hourly_operating_cost_cny"].sum()
        ),
        "settlement_tail_operating_cost_cny": float(
            tail_rows["hourly_operating_cost_cny"].sum()
        ),
        "analysis_hours": len(workload),
        "settlement_tail_hours": 3,
        "grid_capacity_mw": params.grid_capacity_mw,
        "grid_purchase_energy_mwh": float(
            hourly["grid_power_mw"].sum() * params.time_step_h
        ),
        "grid_peak_power_mw": float(hourly["grid_power_mw"].max()),
        "grid_mean_power_mw": float(hourly["grid_power_mw"].mean()),
        "grid_binding_hours": int((grid_margin <= 1e-7).sum()),
        "grid_minimum_margin_mw": float(grid_margin.min()),
        "renewable_available_energy_mwh": renewable_available_energy,
        "renewable_used_energy_mwh": renewable_used_energy,
        "renewable_curtailment_energy_mwh": renewable_curtailment_energy,
        "renewable_curtailment_rate_pct": (
            100.0 * renewable_curtailment_energy / renewable_available_energy
            if renewable_available_energy > 0.0
            else 0.0
        ),
        "grid_supply_share_pct": (
            100.0
            * float(hourly["grid_power_mw"].sum() * params.time_step_h)
            / supply_energy
            if supply_energy > 0.0
            else 0.0
        ),
        "solar_supply_share_pct": (
            100.0
            * float(hourly["solar_used_mw"].sum() * params.time_step_h)
            / supply_energy
            if supply_energy > 0.0
            else 0.0
        ),
        "wind_supply_share_pct": (
            100.0
            * float(hourly["wind_used_mw"].sum() * params.time_step_h)
            / supply_energy
            if supply_energy > 0.0
            else 0.0
        ),
        "battery_discharge_supply_share_pct": (
            100.0 * discharged_energy / supply_energy
            if supply_energy > 0.0
            else 0.0
        ),
        "battery_charged_energy_mwh": charged_energy,
        "battery_discharged_energy_mwh": discharged_energy,
        "battery_throughput_energy_mwh": charged_energy + discharged_energy,
        "battery_equivalent_full_cycles": (
            discharged_energy / params.battery_energy_mwh
            if enable_storage
            else 0.0
        ),
        "initial_stored_energy_mwh": initial_energy_mwh,
        "final_stored_energy_mwh": float(
            hourly.iloc[-1]["stored_energy_end_mwh"]
        ),
        "soc_cycle_error": abs(
            float(hourly.iloc[-1]["soc_end"] - hourly.iloc[0]["soc_start"])
        ),
        "max_simultaneous_charge_discharge_mw2": float(
            (hourly["charge_mw"] * hourly["discharge_mw"]).max()
        ),
        "warmup_carry_in_task_cpu_pu_hours": warmup_carry_in_cpu,
        "cross_day_task_cpu_pu_hours": float(cross_day_task_cpu),
        "total_task_delay_cpu_hours": float(task_delay),
        "average_flexible_task_delay_h": (
            float(task_delay) / flexible_cpu_total
            if flexible_cpu_total > 0.0
            else 0.0
        ),
        "maximum_task_delay_h": int(maximum_delay),
        "cpu_conservation_error": abs(
            float(hourly["cpu_scheduled_pu"].sum())
            - float(workload.sum())
            - warmup_carry_in_cpu
        ),
        "power_balance_max_error_mw": float(
            np.abs(
                hourly["grid_power_mw"]
                + hourly["solar_used_mw"]
                + hourly["wind_used_mw"]
                + hourly["discharge_mw"]
                - hourly["dc_power_mw"]
                - hourly["charge_mw"]
            ).max()
        ),
        "rolling_solve_time_s": rolling_solve_time_s,
        "warmup_solve_time_s": (
            float(warmup_metrics["solve_time_s"])
            if warmup_metrics is not None
            else 0.0
        ),
        "soc_coordination_solve_time_s": (
            float(coordination_metrics["solve_time_s"])
            if coordination_metrics is not None
            else 0.0
        ),
        "solve_time_s": float(
            sum(metric["solve_time_s"] for metric in all_solve_metrics)
        ),
        "mip_gap": float(max(metric["mip_gap"] for metric in all_solve_metrics)),
    }
    if not math.isclose(
        metrics["operating_cost_cny"],
        sum(
            metrics[name]
            for name in (
                "grid_purchase_cost_cny",
                "solar_om_cost_cny",
                "wind_om_cost_cny",
                "battery_om_cost_cny",
                "battery_degradation_cost_cny",
            )
        ),
        rel_tol=0.0,
        abs_tol=1e-7,
    ):
        raise RuntimeError("五项成本分量与运行成本不一致。")
    return hourly, metrics, daily
