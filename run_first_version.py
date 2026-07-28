from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib-cache")
)

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyscipopt import Model, quicksum


@dataclass(frozen=True)
class Parameters:
    flex_ratio: float = 0.30
    max_delay_h: int = 3
    cpu_capacity_pu: float = 0.65
    idle_power_ratio: float = 0.60
    it_peak_power_mw: float = 100.0
    pue: float = 1.20
    battery_energy_mwh: float = 4.0
    battery_soc_min: float = 0.10
    battery_soc_max: float = 0.90
    battery_soc_initial: float = 0.50
    battery_power_mw: float = 1.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    time_step_h: float = 1.0
    time_limit_s: float = 60.0
    relative_gap: float = 1e-3
    throughput_tiebreaker: float = 1e-6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Google 2019 聚合 CPU 轨迹：算力时移 + 储能 + 并网功率平滑第一版"
    )
    parser.add_argument(
        "--input",
        default="data/instance_usage_grouped_300_seconds_month.csv",
        help="8064 行 Google 2019 instance usage 聚合 CSV",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/first_version",
        help="结果输出目录",
    )
    parser.add_argument(
        "--day",
        type=int,
        default=None,
        help="指定第 1~28 天；省略则自动选择最接近 28 天平均曲线的代表日",
    )
    parser.add_argument(
        "--show-scip-log",
        action="store_true",
        help="显示 SCIP 求解日志",
    )
    return parser.parse_args()


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

    profiles = hourly.pivot(index="day", columns="hour", values="avg_cpu") #二维矩阵
    mean_profile = profiles.mean(axis=0) #按列求平均值，得到平均曲线
    representative_day = int(np.sqrt(((profiles - mean_profile) ** 2).mean(axis=1)).idxmin()) #按行求均方差，找到均方差最小的那一天
    stress_day = int(profiles.std(axis=1).idxmax()) #按行求标准差，找到标准差最大的那一天
    return raw, hourly, representative_day, stress_day


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
            vtype="C", #定义连续变量
            name=f"cpu_scheduled_{t:02d}",
        )
        for t in hours
    }

    #柔性算力时移
    shift_vars: dict[tuple[int, int], object] = {} #时移负荷量
    if enable_shift: #是否时移
        for origin in hours:
            latest = min(origin + params.max_delay_h, T - 1) #允许的最晚时移时间
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
    
    #CPU到数据中心功率的映射
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

    #并网功率变量
    p_grid = {
        t: model.addVar(lb=0.0, vtype="C", name=f"p_grid_mw_{t:02d}")
        for t in hours
    }

    #储能SOC
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

    #爬坡变量
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
        "max_simultaneous_charge_discharge_mw": ( #为0表示没有同时充放电
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


def make_plots(
    all_results: pd.DataFrame,
    metrics: pd.DataFrame,
    output_dir: Path,
) -> None:
    colors = {
        "baseline": "#6B7280",
        "shift_only": "#2563EB",
        "storage_only": "#F59E0B",
        "joint": "#DC2626",
    }
    labels = {
        "baseline": "Baseline",
        "shift_only": "Workload shift",
        "storage_only": "Battery",
        "joint": "Shift + battery",
    }
    
    #图1
    hours = np.arange(24)

    plt.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC",
        "Microsoft YaHei",
        "SimHei",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)

    #原始与调度后算力负荷
    baseline = all_results[all_results["case"] == "baseline"]
    joint = all_results[all_results["case"] == "joint"]
    axes[0, 0].plot(
        hours,
        baseline["cpu_arrival_pu"],
        color=colors["baseline"],
        marker="o",
        markersize=3,
        label="Original CPU",
    )
    axes[0, 0].plot(
        hours,
        joint["cpu_scheduled_pu"],
        color=colors["joint"],
        marker="o",
        markersize=3,
        label="Jointly scheduled CPU",
    )
    axes[0, 0].set_title("Aggregated CPU load")
    axes[0, 0].set_ylabel("CPU utilization (p.u.)")
    axes[0, 0].legend()

    #四种算例的并网功率
    for case_name in ["baseline", "shift_only", "storage_only", "joint"]:
        data = all_results[all_results["case"] == case_name]
        axes[0, 1].plot(
            hours,
            data["grid_power_mw"],
            color=colors[case_name],
            linewidth=2 if case_name == "joint" else 1.5,
            label=labels[case_name],
        )
    axes[0, 1].set_title("Grid power in four cases")
    axes[0, 1].set_ylabel("Grid power (MW)")
    axes[0, 1].legend(fontsize=9)

    #储能充放电功率
    axes[1, 0].bar(
        hours,
        joint["charge_mw"],
        width=0.36,
        color="#3B82F6",
        label="Charge",
    )
    axes[1, 0].bar(
        hours,
        -joint["discharge_mw"],
        width=0.36,
        color="#F97316",
        label="Discharge",
    )
    axes[1, 0].axhline(0, color="#374151", linewidth=0.8)
    axes[1, 0].set_title("Joint case: battery operation")
    axes[1, 0].set_ylabel("Power (MW)")
    axes[1, 0].legend()

    #储能SOC
    axes[1, 1].step(
        np.arange(25),
        np.r_[joint["soc_start"].iloc[0], joint["soc_end"].to_numpy()],
        where="post",
        color="#059669",
        linewidth=2,
    )
    axes[1, 1].axhline(0.1, color="#9CA3AF", linestyle="--", linewidth=1)
    axes[1, 1].axhline(0.9, color="#9CA3AF", linestyle="--", linewidth=1)
    axes[1, 1].set_ylim(0, 1)
    axes[1, 1].set_title("Joint case: battery SOC")
    axes[1, 1].set_ylabel("SOC")

    for ax in axes.flat:
        ax.set_xlabel("Hour")
        ax.set_xticks(np.arange(0, 24, 3))
        ax.grid(True, alpha=0.2)

    fig.suptitle("Google 2019 aggregated trace: first SCIP results", fontsize=16)
    fig.savefig(output_dir / "first_version_results.png", dpi=180)
    plt.close(fig)

    #图2：总波动量对比
    ordered = metrics.set_index("case").loc[
        ["baseline", "shift_only", "storage_only", "joint"]
    ]
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    bars = ax.bar(
        [labels[x] for x in ordered.index],
        ordered["total_variation_mw"],
        color=[colors[x] for x in ordered.index],
    )
    ax.bar_label(bars, fmt="%.2f", padding=3)
    ax.set_ylabel("Total variation (MW)")
    ax.set_title("Grid-power variation (lower is better)")
    ax.grid(axis="y", alpha=0.2)
    fig.savefig(output_dir / "total_variation_comparison.png", dpi=180)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    csv_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    params = Parameters()

    raw, hourly, representative_day, stress_day = load_and_prepare(csv_path)
    selected_day = args.day if args.day is not None else representative_day #指定哪天否则用代表天
    max_day = int(hourly["day"].max())
    if not 1 <= selected_day <= max_day:
        raise ValueError(f"--day 应在 1 到 {max_day} 之间。")

    selected = (hourly[hourly["day"] == selected_day].sort_values("hour").reset_index(drop=True))
    if len(selected) != 24:
        raise ValueError("所选日不是完整的 24 个小时。")

    # cpu_arrival_pu 为每小时到达的CPU需求
    selected.rename(columns={"avg_cpu": "cpu_arrival_pu"}).to_csv(
        output_dir / "scip_input_representative_day.csv",
        index=False,
    )
    hourly.to_csv(output_dir / "all_days_hourly.csv", index=False)

    cases = [
        ("baseline", False, False),
        ("shift_only", True, False),
        ("storage_only", False, True),
        ("joint", True, True),
    ]
    results = []
    metric_rows = []
    cpu_arrival = selected["avg_cpu"].to_numpy(dtype=float)
    for name, shift, storage in cases:
        result, metrics = build_and_solve(
            cpu_arrival=cpu_arrival,
            params=params,
            enable_shift=shift,
            enable_storage=storage,
            case_name=name,
            output_dir=output_dir,
            show_log=args.show_scip_log,
        )
        results.append(result)
        metric_rows.append(metrics)

    all_results = pd.concat(results, ignore_index=True)
    metrics = pd.DataFrame(metric_rows)
    baseline_tv = float( #总波动量
        metrics.loc[
            metrics["case"] == "baseline", "total_variation_mw"
        ].iloc[0]
    )
    baseline_peak = float( #峰值并网功率
        metrics.loc[
            metrics["case"] == "baseline", "peak_grid_power_mw"
        ].iloc[0]
    )
    metrics["variation_reduction_pct"] = ( #波动量减少百分比
        baseline_tv - metrics["total_variation_mw"]
    ) / baseline_tv
    metrics["peak_reduction_pct"] = ( #峰值减少百分比
        baseline_peak - metrics["peak_grid_power_mw"]
    ) / baseline_peak

    all_results.to_csv(output_dir / "hourly_case_results.csv", index=False)
    metrics.to_csv(output_dir / "case_metrics.csv", index=False)
    make_plots(all_results, metrics, output_dir)

    metadata = {
        "input_file": str(csv_path),
        "raw_rows": int(len(raw)),
        "days": int(max_day),
        "representative_day": representative_day,
        "stress_day": stress_day,
        "selected_day": selected_day,
        "parameters": asdict(params),
        "software": {
            "python": sys.version.split()[0],
            "pyscipopt": __import__("pyscipopt").__version__,
            "scip": ".".join(
                map(
                    str,
                    [
                        Model().getMajorVersion(),
                        Model().getMinorVersion(),
                        Model().getTechVersion(),
                    ],
                )
            ),
        },
    }
    with (output_dir / "run_metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    shutil.copy2(csv_path, output_dir / csv_path.name)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    print("\n指标：")
    print(
        metrics[
            [
                "case",
                "status",
                "total_variation_mw",
                "variation_reduction_pct",
                "max_ramp_mw",
                "peak_grid_power_mw",
                "std_grid_power_mw",
                "solve_time_s",
                "mip_gap",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
