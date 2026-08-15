from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from pyscipopt import Model, quicksum

from ..config import Parameters
from .types import PendingFlexibleTask, WindowSolveState


_SETTLEMENT_TOLERANCE_USD = 1e-6
_WORK_DELAY_TOLERANCE_PU_HOURS = 1e-6
_CURTAILMENT_TOLERANCE_MWH = 1e-6
_STORAGE_BOUNDARY_TOLERANCE_MWH = 1e-9


def _require_accepted_solve_result(
    model: Model,
    *,
    stage: str,
    case_name: str,
    relative_gap: float,
) -> tuple[str, float]:
    status = str(model.getStatus())
    gap = float(model.getGap())
    details = (
        f"stage={stage}, case={case_name}, status={status}, gap={gap!r}, "
        f"primal_bound={float(model.getPrimalbound())!r}, "
        f"dual_bound={float(model.getDualbound())!r}"
    )
    if model.getNSols() == 0:
        raise RuntimeError(f"{details}, 未找到可行解。")
    accepted = status == "optimal" or (
        status == "gaplimit" and math.isfinite(gap) and gap <= relative_gap + 1e-12
    )
    if not accepted:
        raise RuntimeError(f"{details}, 求解结果未达到接受标准。")
    return status, gap


def _clamp_storage_boundary_energy(
    value: object,
    *,
    name: str,
    storage_min_mwh: float,
    storage_max_mwh: float,
) -> float:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} 超出储能电量边界。") from error
    if (
        not math.isfinite(numeric_value)
        or numeric_value < storage_min_mwh - _STORAGE_BOUNDARY_TOLERANCE_MWH
        or numeric_value > storage_max_mwh + _STORAGE_BOUNDARY_TOLERANCE_MWH
    ):
        raise ValueError(f"{name} 超出储能电量边界。")
    return min(max(numeric_value, storage_min_mwh), storage_max_mwh)


