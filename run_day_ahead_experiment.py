from __future__ import annotations

import argparse
import json
from pathlib import Path

from dc_energy_opt.experiments import run_houston_2020_experiment


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
    print(json.dumps(result.metadata, ensure_ascii=True, indent=2))
    print("\nOperating cost metrics:")
    print(result.case_metrics.to_string(index=False))


if __name__ == "__main__":
    main()
