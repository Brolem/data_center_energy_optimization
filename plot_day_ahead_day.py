from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from dc_energy_opt.reporting import make_daily_plots


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从现有小时调度结果生成指定日期的五张图。",
    )
    parser.add_argument(
        "--hourly-dispatch",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--day",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.hourly_dispatch.is_file():
        raise FileNotFoundError(
            f"hourly_dispatch.csv 不存在: {args.hourly_dispatch}"
        )
    hourly_results = pd.read_csv(args.hourly_dispatch)
    daily_output_dir = make_daily_plots(
        hourly_results,
        args.day,
        args.output_dir,
    )
    print(f"Daily plots written to: {daily_output_dir}")


if __name__ == "__main__":
    main()
