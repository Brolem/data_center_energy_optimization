from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from dc_energy_opt.config import HOUSTON_2020
from experiments.paper.houston_2020 import run_houston_2020_experiment
from experiments.paper.houston_2020.plotting.daily_costs import (
    plot_daily_cost_results,
)
from experiments.paper.houston_2020.plotting.day_ahead import (
    plot_day_ahead_results,
)
from experiments.paper.houston_2020.sensitivity.flex_ratio import (
    DEFAULT_FLEX_RATIOS,
    run_flex_ratio_sensitivity_experiment,
    validate_flex_ratios,
)
from experiments.paper.houston_2020.sensitivity.storage_energy_power import (
    run_storage_energy_power_sensitivity_experiment,
)
from experiments.paper.houston_2020.sensitivity.storage_scale import (
    run_storage_scale_sensitivity_experiment,
)
from experiments.paper.houston_2020.summaries import (
    format_experiment_objective_summary,
    format_sensitivity_summary,
    format_storage_energy_power_sensitivity_summary,
    format_storage_scale_sensitivity_summary,
)


SPOT_GPU_INPUT_DIR = Path(
    "outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs"
)
SPOT_GPU_OUTPUT_DIR = Path("outputs/paper/ercot_2025_houston_spot_gpu/day_ahead")


@dataclass(frozen=True)
class PaperCommand:
    name: str
    study: str | None
    arguments: argparse.Namespace


def _parse_flex_ratios(value: str) -> tuple[float, ...]:
    try:
        ratios = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "flex ratios must be comma-separated numbers"
        ) from error

    try:
        return validate_flex_ratios(ratios)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _add_data_arguments(
    parser: argparse.ArgumentParser,
    *,
    output_dir: Path,
) -> None:
    parser.add_argument(
        "--workload-data", type=Path, default=HOUSTON_2020.workload_data
    )
    parser.add_argument(
        "--energy-data", type=Path, default=HOUSTON_2020.energy_data
    )
    parser.add_argument("--output-dir", type=Path, default=output_dir)
    parser.add_argument("--show-solver-log", action="store_true")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m experiments.paper")
    commands = parser.add_subparsers(dest="name", required=True)

    day_ahead = commands.add_parser("day-ahead")
    _add_data_arguments(day_ahead, output_dir=HOUSTON_2020.main_output_dir)

    sensitivity = commands.add_parser("sensitivity")
    sensitivity_commands = sensitivity.add_subparsers(dest="study", required=True)

    flex_ratio = sensitivity_commands.add_parser("flex-ratio")
    _add_data_arguments(
        flex_ratio,
        output_dir=HOUSTON_2020.flex_ratio_sensitivity_output_dir,
    )
    flex_ratio.add_argument(
        "--flex-ratios", type=_parse_flex_ratios, default=DEFAULT_FLEX_RATIOS
    )

    storage_scale = sensitivity_commands.add_parser("storage-scale")
    _add_data_arguments(
        storage_scale,
        output_dir=HOUSTON_2020.storage_scale_sensitivity_output_dir,
    )

    storage_energy_power = sensitivity_commands.add_parser(
        "storage-energy-power"
    )
    _add_data_arguments(
        storage_energy_power,
        output_dir=HOUSTON_2020.storage_energy_power_sensitivity_output_dir,
    )

    plot = commands.add_parser("plot")
    plot_commands = plot.add_subparsers(dest="plot_name", required=True)
    main_results_dir = HOUSTON_2020.main_output_dir / "results"
    main_figures_dir = HOUSTON_2020.main_output_dir / "figures"

    plot_day_ahead = plot_commands.add_parser("day-ahead")
    plot_day_ahead.add_argument(
        "--hourly-dispatch",
        type=Path,
        default=main_results_dir / "hourly_dispatch.csv",
    )
    plot_day_ahead.add_argument("--day", type=int, default=8)
    plot_day_ahead.add_argument(
        "--daily-metrics",
        type=Path,
        default=main_results_dir / "daily_metrics.csv",
    )
    plot_day_ahead.add_argument(
        "--output-dir", type=Path, default=main_figures_dir
    )

    plot_daily_costs = plot_commands.add_parser("daily-costs")
    plot_daily_costs.add_argument(
        "--daily-metrics",
        type=Path,
        default=main_results_dir / "daily_metrics.csv",
    )
    plot_daily_costs.add_argument(
        "--hourly-dispatch",
        type=Path,
        default=main_results_dir / "hourly_dispatch.csv",
    )
    plot_daily_costs.add_argument(
        "--output-dir", type=Path, default=main_figures_dir
    )

    spot_gpu = commands.add_parser("spot-gpu")
    spot_gpu_commands = spot_gpu.add_subparsers(dest="study", required=True)
    for action in ("replay", "pilot", "report"):
        action_parser = spot_gpu_commands.add_parser(action)
        action_parser.add_argument(
            "--input-dir", type=Path, default=SPOT_GPU_INPUT_DIR
        )
        action_parser.add_argument(
            "--output-dir", type=Path, default=SPOT_GPU_OUTPUT_DIR
        )
    return parser


def parse_command(argv: list[str] | None = None) -> PaperCommand:
    arguments = _build_parser().parse_args(argv)
    return PaperCommand(
        name=arguments.name,
        study=getattr(arguments, "study", None),
        arguments=arguments,
    )


def main(argv: list[str] | None = None) -> None:
    command = parse_command(argv)
    args = command.arguments

    if command.name == "day-ahead":
        result = run_houston_2020_experiment(
            workload_data=args.workload_data,
            energy_data=args.energy_data,
            output_dir=args.output_dir,
            show_solver_log=args.show_solver_log,
        )
        print(format_experiment_objective_summary(result))
        return

    if command.name == "sensitivity":
        common_arguments = {
            "workload_data": args.workload_data,
            "energy_data": args.energy_data,
            "output_dir": args.output_dir,
            "show_solver_log": args.show_solver_log,
        }
        if command.study == "flex-ratio":
            result = run_flex_ratio_sensitivity_experiment(
                flex_ratios=args.flex_ratios,
                **common_arguments,
            )
            print(format_sensitivity_summary(result.metrics))
            return
        if command.study == "storage-scale":
            result = run_storage_scale_sensitivity_experiment(
                **common_arguments
            )
            print(format_storage_scale_sensitivity_summary(result.metrics))
            return
        if command.study == "storage-energy-power":
            result = run_storage_energy_power_sensitivity_experiment(
                **common_arguments
            )
            print(
                format_storage_energy_power_sensitivity_summary(result.metrics)
            )
            return

    if command.name == "plot" and args.plot_name == "day-ahead":
        plot_day_ahead_results(
            hourly_dispatch=args.hourly_dispatch,
            daily_metrics=args.daily_metrics,
            day_number=args.day,
            output_dir=args.output_dir,
        )
        return

    if command.name == "plot" and args.plot_name == "daily-costs":
        plot_daily_cost_results(
            daily_metrics=args.daily_metrics,
            hourly_dispatch=args.hourly_dispatch,
            output_dir=args.output_dir,
        )
        return

    if command.name == "spot-gpu":
        raise RuntimeError(
            "spot-gpu execution is introduced after the Stage 1 input contract"
        )

    raise RuntimeError("unreachable paper command")
