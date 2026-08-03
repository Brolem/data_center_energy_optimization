from __future__ import annotations

import argparse
from pathlib import Path

from dc_energy_opt.experiments import (
    ExperimentResult,
    run_houston_2020_experiment,
)


FORMAL_CASES = (
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
)


def format_experiment_objective_summary(result: ExperimentResult) -> str:
    baseline_dispatch = result.hourly_dispatch.loc[
        result.hourly_dispatch["case"] == "renewables_only"
    ]
    if baseline_dispatch.empty:
        raise ValueError("hourly_dispatch 缺少 renewables_only")

    grid_only_cost = float(
        (
            baseline_dispatch["dc_power_mw"]
            * baseline_dispatch["electricity_price_cny_per_kwh"]
            * 1000.0
        ).sum()
    )
    required_grid_peak = float(baseline_dispatch["dc_power_mw"].max())
    ordered_metrics = (
        result.case_metrics.set_index("case").loc[list(FORMAL_CASES)].reset_index()
    )
    renewables_only_cost = float(
        ordered_metrics.loc[
            ordered_metrics["case"] == "renewables_only",
            "operating_cost_cny",
        ].iloc[0]
    )
    renewable_contribution = grid_only_cost - renewables_only_cost
    renewable_contribution_pct = (
        renewable_contribution / grid_only_cost * 100.0
        if grid_only_cost > 0.0
        else 0.0
    )

    lines = [
        f"Grid-only accounting baseline: {grid_only_cost:.4f} CNY",
        f"Required grid peak: {required_grid_peak:.4f} MW",
        f"Renewables-only cost: {renewables_only_cost:.4f} CNY",
        (
            "Wind + solar contribution: "
            f"{renewable_contribution:.4f} CNY "
            f"({renewable_contribution_pct:.4f}%)"
        ),
        "",
        "Formal optimization objectives:",
        (
            f"{'case':<24} {'status':<10} {'operating_cost':>16} "
            f"{'saving':>12} {'total_delay':>14} {'max_delay':>10}"
        ),
    ]
    for row in ordered_metrics.itertuples(index=False):
        lines.append(
            f"{row.case:<24} {row.status:<10} "
            f"{float(row.operating_cost_cny):>16.4f} "
            f"{float(row.operating_cost_savings_vs_renewables_only_pct):>11.4f}% "
            f"{float(row.total_task_delay_cpu_hours):>14.4f} "
            f"{int(row.maximum_task_delay_h):>10d}"
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="数据中心跨日确定性日前运行成本优化",
    )
    parser.add_argument(
        "--workload-data",
        type=Path,
        default=Path("data/workload/google_2019_28d_5min.csv"),
    )
    parser.add_argument(
        "--energy-data",
        type=Path,
        default=Path("data/energy/houston_2020_may_hourly.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/houston_2020_main"),
    )
    parser.add_argument("--show-solver-log", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = run_houston_2020_experiment(
        workload_data=args.workload_data,
        energy_data=args.energy_data,
        output_dir=args.output_dir,
        show_solver_log=args.show_solver_log,
    )
    print(format_experiment_objective_summary(result))


if __name__ == "__main__":
    main()
