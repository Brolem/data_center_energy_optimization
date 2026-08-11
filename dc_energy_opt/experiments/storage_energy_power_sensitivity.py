from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

from ..config import Parameters
from ..reporting import (
    make_storage_energy_power_sensitivity_plots,
    software_versions,
)
from .artifacts import build_run_provenance, staged_run_directory
from .houston_2020 import run_houston_2020_experiment
from .storage_scale_sensitivity import (
    StorageScale,
    StorageScaleSensitivityResult,
    build_storage_scale_summary,
    validate_storage_scales,
)


DEFAULT_STORAGE_ENERGY_POWER_SCALES = tuple(
    StorageScale(
        f"energy_{energy_mwh:.1f}".replace(".", "p")
        + f"_mwh_power_{power_mw:.1f}".replace(".", "p")
        + "_mw",
        energy_mwh,
        power_mw,
    )
    for energy_mwh in (2.0, 4.0, 6.0)
    for power_mw in (0.5, 1.0, 1.5)
)


def _resolve_and_validate_input_paths(
    workload_data: Path,
    energy_data: Path,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    workload_path = Path(workload_data)
    energy_path = Path(energy_data)
    output_path = Path(output_dir)
    resolved_output_path = output_path.resolve(strict=False)
    for input_identifier, input_path in (
        ("workload_data", workload_path.resolve(strict=False)),
        ("energy_data", energy_path.resolve(strict=False)),
    ):
        if input_path == resolved_output_path or input_path.is_relative_to(
            resolved_output_path
        ):
            raise ValueError(
                f"{input_identifier} must not equal output_dir or be inside it"
            )
    return workload_path, energy_path, output_path


def _write_analysis_report(
    *,
    output_path: Path,
    metrics: pd.DataFrame,
) -> None:
    lines = [
        "# 固定 3 小时时移下的储能容量×功率敏感性分析",
        "",
        "- 容量扫描：2、4、6 MWh。",
        "- 功率扫描：0.5、1.0、1.5 MW；充放电功率相同。",
        "- 全部格点固定 `max_delay_h=3` 与 `flex_ratio=0.30`。",
        "- 每个格点独立求解四个正式算例并保留完整项目。",
        "",
        "| 能量 (MWh) | 功率 (MW) | 联合成本 (CNY) | 储能对时移价值的影响 (CNY) |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for row in metrics.sort_values(
        ["battery_energy_mwh", "battery_power_mw"]
    ).itertuples(index=False):
        lines.append(
            f"| {float(row.battery_energy_mwh):.1f} | "
            f"{float(row.battery_power_mw):.1f} | "
            f"{float(row.joint_cost_cny):,.4f} | "
            f"{float(row.storage_effect_on_shift_cny):,.4f} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_storage_energy_power_sensitivity_experiment(
    *,
    workload_data: Path,
    energy_data: Path,
    output_dir: Path,
    params: Parameters | None = None,
    storage_scales: tuple[StorageScale, ...] = (
        DEFAULT_STORAGE_ENERGY_POWER_SCALES
    ),
    show_solver_log: bool = False,
) -> StorageScaleSensitivityResult:
    scales = validate_storage_scales(storage_scales)
    workload_path, energy_path, output_path = _resolve_and_validate_input_paths(
        workload_data,
        energy_data,
        output_dir,
    )
    base_params = Parameters() if params is None else params
    if base_params.max_delay_h != 3:
        raise ValueError(
            "storage-energy-power sensitivity requires params.max_delay_h == 3"
        )

    with staged_run_directory(output_path) as paths:
        case_metrics_by_scale: dict[str, pd.DataFrame] = {}
        for scale in scales:
            scale_params = replace(
                base_params,
                battery_energy_mwh=scale.battery_energy_mwh,
                battery_charge_power_mw=scale.battery_power_mw,
                battery_discharge_power_mw=scale.battery_power_mw,
            )
            scale_result = run_houston_2020_experiment(
                workload_data=workload_path,
                energy_data=energy_path,
                output_dir=paths.root / "experiments" / scale.name,
                params=scale_params,
                show_solver_log=show_solver_log,
            )
            case_metrics_by_scale[scale.name] = scale_result.case_metrics

        metrics = build_storage_scale_summary(
            case_metrics_by_scale=case_metrics_by_scale,
            storage_scales=scales,
        )
        metrics.to_csv(
            paths.results / "storage_energy_power_sensitivity.csv",
            index=False,
        )
        make_storage_energy_power_sensitivity_plots(metrics, paths.figures)
        _write_analysis_report(
            output_path=paths.root / "analysis.md",
            metrics=metrics,
        )

        parameter_values = asdict(base_params)
        parameter_values.update(
            {
                "server_idle_power_kw": base_params.server_idle_power_kw,
                "solar_capacity_mw": base_params.solar_capacity_mw,
                "solar_inverter_capacity_mw": (
                    base_params.solar_inverter_capacity_mw
                ),
                "wind_capacity_mw": base_params.wind_capacity_mw,
            }
        )
        metadata: dict[str, object] = {
            "model_type": "rolling_24_plus_3_deterministic_day_ahead",
            "scenario_status": "houston_2020_storage_energy_power_sensitivity",
            "input_file": str(workload_path),
            "energy_scenario_file": str(energy_path),
            "fixed_max_delay_h": 3,
            "storage_scales": [
                {
                    "name": scale.name,
                    "battery_energy_mwh": scale.battery_energy_mwh,
                    "battery_power_mw": scale.battery_power_mw,
                }
                for scale in scales
            ],
            "individual_project_root": "experiments",
            "operating_cost_accounting": (
                "operating_cost_cny equals the 672-hour analysis cost plus "
                "the 3-hour settlement-tail cost; warmup cost is excluded"
            ),
            "parameters": parameter_values,
            "software_versions": software_versions(),
        }
        metadata.update(
            build_run_provenance(
                input_files={
                    "workload": workload_path,
                    "energy": energy_path,
                }
            )
        )
        with (paths.root / "run_metadata.json").open(
            "w", encoding="utf-8"
        ) as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)

    return StorageScaleSensitivityResult(metrics=metrics, metadata=metadata)
