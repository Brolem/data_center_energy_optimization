from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..config import Parameters
from ..optimization.types import PendingFlexibleTask, WindowSolveState


COST_COLUMNS = {
    "grid_purchase_cost_cny": "hourly_grid_purchase_cost_cny",
    "solar_om_cost_cny": "hourly_solar_om_cost_cny",
    "wind_om_cost_cny": "hourly_wind_om_cost_cny",
    "battery_om_cost_cny": "hourly_battery_om_cost_cny",
    "battery_degradation_cost_cny": (
        "hourly_battery_degradation_cost_cny"
    ),
    "operating_cost_cny": "hourly_operating_cost_cny",
}


def summarize_costs(rows: pd.DataFrame) -> dict[str, float]:
    return {
        metric_name: float(rows[column_name].sum())
        for metric_name, column_name in COST_COLUMNS.items()
    }


def summarize_daily_window(
    *,
    case_name: str,
    day_number: int,
    result: pd.DataFrame,
    stored_energy_mwh: float,
    state: WindowSolveState,
    committed_energy_mwh: float | None,
    terminal_energy_mwh: float | None,
    initial_energy_mwh: float,
    carry_in_tasks: tuple[PendingFlexibleTask, ...],
    window_metrics: dict[str, object],
    is_final_day: bool,
) -> dict[str, object]:
    day_costs = summarize_costs(result.iloc[:24])
    tail_cost = (
        float(result.iloc[24:]["hourly_operating_cost_cny"].sum())
        if is_final_day
        else 0.0
    )
    return {
        "case": case_name,
        "day": day_number,
        **day_costs,
        "settlement_tail_operating_cost_cny": tail_cost,
        "initial_stored_energy_mwh": stored_energy_mwh,
        "committed_end_stored_energy_mwh": state.stored_energy_mwh,
        "coordinated_committed_stored_energy_mwh": (
            committed_energy_mwh
            if committed_energy_mwh is not None
            else initial_energy_mwh
        ),
        "window_terminal_stored_energy_mwh": (
            terminal_energy_mwh
            if terminal_energy_mwh is not None
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


def summarize_case_metrics(
    *,
    hourly: pd.DataFrame,
    workload: np.ndarray,
    params: Parameters,
    case_name: str,
    enable_shift: bool,
    enable_storage: bool,
    warmup_carry_in_cpu: float,
    warmup_metrics: dict[str, object] | None,
    coordination_metrics: dict[str, object] | None,
    rolling_metrics: list[dict[str, object]],
) -> dict[str, object]:
    costs = summarize_costs(hourly)
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
    analysis_days = len(workload) // 24
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
    initial_energy_mwh = (
        params.battery_soc_initial * params.battery_energy_mwh
    )
    metrics = {
        "case": case_name,
        "status": (
            "optimal"
            if all(
                metric["status"] == "optimal"
                for metric in all_solve_metrics
            )
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
            100.0
            * renewable_curtailment_energy
            / renewable_available_energy
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
        "mip_gap": float(
            max(metric["mip_gap"] for metric in all_solve_metrics)
        ),
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
    return metrics
