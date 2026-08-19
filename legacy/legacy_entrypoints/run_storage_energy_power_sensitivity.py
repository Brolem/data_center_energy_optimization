from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from dc_energy_opt.config import HOUSTON_2020
from dc_energy_opt.experiments.storage_energy_power_sensitivity import (
    StorageScaleSensitivityResult,
    run_storage_energy_power_sensitivity_experiment,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fixed 3-hour delay: independently vary battery energy and power."
        ),
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
        default=HOUSTON_2020.storage_energy_power_sensitivity_output_dir,
    )
    parser.add_argument("--show-solver-log", action="store_true")
    return parser.parse_args(argv)


def format_storage_energy_power_sensitivity_summary(
    metrics: pd.DataFrame,
) -> str:
    required_columns = (
        "battery_energy_mwh",
        "battery_power_mw",
        "joint_cost_cny",
        "storage_effect_on_shift_cny",
    )
    missing_columns = [
        column for column in required_columns if column not in metrics
    ]
    if missing_columns:
        raise ValueError(
            "storage energy-power sensitivity metrics missing columns: "
            f"{', '.join(missing_columns)}"
        )
    best_joint = metrics.loc[metrics["joint_cost_cny"].idxmin()]
    effect = metrics["storage_effect_on_shift_cny"]
    return "\n".join(
        (
            "Storage energy-power sensitivity summary:",
            "Best joint cost: "
            f"{float(best_joint.joint_cost_cny):.4f} CNY "
            f"at {float(best_joint.battery_energy_mwh):g} MWh / "
            f"{float(best_joint.battery_power_mw):g} MW.",
            "Shift-value effect range: "
            f"{float(effect.min()):.4f} to {float(effect.max()):.4f} CNY.",
        )
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result: StorageScaleSensitivityResult = (
        run_storage_energy_power_sensitivity_experiment(
            workload_data=args.workload_data,
            energy_data=args.energy_data,
            output_dir=args.output_dir,
            show_solver_log=args.show_solver_log,
        )
    )
    print(format_storage_energy_power_sensitivity_summary(result.metrics))


if __name__ == "__main__":
    main()
