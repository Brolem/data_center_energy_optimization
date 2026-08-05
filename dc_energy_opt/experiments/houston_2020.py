from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from ..config import Parameters
from ..data import load_and_prepare, load_houston_energy_scenario
from ..optimization import ROLLING_CASES, run_rolling_day_ahead
from ..reporting import (
    TASK_DELAY_PLOT_FILENAME,
    make_plots,
    make_task_delay_objective_plot,
    software_versions,
)
from .artifacts import staged_run_directory


@dataclass(frozen=True)
class ExperimentResult:
    hourly_dispatch: pd.DataFrame
    daily_metrics: pd.DataFrame
    case_metrics: pd.DataFrame
    metadata: dict[str, object]


def run_houston_2020_experiment(
    *,
    workload_data: Path,
    energy_data: Path,
    output_dir: Path,
    params: Parameters | None = None,
    show_solver_log: bool = False,
) -> ExperimentResult:
    workload_path = Path(workload_data)
    energy_path = Path(energy_data)
    output_path = Path(output_dir)
    resolved_workload_data = workload_path.resolve(strict=False)
    resolved_energy_data = energy_path.resolve(strict=False)
    resolved_output_dir = output_path.resolve(strict=False)
    for input_identifier, input_path in (
        ("workload_data", resolved_workload_data),
        ("energy_data", resolved_energy_data),
    ):
        if input_path == resolved_output_dir or input_path.is_relative_to(
            resolved_output_dir
        ):
            raise ValueError(
                f"{input_identifier} 输入路径 {input_path} 与 "
                f"output_dir {resolved_output_dir} 冲突："
                "输入不得等于输出目录，"
                "也不得位于其目录树内。"
            )
    experiment_params = Parameters() if params is None else params

    with staged_run_directory(output_path) as paths:
        workload_snapshot = (
            paths.inputs / "google_2019_28d_5min.csv"
        )
        energy_snapshot = (
            paths.inputs / "houston_2020_may_hourly.csv"
        )
        shutil.copyfile(
            workload_path,
            workload_snapshot,
        )
        shutil.copyfile(
            energy_path,
            energy_snapshot,
        )

        raw, hourly, representative_day, stress_day = load_and_prepare(
            workload_snapshot
        )
        energy_scenario = load_houston_energy_scenario(
            energy_snapshot,
            experiment_params,
        )
        max_day = int(hourly["day"].max())
        ordered_hourly = hourly.sort_values(
            ["day", "hour"]
        ).reset_index(drop=True)
        if max_day != 28 or len(ordered_hourly) != 672:
            raise ValueError(
                "主实验算力数据必须严格包含 28 个完整日、672 个小时。"
            )

        analysis_energy = energy_scenario.iloc[24:696].reset_index(
            drop=True
        )
        model_input = ordered_hourly.rename(
            columns={"avg_cpu": "cpu_arrival_pu"}
        ).copy()
        for column in energy_scenario.columns:
            model_input[column] = analysis_energy[column].to_numpy()
        cpu_arrival = model_input["cpu_arrival_pu"].to_numpy(dtype=float)

        model_input.to_csv(
            paths.inputs / "aligned_28d_hourly.csv",
            index=False,
        )
        hourly.to_csv(
            paths.results / "hourly_workload.csv",
            index=False,
        )

        results = []
        metric_rows = []
        daily_results = []
        for (
            case_name,
            enable_shift,
            enable_storage,
        ) in ROLLING_CASES:
            result, case_metric, daily_metric = run_rolling_day_ahead(
                cpu_arrival=cpu_arrival,
                energy_scenario=energy_scenario,
                params=experiment_params,
                case_name=case_name,
                enable_shift=enable_shift,
                enable_storage=enable_storage,
                model_output_dir=paths.models / case_name,
                show_log=show_solver_log,
            )
            results.append(result)
            metric_rows.append(case_metric)
            daily_results.append(daily_metric)

        all_results = pd.concat(results, ignore_index=True)
        case_metrics = pd.DataFrame(metric_rows)
        daily_metrics = pd.concat(daily_results, ignore_index=True)
        renewables_only_cost = float(
            case_metrics.loc[
                case_metrics["case"] == "renewables_only",
                "operating_cost_cny",
            ].iloc[0]
        )
        case_metrics[
            "operating_cost_savings_vs_renewables_only_pct"
        ] = (
            100.0
            * (
                renewables_only_cost
                - case_metrics["operating_cost_cny"]
            )
            / renewables_only_cost
            if renewables_only_cost > 0.0
            else 0.0
        )

        all_results.to_csv(
            paths.results / "hourly_dispatch.csv",
            index=False,
        )
        daily_metrics.to_csv(
            paths.results / "daily_metrics.csv",
            index=False,
        )
        case_metrics.to_csv(
            paths.results / "case_metrics.csv",
            index=False,
        )
        make_plots(all_results, case_metrics, paths.figures)
        make_task_delay_objective_plot(
            daily_metrics,
            paths.figures / TASK_DELAY_PLOT_FILENAME,
        )

        parameter_values = asdict(experiment_params)
        parameter_values.update(
            {
                "server_idle_power_kw": experiment_params.server_idle_power_kw,
                "solar_capacity_mw": experiment_params.solar_capacity_mw,
                "solar_inverter_capacity_mw": (
                    experiment_params.solar_inverter_capacity_mw
                ),
                "wind_capacity_mw": experiment_params.wind_capacity_mw,
            }
        )
        metadata: dict[str, object] = {
            "model_type": "rolling_24_plus_3_deterministic_day_ahead",
            "scenario_status": "houston_2020_main_experiment",
            "input_file": str(workload_path),
            "energy_scenario_file": str(energy_path),
            "renewable_data_source": {
                "file": str(energy_path),
                "location": "Houston, Texas, USA",
                "time_standard": "UTC-06 fixed local standard time",
                "period": "2020-04-30 00:00/2020-05-29 02:00",
                "source_repository": (
                    "https://github.com/dos-group/vessim-opt/tree/"
                    "724ee837f2867ef7b90658730de2d55823a3ae5c"
                ),
                "solar_method": "NSRDB five-minute data with PVWatts v8",
                "wind_method": (
                    "WIND Toolkit 80 m five-minute wind speed with "
                    "GE 1.5sle power curve scaled to 6.6 MW"
                ),
            },
            "electricity_price_source": {
                "file": str(energy_path),
                "currency": "CNY",
                "tariff_type": "time_of_use",
                "geographic_role": "exogenous paper tariff",
                "source_paper": (
                    "A novel demand response-based distributed multi-energy "
                    "system optimal operation framework for data centers"
                ),
            },
            "geographic_interpretation": (
                "风光出力来自 Houston；购电价沿用论文分段电价，"
                "作为外生价格信号，不主张二者具有地理一致性。"
            ),
            "rolling_schedule": {
                "warmup": "2020-04-30 00:00/2020-04-30 23:00",
                "analysis": "2020-05-01 00:00/2020-05-28 23:00",
                "settlement_tail": "2020-05-29 00:00/2020-05-29 02:00",
                "window_hours": 27,
                "committed_hours": 24,
                "maximum_task_delay_hours": experiment_params.max_delay_h,
                "soc_coordination": (
                    "one full-period deterministic coordination solve; "
                    "daily boundary targets enforced in rolling windows"
                ),
            },
            "formal_cases": [
                case_name for case_name, _, _ in ROLLING_CASES
            ],
            "cost_baseline_case": "renewables_only",
            "operating_cost_accounting": (
                "operating_cost_cny equals the 672-hour analysis cost plus "
                "the 3-hour settlement-tail cost; warmup cost is excluded"
            ),
            "battery_equivalent_full_cycle_definition": (
                "discharged_energy_mwh / battery_energy_mwh"
            ),
            "raw_rows": int(len(raw)),
            "energy_scenario_rows": int(len(energy_scenario)),
            "days": int(max_day),
            "representative_day": representative_day,
            "stress_day": stress_day,
            "parameters": parameter_values,
            "software_versions": software_versions(),
        }
        with (paths.root / "run_metadata.json").open(
            "w", encoding="utf-8"
        ) as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)

    return ExperimentResult(
        hourly_dispatch=all_results,
        daily_metrics=daily_metrics,
        case_metrics=case_metrics,
        metadata=metadata,
    )
