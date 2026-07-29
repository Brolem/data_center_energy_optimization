from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from pyscipopt import Model, quicksum

from .config import Parameters


def build_and_solve(
    cpu_arrival: np.ndarray,
    params: Parameters,
    enable_shift: bool,
    enable_storage: bool,
    case_name: str,
    output_dir: Path,
    show_log: bool,
) -> tuple[pd.DataFrame, dict]:
    T = len(cpu_arrival)
    hours = range(T)
    model = Model(case_name)
    if not show_log:
        model.hideOutput()

    model.setParam("limits/time", params.time_limit_s)
    model.setParam("limits/gap", params.relative_gap)

    u = {
        t: model.addVar(
            lb=0.0,
            ub=params.cpu_capacity_pu,
            vtype="C",
            name=f"cpu_scheduled_{t:02d}",
        )
        for t in hours
    }

    shift_vars: dict[tuple[int, int], object] = {}
    if enable_shift:
        for origin in hours:
            latest = min(origin + params.max_delay_h, T - 1)
            for target in range(origin, latest + 1):
                shift_vars[origin, target] = model.addVar(
                    lb=0.0,
                    vtype="C",
                    name=f"shift_{origin:02d}_to_{target:02d}",
                )

        for origin in hours:
            latest = min(origin + params.max_delay_h, T - 1)
            model.addCons(
                quicksum(
                    shift_vars[origin, target]
                    for target in range(origin, latest + 1)
                )
                == params.flex_ratio * float(cpu_arrival[origin]),
                name=f"flex_conservation_{origin:02d}",
            )

        for target in hours:
            eligible_origins = range(max(0, target - params.max_delay_h), target + 1)
            model.addCons(
                u[target]
                == (1.0 - params.flex_ratio) * float(cpu_arrival[target])
                + quicksum(
                    shift_vars[origin, target]
                    for origin in eligible_origins
                    if (origin, target) in shift_vars
                ),
                name=f"scheduled_cpu_balance_{target:02d}",
            )
    else:
        for t in hours:
            model.addCons(
                u[t] == float(cpu_arrival[t]),
                name=f"fixed_cpu_{t:02d}",
            )

    p_it = {
        t: model.addVar(lb=0.0, vtype="C", name=f"p_it_mw_{t:02d}")
        for t in hours
    }
    p_dc = {
        t: model.addVar(lb=0.0, vtype="C", name=f"p_dc_mw_{t:02d}")
        for t in hours
    }
    for t in hours:
        model.addCons(
            p_it[t]
            == params.it_peak_power_mw
            * (
                params.idle_power_ratio
                + (1.0 - params.idle_power_ratio) * u[t]
            ),
            name=f"it_power_mapping_{t:02d}",
        )
        model.addCons(
            p_dc[t] == params.pue * p_it[t],
            name=f"pue_mapping_{t:02d}",
        )

    p_grid = {
        t: model.addVar(lb=0.0, vtype="C", name=f"p_grid_mw_{t:02d}")
        for t in hours
    }

    if enable_storage:
        p_ch = {
            t: model.addVar(
                lb=0.0,
                ub=params.battery_power_mw,
                vtype="C",
                name=f"p_charge_mw_{t:02d}",
            )
            for t in hours
        }
        p_dis = {
            t: model.addVar(
                lb=0.0,
                ub=params.battery_power_mw,
                vtype="C",
                name=f"p_discharge_mw_{t:02d}",
            )
            for t in hours
        }
        charge_mode = {
            t: model.addVar(vtype="B", name=f"charge_mode_{t:02d}")
            for t in hours
        }
        e_min = params.battery_soc_min * params.battery_energy_mwh
        e_max = params.battery_soc_max * params.battery_energy_mwh
        e_initial = params.battery_soc_initial * params.battery_energy_mwh
        energy = {
            t: model.addVar(
                lb=e_min,
                ub=e_max,
                vtype="C",
                name=f"energy_mwh_{t:02d}",
            )
            for t in range(T + 1)
        }
        model.addCons(energy[0] == e_initial, name="initial_energy")
        model.addCons(energy[T] == e_initial, name="terminal_energy")

        for t in hours:
            model.addCons(
                p_ch[t] <= params.battery_power_mw * charge_mode[t],
                name=f"charge_exclusive_{t:02d}",
            )
            model.addCons(
                p_dis[t]
                <= params.battery_power_mw * (1 - charge_mode[t]),
                name=f"discharge_exclusive_{t:02d}",
            )
            model.addCons(
                energy[t + 1]
                == energy[t]
                + params.charge_efficiency
                * p_ch[t]
                * params.time_step_h
                - p_dis[t]
                * params.time_step_h
                / params.discharge_efficiency,
                name=f"energy_balance_{t:02d}",
            )
            model.addCons(
                p_grid[t] == p_dc[t] + p_ch[t] - p_dis[t],
                name=f"grid_balance_{t:02d}",
            )
    else:
        p_ch = {}
        p_dis = {}
        energy = {}
        for t in hours:
            model.addCons(
                p_grid[t] == p_dc[t],
                name=f"grid_without_storage_{t:02d}",
            )

    ramp = {
        t: model.addVar(lb=0.0, vtype="C", name=f"absolute_ramp_{t:02d}")
        for t in range(1, T)
    }
    for t in range(1, T):
        model.addCons(
            ramp[t] >= p_grid[t] - p_grid[t - 1],
            name=f"ramp_positive_{t:02d}",
        )
        model.addCons(
            ramp[t] >= p_grid[t - 1] - p_grid[t],
            name=f"ramp_negative_{t:02d}",
        )

    objective = quicksum(ramp[t] for t in range(1, T))
    if enable_storage:
        objective += params.throughput_tiebreaker * quicksum(
            p_ch[t] + p_dis[t] for t in hours
        )
    model.setObjective(objective, "minimize")
    model.writeProblem(str(output_dir / f"{case_name}.lp"))
    model.optimize()

    status = str(model.getStatus())
    if model.getNSols() == 0:
        raise RuntimeError(f"{case_name} 未找到可行解，SCIP 状态: {status}")

    scheduled = np.array([model.getVal(u[t]) for t in hours])
    it_power = np.array([model.getVal(p_it[t]) for t in hours])
    dc_power = np.array([model.getVal(p_dc[t]) for t in hours])
    grid_power = np.array([model.getVal(p_grid[t]) for t in hours])

    if enable_storage:
        charge = np.array([model.getVal(p_ch[t]) for t in hours])
        discharge = np.array([model.getVal(p_dis[t]) for t in hours])
        soc = np.array(
            [
                model.getVal(energy[t]) / params.battery_energy_mwh
                for t in range(T + 1)
            ]
        )
    else:
        charge = np.zeros(T)
        discharge = np.zeros(T)
        soc = np.full(T + 1, np.nan)

    result = pd.DataFrame(
        {
            "case": case_name,
            "hour": np.arange(T),
            "cpu_arrival_pu": cpu_arrival,
            "cpu_scheduled_pu": scheduled,
            "it_power_mw": it_power,
            "dc_power_mw": dc_power,
            "charge_mw": charge,
            "discharge_mw": discharge,
            "grid_power_mw": grid_power,
            "soc_start": soc[:-1],
            "soc_end": soc[1:],
        }
    )

    differences = np.diff(grid_power)
    finite_gap = float(model.getGap())
    if not math.isfinite(finite_gap):
        finite_gap = np.nan
    metrics = {
        "case": case_name,
        "shift_enabled": enable_shift,
        "storage_enabled": enable_storage,
        "status": status,
        "total_variation_mw": float(np.abs(differences).sum()),
        "max_ramp_mw": float(np.abs(differences).max()),
        "peak_grid_power_mw": float(grid_power.max()),
        "mean_grid_power_mw": float(grid_power.mean()),
        "std_grid_power_mw": float(grid_power.std(ddof=0)),
        "grid_energy_mwh": float(grid_power.sum() * params.time_step_h),
        "cpu_conservation_error": float(
            abs(scheduled.sum() - cpu_arrival.sum())
        ),
        "soc_cycle_error": (
            float(abs(soc[-1] - soc[0])) if enable_storage else np.nan
        ),
        "max_simultaneous_charge_discharge_mw": (
            float(np.minimum(charge, discharge).max())
            if enable_storage
            else 0.0
        ),
        "solve_time_s": float(model.getSolvingTime()),
        "mip_gap": float(finite_gap),
        "nodes": int(model.getNNodes()),
        "variables": int(model.getNVars()),
        "constraints": int(model.getNConss()),
        "scip_objective": float(model.getObjVal()),
    }
    return result, metrics
