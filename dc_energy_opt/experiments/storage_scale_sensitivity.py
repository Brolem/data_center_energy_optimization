from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import pandas as pd

from ..config import Parameters
from ..reporting import make_storage_scale_sensitivity_plots, software_versions
from .artifacts import build_run_provenance, staged_run_directory
from .houston_2020 import run_houston_2020_experiment


FORMAL_CASES = (
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
)
ACCEPTED_SOLVER_STATUSES = ("optimal", "gaplimit")
SUMMARY_COLUMNS = [
    "storage_scale",
    "battery_energy_mwh",
    "battery_power_mw",
    "renewables_only_status",
    "renewables_shift_status",
    "renewables_storage_status",
    "joint_status",
    "renewables_only_cost_cny",
    "renewables_shift_cost_cny",
    "renewables_storage_cost_cny",
    "joint_cost_cny",
    "storage_base_savings_cny",
    "no_storage_shift_savings_cny",
    "storage_shift_savings_cny",
    "storage_effect_on_shift_cny",
]


@dataclass(frozen=True)
class StorageScale:
    name: str
    battery_energy_mwh: float
    battery_power_mw: float


DEFAULT_STORAGE_SCALES = (
    StorageScale("energy_2p0_mwh_power_0p5_mw", 2.0, 0.5),
    StorageScale("energy_4p0_mwh_power_1p0_mw", 4.0, 1.0),
    StorageScale("energy_6p0_mwh_power_1p5_mw", 6.0, 1.5),
)


@dataclass(frozen=True)
class StorageScaleSensitivityResult:
    metrics: pd.DataFrame
    metadata: dict[str, object]


def validate_storage_scales(
    storage_scales: tuple[StorageScale, ...],
) -> tuple[StorageScale, ...]:
    if not isinstance(storage_scales, tuple):
        raise TypeError("storage_scales must be a tuple")
    if not storage_scales:
        raise ValueError("storage_scales must not be empty")
    names: list[str] = []
    for scale in storage_scales:
        if not isinstance(scale, StorageScale):
            raise TypeError("storage_scales entries must be StorageScale")
        if not scale.name:
            raise ValueError("storage scale name must not be empty")
        if not math.isfinite(scale.battery_energy_mwh) or (
            scale.battery_energy_mwh <= 0.0
        ):
            raise ValueError("battery_energy_mwh must be positive and finite")
        if not math.isfinite(scale.battery_power_mw) or (
            scale.battery_power_mw <= 0.0
        ):
            raise ValueError("battery_power_mw must be positive and finite")
        names.append(scale.name)
    if len(set(names)) != len(names):
        raise ValueError("storage scale names must be unique")
    return storage_scales


def _case_row(
    case_metrics: pd.DataFrame,
    *,
    scale_name: str,
    case_name: str,
) -> Mapping[str, object]:
    required_columns = ("case", "status", "operating_cost_cny")
    missing_columns = [
        column for column in required_columns if column not in case_metrics
    ]
    if missing_columns:
        raise ValueError(
            "case metrics missing required columns: "
            f"{', '.join(missing_columns)}"
        )
    rows = case_metrics.loc[case_metrics["case"] == case_name]
    if len(rows) != 1:
        raise ValueError(
            f"{scale_name} must contain exactly one {case_name} row"
        )
    row = rows.iloc[0]
    status = row["status"]
    if status not in ACCEPTED_SOLVER_STATUSES:
        raise RuntimeError(
            f"{scale_name} {case_name} has unaccepted solver status {status}"
        )
    cost = float(row["operating_cost_cny"])
    if not math.isfinite(cost):
        raise ValueError(
            f"{scale_name} {case_name} operating_cost_cny must be finite"
        )
    return {
        "status": str(status),
        "operating_cost_cny": cost,
    }


