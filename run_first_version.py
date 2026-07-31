from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from scip_first_version.config import Parameters
from scip_first_version.data import load_and_prepare, load_energy_scenario
from scip_first_version.model import build_and_solve
from scip_first_version.reporting import make_plots, software_versions

__all__ = [
    "Parameters",
    "load_and_prepare",
    "load_energy_scenario",
    "build_and_solve",
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
        default=Path("data/instance_usage_grouped_300_seconds_month.csv"),
        help="8064 行 Google 2019 instance usage 聚合 CSV",
    )
    parser.add_argument(
        "--weather-source",
        type=Path,
        default=Path(
            "data/phoenix_nasa_power_20190501_20190528_hourly.csv"
        ),
        help="672 小时 Phoenix NASA POWER 气象源 CSV",
    )
    parser.add_argument(
        "--energy-scenario",
        type=Path,
        default=Path(
            "data/provisional_phoenix_weather_qinghai_tou_scenario.csv"
        ),
        help="24 小时临时风光与青海分时电价场景 CSV",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/day_ahead_deterministic"),
        help="结果输出目录",
    )
    parser.add_argument(
        "--day",
        type=int,
        default=None,
        help="指定第 1~28 天；省略则选择代表日",
    )
    parser.add_argument(
        "--show-scip-log",
        action="store_true",
        help="显示 SCIP 求解日志",
    )
    return parser.parse_args()


def _normalized_path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _archive_source_files(
    source_paths: list[Path],
    output_dir: Path,
) -> None:
    source_by_target_key: dict[str, Path] = {}
    for source_path in source_paths:
        resolved_source = source_path.resolve(strict=False)
        target_path = output_dir / source_path.name
        target_key = _normalized_path_key(target_path)
        previous_source = source_by_target_key.get(target_key)
        if (
            previous_source is not None
            and _normalized_path_key(previous_source)
            != _normalized_path_key(resolved_source)
        ):
            raise ValueError(
                f"源文件名冲突 {source_path.name}: "
                f"{previous_source} 与 {resolved_source}"
            )
        source_by_target_key[target_key] = resolved_source

    for source_path in source_paths:
        target_path = output_dir / source_path.name
        if _normalized_path_key(source_path) == _normalized_path_key(
            target_path
        ):
            continue
        shutil.copy2(source_path, target_path)


