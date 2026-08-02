from __future__ import annotations

import argparse
import json
from pathlib import Path

from dc_energy_opt.config import Parameters
from dc_energy_opt.data import (
    load_and_prepare,
    load_houston_energy_scenario,
)
from dc_energy_opt.experiments import run_houston_2020_experiment
from dc_energy_opt.optimization import (
    build_and_solve,
    run_rolling_day_ahead,
)
from dc_energy_opt.reporting import make_plots

__all__ = [
    "Parameters",
    "load_and_prepare",
    "load_houston_energy_scenario",
    "build_and_solve",
    "run_rolling_day_ahead",
    "make_plots",
    "main",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="数据中心确定性日前运行成本优化",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/workload/google_2019_28d_5min.csv"),
        help="8064 行 Google 2019 instance usage 聚合 CSV",
    )
    parser.add_argument(
        "--energy-scenario",
        type=Path,
        default=Path("data/energy/houston_2020_may_hourly.csv"),
        help="699 小时 Houston 2020 风光与外生论文分段电价场景 CSV",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/houston_2020_main"),
        help="结果输出目录",
    )
    parser.add_argument(
        "--show-scip-log",
        action="store_true",
        help="显示 SCIP 求解日志",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    experiment = run_houston_2020_experiment(
        workload_data=args.input,
        energy_data=args.energy_scenario,
        output_dir=args.output_dir,
        show_solver_log=args.show_scip_log,
    )

    print(json.dumps(experiment.metadata, ensure_ascii=True, indent=2))
    print("\nOperating cost metrics:")
    print(
        experiment.case_metrics[
            [
                "case",
                "status",
                "grid_purchase_cost_cny",
                "solar_om_cost_cny",
                "wind_om_cost_cny",
                "battery_om_cost_cny",
                "battery_degradation_cost_cny",
                "operating_cost_cny",
                "operating_cost_savings_vs_renewables_only_pct",
                "renewable_curtailment_energy_mwh",
                "renewable_curtailment_rate_pct",
                "battery_equivalent_full_cycles",
                "cross_day_task_cpu_pu_hours",
                "average_flexible_task_delay_h",
                "maximum_task_delay_h",
                "grid_binding_hours",
                "grid_minimum_margin_mw",
                "solve_time_s",
                "mip_gap",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