def build_storage_scale_summary(
    *,
    case_metrics_by_scale: Mapping[str, pd.DataFrame],
    storage_scales: tuple[StorageScale, ...],
) -> pd.DataFrame:
    scales = validate_storage_scales(storage_scales)
    missing_scales = [
        scale.name
        for scale in scales
        if scale.name not in case_metrics_by_scale
    ]
    if missing_scales:
        raise ValueError(
            "case metrics missing storage scales: "
            f"{', '.join(missing_scales)}"
        )
    unexpected_scales = sorted(
        set(case_metrics_by_scale).difference(scale.name for scale in scales)
    )
    if unexpected_scales:
        raise ValueError(
            "case metrics contains unexpected storage scales: "
            f"{', '.join(unexpected_scales)}"
        )

    summary_rows: list[dict[str, object]] = []
    for scale in scales:
        case_metrics = case_metrics_by_scale[scale.name]
        rows = {
            case_name: _case_row(
                case_metrics,
                scale_name=scale.name,
                case_name=case_name,
            )
            for case_name in FORMAL_CASES
        }
        renewables_only_cost = float(
            rows["renewables_only"]["operating_cost_cny"]
        )
        renewables_shift_cost = float(
            rows["renewables_shift"]["operating_cost_cny"]
        )
        renewables_storage_cost = float(
            rows["renewables_storage"]["operating_cost_cny"]
        )
        joint_cost = float(rows["joint"]["operating_cost_cny"])
        no_storage_shift_savings = (
            renewables_only_cost - renewables_shift_cost
        )
        storage_shift_savings = renewables_storage_cost - joint_cost
        summary_rows.append(
            {
                "storage_scale": scale.name,
                "battery_energy_mwh": scale.battery_energy_mwh,
                "battery_power_mw": scale.battery_power_mw,
                "renewables_only_status": rows["renewables_only"]["status"],
                "renewables_shift_status": rows["renewables_shift"]["status"],
                "renewables_storage_status": rows[
                    "renewables_storage"
                ]["status"],
                "joint_status": rows["joint"]["status"],
                "renewables_only_cost_cny": renewables_only_cost,
                "renewables_shift_cost_cny": renewables_shift_cost,
                "renewables_storage_cost_cny": renewables_storage_cost,
                "joint_cost_cny": joint_cost,
                "storage_base_savings_cny": (
                    renewables_only_cost - renewables_storage_cost
                ),
                "no_storage_shift_savings_cny": no_storage_shift_savings,
                "storage_shift_savings_cny": storage_shift_savings,
                "storage_effect_on_shift_cny": (
                    storage_shift_savings - no_storage_shift_savings
                ),
            }
        )
    return pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS)


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
        "# 固定 3 小时延迟的储能规模敏感性分析",
        "",
        "## 实验设定",
        "",
        "- 全部算例固定 max_delay_h=3。",
        "- 仅同步改变储能能量、充电功率和放电功率。",
        "- 每个储能规模均为一个独立的 28 天四算例项目。",
        "- operating_cost_cny 包含 672 小时分析期与 3 小时结算尾段。",
        "",
        "## 指标定义",
        "",
        "- 无储能时移节省 = renewables_only - renewables_shift。",
        "- 有储能时移节省 = renewables_storage - joint。",
        "- 储能对时移价值的影响 = 有储能时移节省 - 无储能时移节省。",
        "- 正值表示储能增强时移节省，负值表示储能削弱时移节省。",
        "",
        "## 结果汇总",
        "",
        "| 储能规模 | 储能基准节省 (CNY) | 无储能时移节省 (CNY) | 有储能时移节省 (CNY) | 储能对时移影响 (CNY) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in metrics.itertuples(index=False):
        lines.append(
            f"| {row.storage_scale} | "
            f"{float(row.storage_base_savings_cny):,.4f} | "
            f"{float(row.no_storage_shift_savings_cny):,.4f} | "
            f"{float(row.storage_shift_savings_cny):,.4f} | "
            f"{float(row.storage_effect_on_shift_cny):,.4f} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_storage_scale_sensitivity_experiment(
    *,
    workload_data: Path,
    energy_data: Path,
    output_dir: Path,
    params: Parameters | None = None,
    storage_scales: tuple[StorageScale, ...] = DEFAULT_STORAGE_SCALES,
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
            "storage-scale sensitivity requires params.max_delay_h == 3"
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
            paths.results / "storage_scale_sensitivity.csv",
            index=False,
        )
        make_storage_scale_sensitivity_plots(metrics, paths.figures)
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
            "scenario_status": "houston_2020_storage_scale_sensitivity",
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
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)

    return StorageScaleSensitivityResult(metrics=metrics, metadata=metadata)
