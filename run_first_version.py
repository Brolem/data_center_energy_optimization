from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from scip_first_version.config import Parameters
from scip_first_version.data import load_and_prepare
from scip_first_version.model import build_and_solve
from scip_first_version.reporting import make_plots, software_versions

__all__ = [
    "Parameters",
    "build_and_solve",
    "load_and_prepare",
    "make_plots",
]


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


def main() -> None:
    args = parse_args()
    csv_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    params = Parameters()

    raw, hourly, representative_day, stress_day = load_and_prepare(csv_path)
    selected_day = args.day if args.day is not None else representative_day
    max_day = int(hourly["day"].max())
    if not 1 <= selected_day <= max_day:
        raise ValueError(f"--day 应在 1 到 {max_day} 之间。")

    selected = (
        hourly[hourly["day"] == selected_day]
        .sort_values("hour")
        .reset_index(drop=True)
    )
    if len(selected) != 24:
        raise ValueError("所选日不是完整的 24 个小时。")

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
    baseline_tv = float(
        metrics.loc[
            metrics["case"] == "baseline", "total_variation_mw"
        ].iloc[0]
    )
    baseline_peak = float(
        metrics.loc[
            metrics["case"] == "baseline", "peak_grid_power_mw"
        ].iloc[0]
    )
    metrics["variation_reduction_pct"] = (
        baseline_tv - metrics["total_variation_mw"]
    ) / baseline_tv
    metrics["peak_reduction_pct"] = (
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
        "software": software_versions(),
    }
    with (output_dir / "run_metadata.json").open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)

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
