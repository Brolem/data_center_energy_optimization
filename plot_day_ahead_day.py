from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from dc_energy_opt.reporting import (
    TASK_DELAY_PLOT_FILENAME,
    make_daily_plots,
    make_task_delay_objective_plot,
)


FORMAL_CASES = (
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
)


def format_daily_objective_summary(
    hourly_results: pd.DataFrame,
    day_number: int,
) -> str:
    selected = hourly_results.loc[hourly_results["day"] == day_number]
    baseline = selected.loc[selected["case"] == "renewables_only"]
    if baseline.empty:
        raise ValueError(
            f"hourly_dispatch.csv 第 {day_number} 天缺少 renewables_only"
        )

    grid_only_cost = float(
        (
            baseline["dc_power_mw"]
            * baseline["electricity_price_cny_per_kwh"]
            * 1000.0
        ).sum()
    )
    required_grid_peak = float(baseline["dc_power_mw"].max())
    renewables_only_cost = float(
        baseline["hourly_operating_cost_cny"].sum()
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
        "Formal case operating costs:",
        (
            f"{'case':<24} {'analysis':>14} {'tail':>14} "
            f"{'total':>14} {'saving':>12}"
        ),
    ]
    for case_name in FORMAL_CASES:
        case_rows = selected.loc[selected["case"] == case_name]
        if case_rows.empty:
            raise ValueError(
                f"hourly_dispatch.csv 第 {day_number} 天缺少 {case_name}"
            )
        analysis_cost = float(
            case_rows.loc[
                case_rows["period_role"] == "analysis",
                "hourly_operating_cost_cny",
            ].sum()
        )
        tail_cost = float(
            case_rows.loc[
                case_rows["period_role"] == "settlement_tail",
                "hourly_operating_cost_cny",
            ].sum()
        )
        total_cost = analysis_cost + tail_cost
        saving_pct = (
            (renewables_only_cost - total_cost)
            / renewables_only_cost
            * 100.0
            if renewables_only_cost > 0.0
            else 0.0
        )
        lines.append(
            f"{case_name:<24} {analysis_cost:>14.4f} "
            f"{tail_cost:>14.4f} {total_cost:>14.4f} "
            f"{saving_pct:>11.4f}%"
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从现有小时调度结果生成指定日期的五张图。",
    )
    parser.add_argument(
        "--hourly-dispatch",
        type=Path,
        default="outputs/houston_2020_main/results/hourly_dispatch.csv",
    )
    parser.add_argument(
        "--day",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--daily-metrics",
        type=Path,
        default="outputs/houston_2020_main/results/daily_metrics.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default="outputs/houston_2020_main/figures",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.hourly_dispatch.is_file():
        raise FileNotFoundError(
            f"hourly_dispatch.csv 不存在: {args.hourly_dispatch}"
        )
    if not args.daily_metrics.is_file():
        raise FileNotFoundError(
            f"daily_metrics.csv 不存在: {args.daily_metrics}"
        )
    hourly_results = pd.read_csv(args.hourly_dispatch)
    daily_metrics = pd.read_csv(args.daily_metrics)
    print(format_daily_objective_summary(hourly_results, args.day))
    daily_output_dir = make_daily_plots(
        hourly_results,
        args.day,
        args.output_dir,
    )
    make_task_delay_objective_plot(
        daily_metrics,
        daily_output_dir / TASK_DELAY_PLOT_FILENAME,
        day_number=args.day,
    )


if __name__ == "__main__":
    main()