def _validated_profiles(
    *,
    workload_arrival_pu: np.ndarray,
    solar_available_mw: np.ndarray,
    wind_available_mw: np.ndarray,
    price_usd_per_mwh: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    profiles: dict[str, np.ndarray] = {}
    for name, raw_values, allow_negative in (
        ("workload_arrival_pu", workload_arrival_pu, False),
        ("solar_available_mw", solar_available_mw, False),
        ("wind_available_mw", wind_available_mw, False),
        ("price_usd_per_mwh", price_usd_per_mwh, True),
    ):
        values = np.asarray(raw_values, dtype=float).reshape(-1)
        if len(values) == 0:
            raise ValueError(f"{name} 必须为非空数组。")
        if not np.isfinite(values).all():
            raise ValueError(f"{name} 必须为有限值。")
        if not allow_negative and (values < 0.0).any():
            raise ValueError(f"{name} 必须为非负值。")
        profiles[name] = values
    workload = profiles["workload_arrival_pu"]
    for name in ("solar_available_mw", "wind_available_mw", "price_usd_per_mwh"):
        if len(profiles[name]) != len(workload):
            raise ValueError(f"{name} 长度必须与 workload_arrival_pu 一致。")
    return (
        workload,
        profiles["solar_available_mw"],
        profiles["wind_available_mw"],
        profiles["price_usd_per_mwh"],
    )


def build_and_solve_market_window(
    *,
    workload_arrival_pu: np.ndarray,
    solar_available_mw: np.ndarray,
    wind_available_mw: np.ndarray,
    price_usd_per_mwh: np.ndarray,
    params: Parameters,
    enable_shift: bool,
    enable_storage: bool,
    case_name: str,
    lp_output_dir: Path,
    show_log: bool,
    initial_stored_energy_mwh: float | None = None,
    terminal_stored_energy_mwh: float | None = None,
    committed_stored_energy_mwh: float | None = None,
    flex_arrival_hours: int | None = None,
    carry_in_tasks: tuple[PendingFlexibleTask, ...] = (),
    commit_hours: int | None = None,
    return_state: bool = False,
) -> (
    tuple[pd.DataFrame, dict]
    | tuple[pd.DataFrame, dict, WindowSolveState]
):
    """Solve one USD/MWh market-settled dispatch window.

    This solver intentionally uses only market grid settlement. It does not
    combine the existing CNY-denominated operating-cost parameters with USD.
    """
    workload, solar_available, wind_available, prices = _validated_profiles(
        workload_arrival_pu=workload_arrival_pu,
        solar_available_mw=solar_available_mw,
        wind_available_mw=wind_available_mw,
        price_usd_per_mwh=price_usd_per_mwh,
    )
    horizon = len(workload)
    if flex_arrival_hours is None:
        flex_arrival_hours = horizon
    if not isinstance(flex_arrival_hours, int) or not 0 <= flex_arrival_hours <= horizon:
        raise ValueError("flex_arrival_hours 必须位于 0 与优化时域长度之间。")
    if commit_hours is None:
        commit_hours = horizon
    if not isinstance(commit_hours, int) or not 1 <= commit_hours <= horizon:
        raise ValueError("commit_hours 必须位于 1 与优化时域长度之间。")

    carry_origins: set[int] = set()
    for task in carry_in_tasks:
        if not isinstance(task, PendingFlexibleTask):
            raise TypeError("carry_in_tasks 只能包含 PendingFlexibleTask。")
        if task.origin_hour >= 0 or task.origin_hour in carry_origins:
            raise ValueError("跨日遗留任务的 origin_hour 无效。")
        if not math.isfinite(task.remaining_cpu_pu) or task.remaining_cpu_pu <= 0.0:
            raise ValueError("跨日遗留任务量必须为有限正数。")
        if task.origin_hour + params.max_delay_h < 0:
            raise ValueError("跨日遗留任务已超过最大允许延迟。")
        carry_origins.add(task.origin_hour)
    if carry_in_tasks and not enable_shift:
        raise ValueError("存在跨日遗留任务时必须启用工作量转移。")

    nominal_initial_energy_mwh = params.battery_soc_initial * params.battery_energy_mwh
    if initial_stored_energy_mwh is None:
        initial_stored_energy_mwh = nominal_initial_energy_mwh
    if enable_storage:
        if not math.isfinite(params.battery_energy_mwh) or params.battery_energy_mwh <= 0.0:
            raise ValueError("enable_storage=True 时 battery_energy_mwh 必须大于 0。")
        storage_min_mwh = params.battery_soc_min * params.battery_energy_mwh
        storage_max_mwh = params.battery_soc_max * params.battery_energy_mwh
        initial_stored_energy_mwh = _clamp_storage_boundary_energy(
            initial_stored_energy_mwh,
            name="initial_stored_energy_mwh",
            storage_min_mwh=storage_min_mwh,
            storage_max_mwh=storage_max_mwh,
        )
        if terminal_stored_energy_mwh is not None:
            terminal_stored_energy_mwh = _clamp_storage_boundary_energy(
                terminal_stored_energy_mwh,
                name="terminal_stored_energy_mwh",
                storage_min_mwh=storage_min_mwh,
                storage_max_mwh=storage_max_mwh,
            )
        if committed_stored_energy_mwh is not None:
            committed_stored_energy_mwh = _clamp_storage_boundary_energy(
                committed_stored_energy_mwh,
                name="committed_stored_energy_mwh",
                storage_min_mwh=storage_min_mwh,
                storage_max_mwh=storage_max_mwh,
            )

    hours = range(horizon)
    model = Model(case_name)
    if not show_log:
        model.hideOutput()
    model.setParam("limits/time", params.time_limit_s)
    model.setParam("limits/gap", params.relative_gap)

    scheduled_workload = {
        hour: model.addVar(
            lb=0.0,
            ub=params.cpu_capacity_pu,
            vtype="C",
            name=f"workload_scheduled_{hour:02d}",
        )
        for hour in hours
    }
    shifted_workload: dict[tuple[int, int], object] = {}
    flexible_work_by_origin: dict[int, float] = {}
    if enable_shift:
        flexible_work_by_origin.update(
            {
                task.origin_hour: task.remaining_cpu_pu
                for task in carry_in_tasks
            }
        )
        flexible_work_by_origin.update(
            {
                origin: params.flex_ratio * float(workload[origin])
                for origin in range(flex_arrival_hours)
            }
        )
        for origin, flexible_work in flexible_work_by_origin.items():
            first_target = max(origin, 0)
            last_target = min(origin + params.max_delay_h, horizon - 1)
            if first_target > last_target:
                raise ValueError(f"origin_hour={origin} 的柔性工作无法完成。")
            for target in range(first_target, last_target + 1):
                shifted_workload[origin, target] = model.addVar(
                    lb=0.0,
                    vtype="C",
                    name=f"shifted_workload_{origin:02d}_{target:02d}",
                )
            model.addCons(
                quicksum(
                    shifted_workload[origin, target]
                    for target in range(first_target, last_target + 1)
                )
                == flexible_work,
                name=f"shift_conservation_{origin:02d}",
            )
        for target in hours:
            arrivals = quicksum(
                variable
                for (origin, shifted_target), variable in shifted_workload.items()
                if shifted_target == target
            )
            model.addCons(
                scheduled_workload[target]
                == (1.0 - params.flex_ratio) * float(workload[target]) + arrivals,
                name=f"scheduled_workload_balance_{target:02d}",
            )
    else:
        for hour in hours:
            model.addCons(
                scheduled_workload[hour] == float(workload[hour]),
                name=f"fixed_workload_{hour:02d}",
            )

    total_work_delay = quicksum(
        (target - origin) * variable
        for (origin, target), variable in shifted_workload.items()
    )
    idle_it_power_mw = params.it_power_mw(0.0)
    it_power_slope_mw = params.it_power_mw(1.0) - idle_it_power_mw
    it_power = {
        hour: model.addVar(lb=0.0, vtype="C", name=f"it_power_mw_{hour:02d}")
        for hour in hours
    }
    dc_power = {
        hour: model.addVar(lb=0.0, vtype="C", name=f"dc_power_mw_{hour:02d}")
        for hour in hours
    }
    grid_power = {
        hour: model.addVar(
            lb=0.0,
            ub=params.grid_capacity_mw,
            vtype="C",
            name=f"grid_power_mw_{hour:02d}",
        )
        for hour in hours
    }
    solar_used = {
        hour: model.addVar(
            lb=0.0,
            ub=float(solar_available[hour]),
            vtype="C",
            name=f"solar_used_mw_{hour:02d}",
        )
        for hour in hours
    }
    solar_curtailed = {
        hour: model.addVar(
            lb=0.0,
            ub=float(solar_available[hour]),
            vtype="C",
            name=f"solar_curtailed_mw_{hour:02d}",
        )
        for hour in hours
    }
    wind_used = {
        hour: model.addVar(
            lb=0.0,
            ub=float(wind_available[hour]),
            vtype="C",
            name=f"wind_used_mw_{hour:02d}",
        )
        for hour in hours
    }
    wind_curtailed = {
        hour: model.addVar(
            lb=0.0,
            ub=float(wind_available[hour]),
            vtype="C",
            name=f"wind_curtailed_mw_{hour:02d}",
        )
        for hour in hours
    }
    if enable_storage:
        charge_power = {
            hour: model.addVar(
                lb=0.0,
                ub=params.battery_charge_power_mw,
                vtype="C",
                name=f"charge_mw_{hour:02d}",
            )
            for hour in hours
        }
        discharge_power = {
            hour: model.addVar(
                lb=0.0,
                ub=params.battery_discharge_power_mw,
                vtype="C",
                name=f"discharge_mw_{hour:02d}",
            )
            for hour in hours
        }
        charge_active = {
            hour: model.addVar(vtype="B", name=f"charge_active_{hour:02d}")
            for hour in hours
        }
        discharge_active = {
            hour: model.addVar(vtype="B", name=f"discharge_active_{hour:02d}")
            for hour in hours
        }
        stored_energy = {
            hour: model.addVar(
                lb=params.battery_soc_min * params.battery_energy_mwh,
                ub=params.battery_soc_max * params.battery_energy_mwh,
                vtype="C",
                name=f"stored_energy_mwh_{hour:02d}",
            )
            for hour in range(horizon + 1)
        }
        model.addCons(
            stored_energy[0] == initial_stored_energy_mwh,
            name="stored_energy_initial",
        )
        if terminal_stored_energy_mwh is not None:
            model.addCons(
                stored_energy[horizon] == terminal_stored_energy_mwh,
                name="stored_energy_terminal",
            )
        if committed_stored_energy_mwh is not None:
            model.addCons(
                stored_energy[commit_hours] == committed_stored_energy_mwh,
                name="stored_energy_committed_boundary",
            )
        for hour in hours:
            model.addCons(
                charge_power[hour] <= params.battery_charge_power_mw * charge_active[hour],
                name=f"charge_activation_{hour:02d}",
            )
            model.addCons(
                discharge_power[hour]
                <= params.battery_discharge_power_mw * discharge_active[hour],
                name=f"discharge_activation_{hour:02d}",
            )
            model.addCons(
                charge_active[hour] + discharge_active[hour] <= 1,
                name=f"storage_mode_exclusion_{hour:02d}",
            )
            model.addCons(
                stored_energy[hour + 1]
                == stored_energy[hour]
                + params.charge_efficiency * charge_power[hour] * params.time_step_h
                - discharge_power[hour]
                * params.time_step_h
                / params.discharge_efficiency,
                name=f"stored_energy_balance_{hour:02d}",
            )
    else:
        charge_power = {hour: 0.0 for hour in hours}
        discharge_power = {hour: 0.0 for hour in hours}
        charge_active = {hour: 0.0 for hour in hours}
        discharge_active = {hour: 0.0 for hour in hours}
        stored_energy = {
            hour: nominal_initial_energy_mwh for hour in range(horizon + 1)
        }

    for hour in hours:
        model.addCons(
            it_power[hour]
            == idle_it_power_mw + it_power_slope_mw * scheduled_workload[hour],
            name=f"it_power_mapping_{hour:02d}",
        )
        model.addCons(
            dc_power[hour] == params.pue * it_power[hour],
            name=f"dc_power_mapping_{hour:02d}",
        )
        model.addCons(
            solar_used[hour] + solar_curtailed[hour] == float(solar_available[hour]),
            name=f"solar_allocation_{hour:02d}",
        )
        model.addCons(
            wind_used[hour] + wind_curtailed[hour] == float(wind_available[hour]),
            name=f"wind_allocation_{hour:02d}",
        )
        model.addCons(
            grid_power[hour]
            + solar_used[hour]
            + wind_used[hour]
            + discharge_power[hour]
            == dc_power[hour] + charge_power[hour],
            name=f"power_balance_{hour:02d}",
        )

    grid_settlement = quicksum(
        float(prices[hour]) * grid_power[hour] * params.time_step_h
        for hour in hours
    )
    renewable_curtailment = quicksum(
        (solar_curtailed[hour] + wind_curtailed[hour]) * params.time_step_h
        for hour in hours
    )
    battery_throughput = quicksum(
        (charge_power[hour] + discharge_power[hour]) * params.time_step_h
        for hour in hours
    )

    lp_directory = Path(lp_output_dir)
    lp_directory.mkdir(parents=True, exist_ok=True)
    model.setObjective(grid_settlement, "minimize")
    model.writeProblem(str(lp_directory / "stage_1_settlement.lp"), verbose=show_log)
    stage_started = time.perf_counter()
    model.optimize()
    settlement_solve_time_s = time.perf_counter() - stage_started
    settlement_status, settlement_gap = _require_accepted_solve_result(
        model,
        stage="settlement",
        case_name=case_name,
        relative_gap=params.relative_gap,
    )
    optimum_settlement = float(model.getVal(grid_settlement))

    model.freeTransform()
    model.addCons(
        grid_settlement <= optimum_settlement + _SETTLEMENT_TOLERANCE_USD,
        name="settlement_tolerance",
    )
    model.setObjective(total_work_delay, "minimize")
    model.writeProblem(str(lp_directory / "stage_2_delay.lp"), verbose=show_log)
    stage_started = time.perf_counter()
    model.optimize()
    delay_solve_time_s = time.perf_counter() - stage_started
    delay_status, delay_gap = _require_accepted_solve_result(
        model,
        stage="delay",
        case_name=case_name,
        relative_gap=params.relative_gap,
    )
    optimum_work_delay = float(model.getVal(total_work_delay))

    model.freeTransform()
    model.addCons(
        total_work_delay <= optimum_work_delay + _WORK_DELAY_TOLERANCE_PU_HOURS,
        name="work_delay_tolerance",
    )
    model.setObjective(renewable_curtailment, "minimize")
    model.writeProblem(str(lp_directory / "stage_3_curtailment.lp"), verbose=show_log)
    stage_started = time.perf_counter()
    model.optimize()
    curtailment_solve_time_s = time.perf_counter() - stage_started
    curtailment_status, curtailment_gap = _require_accepted_solve_result(
        model,
        stage="curtailment",
        case_name=case_name,
        relative_gap=params.relative_gap,
    )
    optimum_curtailment = float(model.getVal(renewable_curtailment))

    model.freeTransform()
    model.addCons(
        renewable_curtailment
        <= optimum_curtailment + _CURTAILMENT_TOLERANCE_MWH,
        name="curtailment_tolerance",
    )
    model.setObjective(battery_throughput, "minimize")
    model.writeProblem(str(lp_directory / "stage_4_throughput.lp"), verbose=show_log)
    stage_started = time.perf_counter()
    model.optimize()
    throughput_solve_time_s = time.perf_counter() - stage_started
    throughput_status, throughput_gap = _require_accepted_solve_result(
        model,
        stage="throughput",
        case_name=case_name,
        relative_gap=params.relative_gap,
    )

    def solution_value(variable: object) -> float:
        if isinstance(variable, (int, float)):
            return float(variable)
        return float(model.getVal(variable))

    stored_energy_start = np.array(
        [solution_value(stored_energy[hour]) for hour in hours], dtype=float
    )
    stored_energy_end = np.array(
        [solution_value(stored_energy[hour + 1]) for hour in hours], dtype=float
    )
    result = pd.DataFrame(
        {
            "case": case_name,
            "hour": np.arange(horizon, dtype=int),
            "workload_arrival_pu": workload,
            "workload_scheduled_pu": np.array(
                [model.getVal(scheduled_workload[hour]) for hour in hours],
                dtype=float,
            ),
            "it_power_mw": np.array(
                [model.getVal(it_power[hour]) for hour in hours], dtype=float
            ),
            "dc_power_mw": np.array(
                [model.getVal(dc_power[hour]) for hour in hours], dtype=float
            ),
            "grid_power_mw": np.array(
                [model.getVal(grid_power[hour]) for hour in hours], dtype=float
            ),
            "solar_available_mw": solar_available,
            "solar_used_mw": np.array(
                [model.getVal(solar_used[hour]) for hour in hours], dtype=float
            ),
            "solar_curtailed_mw": np.array(
                [model.getVal(solar_curtailed[hour]) for hour in hours], dtype=float
            ),
            "wind_available_mw": wind_available,
            "wind_used_mw": np.array(
                [model.getVal(wind_used[hour]) for hour in hours], dtype=float
            ),
            "wind_curtailed_mw": np.array(
                [model.getVal(wind_curtailed[hour]) for hour in hours], dtype=float
            ),
            "charge_mw": np.array(
                [solution_value(charge_power[hour]) for hour in hours], dtype=float
            ),
            "discharge_mw": np.array(
                [solution_value(discharge_power[hour]) for hour in hours], dtype=float
            ),
            "stored_energy_start_mwh": stored_energy_start,
            "stored_energy_end_mwh": stored_energy_end,
            "price_usd_per_mwh": prices,
        }
    )
    result["hourly_grid_settlement_usd"] = (
        result["price_usd_per_mwh"]
        * result["grid_power_mw"]
        * params.time_step_h
    )
    assignment_values = [
        (origin, target, solution_value(variable))
        for (origin, target), variable in shifted_workload.items()
    ]
    flexible_work_total = float(sum(flexible_work_by_origin.values()))
    total_work_delay_value = float(model.getVal(total_work_delay))
    maximum_work_delay_h = max(
        (
            target - origin
            for origin, target, value in assignment_values
            if value > 1e-8
        ),
        default=0,
    )
    renewable_available_energy = float(
        (result["solar_available_mw"] + result["wind_available_mw"]).sum()
        * params.time_step_h
    )
    renewable_curtailment_energy = float(
        (result["solar_curtailed_mw"] + result["wind_curtailed_mw"]).sum()
        * params.time_step_h
    )
    status = (
        "optimal"
        if all(
            current_status == "optimal"
            for current_status in (
                settlement_status,
                delay_status,
                curtailment_status,
                throughput_status,
            )
        )
        else "gaplimit"
    )
    metrics = {
        "case": case_name,
        "status": status,
        "grid_settlement_usd": float(result["hourly_grid_settlement_usd"].sum()),
        "grid_purchase_energy_mwh": float(
            result["grid_power_mw"].sum() * params.time_step_h
        ),
        "renewable_available_energy_mwh": renewable_available_energy,
        "renewable_curtailment_energy_mwh": renewable_curtailment_energy,
        "battery_charged_energy_mwh": float(
            result["charge_mw"].sum() * params.time_step_h
        ),
        "battery_discharged_energy_mwh": float(
            result["discharge_mw"].sum() * params.time_step_h
        ),
        "workload_conservation_error": float(
            abs(
                result["workload_scheduled_pu"].sum()
                - (
                    (1.0 - params.flex_ratio) * result["workload_arrival_pu"].sum()
                    + flexible_work_total
                )
            )
            if enable_shift
            else abs(
                result["workload_scheduled_pu"].sum()
                - result["workload_arrival_pu"].sum()
            )
        ),
        "flexible_work_pu_hours": flexible_work_total,
        "total_work_delay_pu_hours": total_work_delay_value,
        "average_flexible_work_delay_h": (
            total_work_delay_value / flexible_work_total
            if flexible_work_total > 0.0
            else 0.0
        ),
        "maximum_work_delay_h": maximum_work_delay_h,
        "settlement_solve_status": settlement_status,
        "delay_solve_status": delay_status,
        "curtailment_solve_status": curtailment_status,
        "throughput_solve_status": throughput_status,
        "settlement_gap": settlement_gap,
        "delay_gap": delay_gap,
        "curtailment_gap": curtailment_gap,
        "throughput_gap": throughput_gap,
        "settlement_solve_time_s": settlement_solve_time_s,
        "delay_solve_time_s": delay_solve_time_s,
        "curtailment_solve_time_s": curtailment_solve_time_s,
        "throughput_solve_time_s": throughput_solve_time_s,
    }
    if return_state:
        pending_tasks = tuple(
            PendingFlexibleTask(
                origin_hour=origin,
                remaining_cpu_pu=float(
                    sum(
                        solution_value(variable)
                        for (shift_origin, target), variable in shifted_workload.items()
                        if shift_origin == origin and target >= commit_hours
                    )
                ),
            )
            for origin in sorted(flexible_work_by_origin)
            if sum(
                solution_value(variable)
                for (shift_origin, target), variable in shifted_workload.items()
                if shift_origin == origin and target >= commit_hours
            )
            > 1e-8
        )
        return result, metrics, WindowSolveState(
            stored_energy_mwh=solution_value(stored_energy[commit_hours]),
            pending_flexible_tasks=pending_tasks,
        )
    return result, metrics
