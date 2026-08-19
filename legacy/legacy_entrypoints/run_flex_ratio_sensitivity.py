from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from dc_energy_opt.config import HOUSTON_2020
from dc_energy_opt.experiments.flex_ratio_sensitivity import (
    DEFAULT_FLEX_RATIOS,
    FlexRatioSensitivityResult,
    run_flex_ratio_sensitivity_experiment,
    validate_flex_ratios,
)


def _parse_flex_ratios(value: str) -> tuple[float, ...]:
    try:
        ratios = tuple(float(part.strip()) for part in value.split(","))
        return validate_flex_ratios(ratios)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="固定模型条件下扫描时移比例并分析运行成本。",
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
        "--flex-ratios",
        type=_parse_flex_ratios,
        default=DEFAULT_FLEX_RATIOS,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=HOUSTON_2020.flex_ratio_sensitivity_output_dir,
    )
    parser.add_argument("--show-solver-log", action="store_true")
    return parser.parse_args(argv)


def format_sensitivity_summary(metrics: pd.DataFrame) -> str:
    lines = ["Flex-ratio sensitivity summary:"]
    for scenario in ("renewables_shift", "joint"):
        rows = metrics.loc[metrics["scenario"] == scenario].sort_values(
            "flex_ratio"
        )
        if rows.empty:
            raise ValueError(f"敏感性结果缺少场景 {scenario}。")
        baseline = rows.iloc[0]
        minimum = rows.loc[
            rows["operating_cost_cny"].idxmin()
        ]
        onset = rows["saturation_onset"].dropna()
        onset_text = (
            f"{float(onset.iloc[0]):.2f}"
            if not onset.empty
            else "not detected"
        )
        lines.append(
            f"{scenario}: baseline={float(baseline['operating_cost_cny']):.4f} CNY; "
            f"minimum at flex_ratio={float(minimum['flex_ratio']):.2f}, "
            f"cost={float(minimum['operating_cost_cny']):.4f} CNY, "
            f"saving={float(minimum['cost_savings_pct']):.4f}%; "
            f"saturation={onset_text}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result: FlexRatioSensitivityResult = (
        run_flex_ratio_sensitivity_experiment(
            workload_data=args.workload_data,
            energy_data=args.energy_data,
            output_dir=args.output_dir,
            flex_ratios=args.flex_ratios,
            show_solver_log=args.show_solver_log,
        )
    )
    print(format_sensitivity_summary(result.metrics))


if __name__ == "__main__":
    main()
