from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .ercot_2025_spot_gpu.config import CareerPaths
from .ercot_2025_spot_gpu.run import run_career_day_ahead


def _build_parser() -> argparse.ArgumentParser:
    paths = CareerPaths()
    parser = argparse.ArgumentParser(prog="python -m experiments.career")
    commands = parser.add_subparsers(dest="command", required=True)
    day_ahead = commands.add_parser("ercot-2025-spot-gpu-day-ahead")
    day_ahead.add_argument("--energy-path", type=Path, default=paths.energy_table)
    day_ahead.add_argument("--spot-job-path", type=Path, default=paths.spot_job_table)
    day_ahead.add_argument("--output-dir", type=Path, default=paths.output_directory)
    day_ahead.add_argument("--show-solver-log", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.command != "ercot-2025-spot-gpu-day-ahead":
        raise RuntimeError("无法识别求职线命令。")
    result = run_career_day_ahead(
        energy_path=arguments.energy_path,
        spot_job_path=arguments.spot_job_path,
        output_directory=arguments.output_dir,
        show_solver_log=arguments.show_solver_log,
    )
    print(f"已发布求职线结果包: {result.output_directory}")
    print(
        "feature_model_deployable="
        f"{result.forecast_evaluation.feature_model_deployable}"
    )
    return 0
