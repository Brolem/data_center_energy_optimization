from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from dc_energy_opt.reporting import make_daily_case_cost_plots


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从现有结果生成四个正式算例的每日运行成本图。",
    )
    parser.add_argument(
        "--daily-metrics",
        type=Path,
        default=Path(
            "outputs/houston_2020_main/results/daily_metrics.csv"
        ),
    )
    parser.add_argument(
        "--hourly-dispatch",
        type=Path,
        default=Path(
            "outputs/houston_2020_main/results/hourly_dispatch.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/houston_2020_main/figures"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.daily_metrics.is_file():
        raise FileNotFoundError(
            f"daily_metrics.csv 不存在: {args.daily_metrics}"
        )
    if not args.hourly_dispatch.is_file():
        raise FileNotFoundError(
            f"hourly_dispatch.csv 不存在: {args.hourly_dispatch}"
        )
    daily_metrics = pd.read_csv(args.daily_metrics)
    hourly_dispatch = pd.read_csv(args.hourly_dispatch)
    make_daily_case_cost_plots(
        daily_metrics,
        hourly_dispatch,
        args.output_dir,
    )


if __name__ == "__main__":
    main()