def main() -> None:
    args = parse_args()
    csv_path = args.input
    weather_source_path = args.weather_source
    energy_scenario_path = args.energy_scenario
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    _archive_source_files(
        [csv_path, weather_source_path, energy_scenario_path],
        output_dir,
    )
    params = Parameters()

    raw, hourly, representative_day, stress_day = load_and_prepare(csv_path)
    energy_scenario = load_energy_scenario(
        energy_scenario_path,
        params,
        weather_source_path=weather_source_path,
    )
    selected_day = args.day if args.day is not None else representative_day
    max_day = int(hourly["day"].max())
    if not 1 <= selected_day <= max_day:
        raise ValueError(f"--day 应在 1 到 {max_day} 之间。")

    selected = (
        hourly[hourly["day"] == selected_day]
        .sort_values("hour")
        .reset_index(drop=True)
    )
    if len(selected) != 24:
        raise ValueError("所选日不是完整的 24 个小时。")

    model_input = selected.rename(
        columns={"avg_cpu": "cpu_arrival_pu"}
    ).merge(
        energy_scenario,
        on="hour",
        how="inner",
        validate="one_to_one",
    )
    if len(model_input) != 24:
        raise ValueError("算力轨迹与能源场景未能按 24 个小时完整对齐。")
    model_input.to_csv(
        output_dir / "model_input_typical_day.csv",
        index=False,
    )
    hourly.to_csv(output_dir / "all_days_hourly.csv", index=False)

    cases = [
        ("grid_only", False, False, False),
        ("renewables_only", False, False, True),
        ("renewables_shift", True, False, True),
        ("renewables_storage", False, True, True),
        ("joint", True, True, True),
    ]
    cpu_arrival = model_input["cpu_arrival_pu"].to_numpy(dtype=float)
    solar_available_mw = model_input["solar_available_mw"].to_numpy(
        dtype=float
    )
    wind_available_mw = model_input["wind_available_mw"].to_numpy(
        dtype=float
    )
    electricity_price_cny_per_kwh = model_input[
        "electricity_price_cny_per_kwh"
    ].to_numpy(dtype=float)
    tou_by_hour = energy_scenario[["hour", "tou_period"]]

    results = []
    metric_rows = []
    for (
        case_name,
        enable_shift,
        enable_storage,
        enable_renewables,
    ) in cases:
        result, metrics = build_and_solve(
            cpu_arrival=cpu_arrival,
            solar_available_mw=solar_available_mw,
            wind_available_mw=wind_available_mw,
            electricity_price_cny_per_kwh=(
                electricity_price_cny_per_kwh
            ),
            params=params,
            enable_shift=enable_shift,
            enable_storage=enable_storage,
            enable_renewables=enable_renewables,
            case_name=case_name,
            output_dir=output_dir,
            show_log=args.show_scip_log,
        )
        result = result.merge(
            tou_by_hour,
            on="hour",
            how="left",
            validate="many_to_one",
        )
        if result["tou_period"].isna().any():
            raise ValueError(f"{case_name} 小时结果未能完整映射分时时段。")
        results.append(result)
        metric_rows.append(metrics)

    all_results = pd.concat(results, ignore_index=True)
    metrics = pd.DataFrame(metric_rows)
    grid_only_cost = float(
        metrics.loc[
            metrics["case"] == "grid_only", "operating_cost_cny"
        ].iloc[0]
    )
    metrics["operating_cost_savings_vs_grid_only_pct"] = (
        100.0 * (grid_only_cost - metrics["operating_cost_cny"])
        / grid_only_cost
        if grid_only_cost > 0.0
        else 0.0
    )

    all_results.to_csv(output_dir / "hourly_case_results.csv", index=False)
    metrics.to_csv(output_dir / "case_metrics.csv", index=False)
    make_plots(all_results, metrics, output_dir)

    parameter_values = asdict(params)
    parameter_values.update(
        {
            "server_idle_power_kw": params.server_idle_power_kw,
            "solar_capacity_mw": params.solar_capacity_mw,
            "wind_capacity_mw": params.wind_capacity_mw,
        }
    )
    metadata = {
        "model_type": "deterministic_day_ahead",
        "scenario_status": (
            "provisional_mixed_region_development_scenario"
        ),
        "input_file": str(csv_path),
        "energy_scenario_file": str(energy_scenario_path),
        "weather_source": {
            "file": str(weather_source_path),
            "location": "Phoenix, Arizona, USA",
            "latitude": 33.4484,
            "longitude": -112.0740,
            "time_standard": "LST",
            "period": "2019-05-01/2019-05-28",
        },
        "electricity_price_source": {
            "file": str(energy_scenario_path),
            "region": "Qinghai, China",
            "currency": "CNY",
            "tariff_type": "time_of_use",
            "source_paper": (
                "A novel demand response-based distributed multi-energy "
                "system optimal operation framework for data centers"
            ),
        },
        "geographic_interpretation": (
            "当前 24 小时场景混合使用菲尼克斯气象和青海电价，"
            "只用于模型开发和模块验证。"
        ),
        "raw_rows": int(len(raw)),
        "energy_scenario_rows": int(len(energy_scenario)),
        "days": int(max_day),
        "representative_day": representative_day,
        "stress_day": stress_day,
        "selected_day": selected_day,
        "parameters": parameter_values,
        "software_versions": software_versions(),
    }
    with (output_dir / "run_metadata.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)

    print(json.dumps(metadata, ensure_ascii=True, indent=2))
    print("\nOperating cost metrics:")
    print(
        metrics[
            [
                "case",
                "status",
                "grid_purchase_cost_cny",
                "solar_om_cost_cny",
                "wind_om_cost_cny",
                "battery_om_cost_cny",
                "operating_cost_cny",
                "operating_cost_savings_vs_grid_only_pct",
                "renewable_curtailment_energy_mwh",
                "renewable_curtailment_rate_pct",
                "solve_time_s",
                "mip_gap",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
