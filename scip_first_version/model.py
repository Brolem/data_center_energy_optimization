from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from pyscipopt import Model, quicksum

from .config import Parameters


def build_and_solve(
    cpu_arrival: np.ndarray,
    solar_available_mw: np.ndarray,
    wind_available_mw: np.ndarray,
    electricity_price_cny_per_kwh: np.ndarray,
    params: Parameters,
    enable_shift: bool,
    enable_storage: bool,
    enable_renewables: bool,
    case_name: str,
    output_dir: Path,
    show_log: bool,
) -> tuple[pd.DataFrame, dict]:
    profiles: dict[str, np.ndarray] = {}
    for profile_name, profile_values in (
        ("cpu_arrival", cpu_arrival),
        ("solar_available_mw", solar_available_mw),
        ("wind_available_mw", wind_available_mw),
        (
            "electricity_price_cny_per_kwh",
            electricity_price_cny_per_kwh,
        ),
    ):
        values = np.asarray(profile_values, dtype=float).reshape(-1)
        if len(values) == 0:
            raise ValueError(f"{profile_name} 必须为非空数组。")
        if not np.isfinite(values).all():
            raise ValueError(f"{profile_name} 必须为有限值。")
        if (values < 0.0).any():
            raise ValueError(f"{profile_name} 必须为非负值。")
        profiles[profile_name] = values

    cpu_arrival = profiles["cpu_arrival"]
    T = len(cpu_arrival)
    for profile_name in (
        "solar_available_mw",
        "wind_available_mw",
        "electricity_price_cny_per_kwh",
    ):
        if len(profiles[profile_name]) != T:
            raise ValueError(f"{profile_name} 长度必须与 cpu_arrival 一致。")

    if enable_storage:
        raise NotImplementedError("本阶段不支持储能一级优化。")

    solar_input = profiles["solar_available_mw"]
    wind_input = profiles["wind_available_mw"]
    electricity_price_cny_per_kwh = profiles[
        "electricity_price_cny_per_kwh"
    ]
    if enable_renewables:
        solar_available = solar_input.copy()
        wind_available = wind_input.copy()
    else:
        solar_available = np.zeros(T, dtype=float)
        wind_available = np.zeros(T, dtype=float)

    hours = range(T)
    model = Model(case_name)
    if not show_log:
        model.hideOutput()
    model.setParam("limits/time", params.time_limit_s)
    model.setParam("limits/gap", params.relative_gap)

    scheduled_cpu = {
        t: model.addVar(
            lb=0.0,
            ub=params.cpu_capacity_pu,
            vtype="C",
            name=f"cpu_scheduled_{t:02d}",
        )
        for t in hours
    }

    if enable_shift:
        shifted_cpu = {}
        for origin in hours:
            last_target = min(origin + params.max_delay_h, T - 1)
            for target in range(origin, last_target + 1):
                shifted_cpu[origin, target] = model.addVar(
                    lb=0.0,
                    vtype="C",
                    name=f"shifted_cpu_{origin:02d}_{target:02d}",
                )
            model.addCons(
                quicksum(
                    shifted_cpu[origin, target]
                    for target in range(origin, last_target + 1)
                )
                == params.flex_ratio * float(cpu_arrival[origin]),
                name=f"shift_conservation_{origin:02d}",
            )

        for target in hours:
            arrivals_at_target = quicksum(
                variable
                for (origin, shifted_target), variable in shifted_cpu.items()
                if shifted_target == target
            )
            model.addCons(
                scheduled_cpu[target]
                == (1.0 - params.flex_ratio)
                * float(cpu_arrival[target])
                + arrivals_at_target,
                name=f"scheduled_cpu_balance_{target:02d}",
            )
    else:
        for t in hours:
            model.addCons(
                scheduled_cpu[t] == float(cpu_arrival[t]),
                name=f"fixed_cpu_{t:02d}",
            )

    idle_it_power_mw = params.it_power_mw(0.0)
    it_power_slope_mw = params.it_power_mw(1.0) - idle_it_power_mw
    it_power = {
        t: model.addVar(lb=0.0, vtype="C", name=f"it_power_mw_{t:02d}")
        for t in hours
    }
    dc_power = {
        t: model.addVar(lb=0.0, vtype="C", name=f"dc_power_mw_{t:02d}")
        for t in hours
    }
    grid_power = {
        t: model.addVar(
            lb=0.0,
            ub=params.grid_capacity_mw,
            vtype="C",
            name=f"grid_power_mw_{t:02d}",
        )
        for t in hours
    }
    solar_used = {
        t: model.addVar(
            lb=0.0,
            ub=float(solar_available[t]),
            vtype="C",
            name=f"solar_used_mw_{t:02d}",
        )
        for t in hours
    }
    solar_curtailed = {
        t: model.addVar(
            lb=0.0,
            ub=float(solar_available[t]),
            vtype="C",
            name=f"solar_curtailed_mw_{t:02d}",
        )
        for t in hours
    }
    wind_used = {
        t: model.addVar(
            lb=0.0,
            ub=float(wind_available[t]),
            vtype="C",
            name=f"wind_used_mw_{t:02d}",
        )
        for t in hours
    }
    wind_curtailed = {
        t: model.addVar(
            lb=0.0,
            ub=float(wind_available[t]),
            vtype="C",
            name=f"wind_curtailed_mw_{t:02d}",
        )
        for t in hours
    }
    charge_power = {t: 0.0 for t in hours}
    discharge_power = {t: 0.0 for t in hours}

    for t in hours:
        model.addCons(
            it_power[t]
            == idle_it_power_mw + it_power_slope_mw * scheduled_cpu[t],
            name=f"it_power_mapping_{t:02d}",
        )
        model.addCons(
            dc_power[t] == params.pue * it_power[t],
            name=f"dc_power_mapping_{t:02d}",
        )
        model.addCons(
            solar_used[t] + solar_curtailed[t]
            == float(solar_available[t]),
            name=f"solar_allocation_{t:02d}",
        )
        model.addCons(
            wind_used[t] + wind_curtailed[t]
            == float(wind_available[t]),
            name=f"wind_allocation_{t:02d}",
        )
        model.addCons(
            grid_power[t] + solar_used[t] + wind_used[t] == dc_power[t],
            name=f"power_balance_{t:02d}",
        )

    grid_purchase_cost = quicksum(
        float(electricity_price_cny_per_kwh[t])
        * grid_power[t]
        * params.time_step_h
        * 1000.0
        for t in hours
    )
    solar_om_cost = quicksum(
        params.solar_om_cost_cny_per_kw
        * solar_used[t]
        * params.time_step_h
        * 1000.0
        for t in hours
    )
    wind_om_cost = quicksum(
        params.wind_om_cost_cny_per_kw
        * wind_used[t]
        * params.time_step_h
        * 1000.0
        for t in hours
    )
    battery_om_cost_expr = quicksum(
        params.battery_om_cost_cny_per_kw
        * (charge_power[t] + discharge_power[t])
        * params.time_step_h
        * 1000.0
        for t in hours
    )
    primary_cost_expr = (
        grid_purchase_cost
        + solar_om_cost
        + wind_om_cost
        + battery_om_cost_expr
    )
    model.setObjective(primary_cost_expr, "minimize")

    output_dir = Path(output_dir)
    model.writeProblem(str(output_dir / f"{case_name}_primary.lp"))
    model.optimize()

    status = str(model.getStatus())
    if model.getNSols() == 0:
        raise RuntimeError(f"{case_name} 未找到可行解，SCIP 状态: {status}")

    result = pd.DataFrame(
        {
            "case": case_name,
            "hour": np.arange(T, dtype=int),
            "cpu_arrival_pu": cpu_arrival,
            "cpu_scheduled_pu": np.array(
                [model.getVal(scheduled_cpu[t]) for t in hours]
            ),
            "it_power_mw": np.array(
                [model.getVal(it_power[t]) for t in hours]
            ),
            "dc_power_mw": np.array(
                [model.getVal(dc_power[t]) for t in hours]
            ),
            "grid_power_mw": np.array(
                [model.getVal(grid_power[t]) for t in hours]
            ),
            "solar_available_mw": solar_available,
            "solar_used_mw": np.array(
                [model.getVal(solar_used[t]) for t in hours]
            ),
            "solar_curtailed_mw": np.array(
                [model.getVal(solar_curtailed[t]) for t in hours]
            ),
            "wind_available_mw": wind_available,
            "wind_used_mw": np.array(
                [model.getVal(wind_used[t]) for t in hours]
            ),
            "wind_curtailed_mw": np.array(
                [model.getVal(wind_curtailed[t]) for t in hours]
            ),
            "charge_mw": np.array(
                [charge_power[t] for t in hours], dtype=float
            ),
            "discharge_mw": np.array(
                [discharge_power[t] for t in hours], dtype=float
            ),
            "soc_start": np.full(T, params.battery_soc_initial, dtype=float),
            "soc_end": np.full(T, params.battery_soc_initial, dtype=float),
            "electricity_price_cny_per_kwh": (
                electricity_price_cny_per_kwh
            ),
        }
    )

    result["hourly_grid_purchase_cost_cny"] = (
        result["electricity_price_cny_per_kwh"]
        * result["grid_power_mw"]
        * params.time_step_h
        * 1000.0
    )
    result["hourly_solar_om_cost_cny"] = (
        params.solar_om_cost_cny_per_kw
        * result["solar_used_mw"]
        * params.time_step_h
        * 1000.0
    )
    result["hourly_wind_om_cost_cny"] = (
        params.wind_om_cost_cny_per_kw
        * result["wind_used_mw"]
        * params.time_step_h
        * 1000.0
    )
    result["hourly_battery_om_cost_cny"] = (
        params.battery_om_cost_cny_per_kw
        * (result["charge_mw"] + result["discharge_mw"])
        * params.time_step_h
        * 1000.0
    )
    result["hourly_operating_cost_cny"] = result[
        [
            "hourly_grid_purchase_cost_cny",
            "hourly_solar_om_cost_cny",
            "hourly_wind_om_cost_cny",
            "hourly_battery_om_cost_cny",
        ]
    ].sum(axis=1)

    grid_purchase_cost_value = float(
        result["hourly_grid_purchase_cost_cny"].sum()
    )
    solar_om_cost_value = float(result["hourly_solar_om_cost_cny"].sum())
    wind_om_cost_value = float(result["hourly_wind_om_cost_cny"].sum())
    battery_om_cost_value = float(
        result["hourly_battery_om_cost_cny"].sum()
    )
    operating_cost_value = (
        grid_purchase_cost_value
        + solar_om_cost_value
        + wind_om_cost_value
        + battery_om_cost_value
    )
    renewable_available_energy = float(
        (
            result["solar_available_mw"]
            + result["wind_available_mw"]
        ).sum()
        * params.time_step_h
    )
    renewable_used_energy = float(
        (result["solar_used_mw"] + result["wind_used_mw"]).sum()
        * params.time_step_h
    )
    renewable_curtailment_energy = float(
        (
            result["solar_curtailed_mw"]
            + result["wind_curtailed_mw"]
        ).sum()
        * params.time_step_h
    )
    renewable_curtailment_rate = (
        100.0
        * renewable_curtailment_energy
        / renewable_available_energy
        if renewable_available_energy > 0.0
        else 0.0
    )
    mip_gap = float(model.getGap())
    if not math.isfinite(mip_gap):
        mip_gap = np.nan

    metrics = {
        "case": case_name,
        "status": status,
        "shift_enabled": enable_shift,
        "storage_enabled": enable_storage,
        "renewables_enabled": enable_renewables,
        "grid_purchase_cost_cny": grid_purchase_cost_value,
        "solar_om_cost_cny": solar_om_cost_value,
        "wind_om_cost_cny": wind_om_cost_value,
        "battery_om_cost_cny": battery_om_cost_value,
        "operating_cost_cny": operating_cost_value,
        "grid_purchase_energy_mwh": float(
            result["grid_power_mw"].sum() * params.time_step_h
        ),
        "grid_peak_power_mw": float(result["grid_power_mw"].max()),
        "grid_mean_power_mw": float(result["grid_power_mw"].mean()),
        "renewable_available_energy_mwh": renewable_available_energy,
        "renewable_used_energy_mwh": renewable_used_energy,
        "renewable_curtailment_energy_mwh": (
            renewable_curtailment_energy
        ),
        "renewable_curtailment_rate_pct": renewable_curtailment_rate,
        "cpu_conservation_error": float(
            abs(
                result["cpu_scheduled_pu"].sum()
                - result["cpu_arrival_pu"].sum()
            )
        ),
        "solve_time_s": float(model.getSolvingTime()),
        "mip_gap": mip_gap,
        "primary_operating_cost_cny": operating_cost_value,
    }
    return result, metrics
