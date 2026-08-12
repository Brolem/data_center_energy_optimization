from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from dc_energy_opt.config import HOUSTON_2020
from dc_energy_opt.experiments.storage_scale_sensitivity import (
    StorageScaleSensitivityResult,
    run_storage_scale_sensitivity_experiment,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="固定三小时时移，比较不同储能功率和容量。",
    )
    parser.add_argument(
        "--workload-data",
        type=Path,
        default=HOUSTON_2020.workload_data,
    )
    parser.add_argument(
        "--energy-data",
        type=Path,
        default=HOUSTON_2020.energy_data,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=HOUSTON_2020.storage_scale_sensitivity_output_dir,
    )
    parser.add_argument("--show-solver-log", action="store_true")
    return parser.parse_args(argv)


def format_storage_scale_sensitivity_summary(
    metrics: pd.DataFrame,
) -> str:
    required_columns = (
        "storage_scale",
        "storage_base_savings_cny",
        "storage_shift_savings_cny",
        "storage_effect_on_shift_cny",
    )
    missing_columns = [
        column for column in required_columns if column not in metrics
    ]
    if missing_columns:
        raise ValueError(
            "storage-scale sensitivity metrics missing columns: "
            f"{', '.join(missing_columns)}"
        )
    lines = ["Storage-scale sensitivity summary:"]
    for row in metrics.itertuples(index=False):
        lines.append(
            f"{row.storage_scale}: "
            f"storage base saving={float(row.storage_base_savings_cny):.4f} CNY; "
            f"shift saving with storage={float(row.storage_shift_savings_cny):.4f} CNY; "
            f"storage effect on shift={float(row.storage_effect_on_shift_cny):.4f} CNY"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result: StorageScaleSensitivityResult = (
        run_storage_scale_sensitivity_experiment(
            workload_data=args.workload_data,
            energy_data=args.energy_data,
            output_dir=args.output_dir,
            show_solver_log=args.show_solver_log,
        )
    )
    print(format_storage_scale_sensitivity_summary(result.metrics))


if __name__ == "__main__":
    main()
