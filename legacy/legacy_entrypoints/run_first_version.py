from __future__ import annotations

import argparse
from pathlib import Path

from run_day_ahead_experiment import main as run_formal_experiment


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Houston 2020 日前主实验旧参数兼容入口",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/workload/google_2019_28d_5min.csv"),
    )
    parser.add_argument(
        "--energy-scenario",
        type=Path,
        default=Path("data/energy/houston_2020_may_hourly.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/houston_2020_main"),
    )
    parser.add_argument("--show-scip-log", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    formal_arguments = [
        f"--workload-data={args.input}",
        f"--energy-data={args.energy_scenario}",
        f"--output-dir={args.output_dir}",
    ]
    if args.show_scip_log:
        formal_arguments.append("--show-solver-log")

    print(
        "run_first_version.py is deprecated; use "
        "run_day_ahead_experiment.py."
    )
    run_formal_experiment(formal_arguments)


if __name__ == "__main__":
    main()
