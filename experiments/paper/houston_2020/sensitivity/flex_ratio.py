from __future__ import annotations

import math
import json
import shutil
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from dc_energy_opt.artifacts import build_run_provenance, staged_run_directory
from dc_energy_opt.config import Parameters
from dc_energy_opt.data import load_and_prepare, load_houston_energy_scenario
from dc_energy_opt.optimization import run_rolling_day_ahead
from dc_energy_opt.reporting import (
    make_flex_ratio_sensitivity_plots,
    software_versions,
)


DEFAULT_FLEX_RATIOS = tuple(index / 10.0 for index in range(11))
SENSITIVITY_SCENARIOS = (
    ("renewables_shift", "renewables_only"),
    ("joint", "renewables_storage"),
)
SUMMARY_COLUMNS = [
    "scenario",
    "baseline_case",
    "flex_ratio",
    "status",
    "analysis_operating_cost_cny",
    "settlement_tail_operating_cost_cny",
    "operating_cost_cny",
    "baseline_operating_cost_cny",
    "cost_savings_cny",
    "cost_savings_pct",
    "marginal_cost_savings_cny_per_flex_ratio",
    "total_task_delay_cpu_hours",
    "average_flexible_task_delay_h",
    "maximum_task_delay_h",
    "saturation_onset",
]
_NUMERIC_METRIC_COLUMNS = (
    "analysis_operating_cost_cny",
    "settlement_tail_operating_cost_cny",
    "operating_cost_cny",
    "total_task_delay_cpu_hours",
    "average_flexible_task_delay_h",
    "maximum_task_delay_h",
)
_COST_IDENTITY_TOLERANCE_CNY = 1e-7


@dataclass(frozen=True)
class FlexRatioSensitivityResult:
    metrics: pd.DataFrame
    metadata: dict[str, object]


def validate_flex_ratios(
    flex_ratios: tuple[float, ...],
) -> tuple[float, ...]:
    if not isinstance(flex_ratios, tuple):
        raise TypeError("flex_ratios 必须为元组。")
    values = tuple(float(value) for value in flex_ratios)
    if not values or values[0] != 0.0:
        raise ValueError("flex_ratios 必须以 0.0 开始。")
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
        raise ValueError("flex_ratios 必须为 0.0..1.0 内的有限值。")
    if tuple(sorted(set(values))) != values:
        raise ValueError("flex_ratios 必须严格递增且不重复。")
    return values


def _validated_metric(
    metric: Mapping[str, object],
    *,
    expected_case: str,
) -> dict[str, object]:
    required_columns = ("case", "status", *_NUMERIC_METRIC_COLUMNS)
    missing_columns = [
        column for column in required_columns if column not in metric
    ]
    if missing_columns:
        raise ValueError(
            "metric missing required columns: "
            f"{', '.join(missing_columns)}"
        )
    if metric["case"] != expected_case:
        raise ValueError(
            f"metric case must be {expected_case}; found {metric['case']}"
        )
    if not isinstance(metric["status"], str):
        raise ValueError("metric status 必须为字符串。")

    validated = {column: metric[column] for column in required_columns}
    for column in _NUMERIC_METRIC_COLUMNS:
        value = float(validated[column])
        if not math.isfinite(value):
            raise ValueError(f"metric {column} 必须为有限值。")
        validated[column] = value
    if not math.isclose(
        float(validated["operating_cost_cny"]),
        float(validated["analysis_operating_cost_cny"])
        + float(validated["settlement_tail_operating_cost_cny"]),
        rel_tol=0.0,
        abs_tol=_COST_IDENTITY_TOLERANCE_CNY,
    ):
        raise ValueError(
            "metric operating_cost_cny 必须等于分析期与结算尾段成本之和。"
        )
    return validated


def _saturation_onset(marginal_savings: list[float]) -> float:
    positive_values = [value for value in marginal_savings if value > 0.0]
    if not positive_values:
        return float("nan")
    threshold = max(positive_values) * 0.10
    for index, value in enumerate(marginal_savings):
        remaining = marginal_savings[index:]
        if 0.0 <= value <= threshold and all(
            0.0 <= later_value <= threshold
            for later_value in remaining
        ):
            return float(index)
    return float("nan")


def build_sensitivity_summary(
    *,
    baseline_metrics: Mapping[str, Mapping[str, object]],
    solved_metrics: Mapping[str, Mapping[float, Mapping[str, object]]],
    flex_ratios: tuple[float, ...],
) -> pd.DataFrame:
    ratios = validate_flex_ratios(flex_ratios)
    rows: list[dict[str, object]] = []

    for scenario, baseline_case in SENSITIVITY_SCENARIOS:
        if scenario not in baseline_metrics:
            raise ValueError(f"baseline_metrics 缺少 {scenario}")
        if scenario not in solved_metrics:
            raise ValueError(f"solved_metrics 缺少 {scenario}")
        baseline = _validated_metric(
            baseline_metrics[scenario],
            expected_case=baseline_case,
        )
        baseline_cost = float(baseline["operating_cost_cny"])
        scenario_rows: list[dict[str, object]] = []
        marginal_savings: list[float] = []
        previous_cost = baseline_cost
        for flex_ratio in ratios:
            metric = (
                baseline
                if flex_ratio == 0.0
                else _validated_metric(
                    solved_metrics[scenario][flex_ratio],
                    expected_case=scenario,
                )
            )
            operating_cost = float(metric["operating_cost_cny"])
            if flex_ratio == 0.0:
                marginal = float("nan")
            else:
                marginal = (previous_cost - operating_cost) / (
                    flex_ratio - previous_flex_ratio
                )
                marginal_savings.append(marginal)
            scenario_rows.append(
                {
                    "scenario": scenario,
                    "baseline_case": baseline_case,
                    "flex_ratio": flex_ratio,
                    "status": metric["status"],
                    "analysis_operating_cost_cny": metric[
                        "analysis_operating_cost_cny"
                    ],
                    "settlement_tail_operating_cost_cny": metric[
                        "settlement_tail_operating_cost_cny"
                    ],
                    "operating_cost_cny": operating_cost,
                    "baseline_operating_cost_cny": baseline_cost,
                    "cost_savings_cny": baseline_cost - operating_cost,
                    "cost_savings_pct": (
                        100.0 * (baseline_cost - operating_cost) / baseline_cost
                        if baseline_cost > 0.0
                        else 0.0
                    ),
                    "marginal_cost_savings_cny_per_flex_ratio": marginal,
                    "total_task_delay_cpu_hours": metric[
                        "total_task_delay_cpu_hours"
                    ],
                    "average_flexible_task_delay_h": metric[
                        "average_flexible_task_delay_h"
                    ],
                    "maximum_task_delay_h": metric[
                        "maximum_task_delay_h"
                    ],
                    "saturation_onset": float("nan"),
                }
            )
            previous_cost = operating_cost
            previous_flex_ratio = flex_ratio

        onset_index = _saturation_onset(marginal_savings)
        if not math.isnan(onset_index):
            onset_flex_ratio = ratios[int(onset_index) + 1]
            for row in scenario_rows:
                row["saturation_onset"] = onset_flex_ratio
        rows.extend(scenario_rows)

    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def _resolve_and_validate_input_paths(
    workload_data: Path,
    energy_data: Path,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    workload_path = Path(workload_data)
    energy_path = Path(energy_data)
    output_path = Path(output_dir)
    resolved_workload_path = workload_path.resolve(strict=False)
    resolved_energy_path = energy_path.resolve(strict=False)
    resolved_output_path = output_path.resolve(strict=False)
    for input_identifier, input_path in (
        ("workload_data", resolved_workload_path),
        ("energy_data", resolved_energy_path),
    ):
        if input_path == resolved_output_path or input_path.is_relative_to(
            resolved_output_path
        ):
            raise ValueError(
                f"{input_identifier} 输入路径 {input_path} 与 "
                f"output_dir {resolved_output_path} 冲突："
                "输入不得等于输出目录，"
                "也不得位于其目录树内。"
            )
    return workload_path, energy_path, output_path


def _solve_case(
    *,
    cpu_arrival: np.ndarray,
    energy_scenario: pd.DataFrame,
    params: Parameters,
    case_name: str,
    enable_shift: bool,
    enable_storage: bool,
    model_output_dir: Path,
    show_solver_log: bool,
) -> dict[str, object]:
    _, case_metrics, _ = run_rolling_day_ahead(
        cpu_arrival=cpu_arrival,
        energy_scenario=energy_scenario,
        params=params,
        case_name=case_name,
        enable_shift=enable_shift,
        enable_storage=enable_storage,
        model_output_dir=model_output_dir,
        show_log=show_solver_log,
    )
    return case_metrics


def run_flex_ratio_sensitivity_experiment(
    *,
    workload_data: Path,
    energy_data: Path,
    output_dir: Path,
    flex_ratios: tuple[float, ...] = DEFAULT_FLEX_RATIOS,
    params: Parameters | None = None,
    show_solver_log: bool = False,
) -> FlexRatioSensitivityResult:
    ratios = validate_flex_ratios(flex_ratios)
    workload_path, energy_path, output_path = _resolve_and_validate_input_paths(
        workload_data,
        energy_data,
        output_dir,
    )
    base_params = Parameters() if params is None else params

    with staged_run_directory(output_path) as paths:
        workload_snapshot = paths.inputs / "google_2019_28d_5min.csv"
        energy_snapshot = paths.inputs / "houston_2020_may_hourly.csv"
        shutil.copyfile(workload_path, workload_snapshot)
        shutil.copyfile(energy_path, energy_snapshot)

        raw, hourly, representative_day, stress_day = load_and_prepare(
            workload_snapshot
        )
        energy_scenario = load_houston_energy_scenario(
            energy_snapshot,
            base_params,
        )
        ordered_hourly = hourly.sort_values(["day", "hour"]).reset_index(
            drop=True
        )
        max_day = int(ordered_hourly["day"].max())
        if max_day != 28 or len(ordered_hourly) != 672:
            raise ValueError(
                "敏感性分析算力数据必须严格包含 28 个完整日、672 个小时。"
            )
        analysis_energy = energy_scenario.iloc[24:696].reset_index(drop=True)
        model_input = ordered_hourly.rename(
            columns={"avg_cpu": "cpu_arrival_pu"}
        ).copy()
        for column in energy_scenario.columns:
            model_input[column] = analysis_energy[column].to_numpy()
        model_input.to_csv(
            paths.inputs / "aligned_28d_hourly.csv",
            index=False,
        )
        cpu_arrival = model_input["cpu_arrival_pu"].to_numpy(dtype=float)

        zero_params = replace(base_params, flex_ratio=0.0)
        baseline_metrics: dict[str, dict[str, object]] = {}
        solved_metrics: dict[str, dict[float, dict[str, object]]] = {
            scenario: {} for scenario, _ in SENSITIVITY_SCENARIOS
        }
        baseline_specs = (
            ("renewables_shift", "renewables_only", False),
            ("joint", "renewables_storage", True),
        )
        for scenario, baseline_case, enable_storage in baseline_specs:
            baseline_metrics[scenario] = _solve_case(
                cpu_arrival=cpu_arrival,
                energy_scenario=energy_scenario,
                params=zero_params,
                case_name=baseline_case,
                enable_shift=False,
                enable_storage=enable_storage,
                model_output_dir=paths.models / scenario / "ratio_000",
                show_solver_log=show_solver_log,
            )

        for flex_ratio in ratios[1:]:
            scan_params = replace(base_params, flex_ratio=flex_ratio)
            for scenario, _, enable_storage in (
                ("renewables_shift", "renewables_only", False),
                ("joint", "renewables_storage", True),
            ):
                solved_metrics[scenario][flex_ratio] = _solve_case(
                    cpu_arrival=cpu_arrival,
                    energy_scenario=energy_scenario,
                    params=scan_params,
                    case_name=scenario,
                    enable_shift=True,
                    enable_storage=enable_storage,
                    model_output_dir=(
                        paths.models
                        / scenario
                        / f"ratio_{round(flex_ratio * 100):03d}"
                    ),
                    show_solver_log=show_solver_log,
                )

        metrics = build_sensitivity_summary(
            baseline_metrics=baseline_metrics,
            solved_metrics=solved_metrics,
            flex_ratios=ratios,
        )
        unaccepted = metrics.loc[
            ~metrics["status"].isin(("optimal", "gaplimit")),
            "status",
        ]
        if not unaccepted.empty:
            raise RuntimeError(
                "敏感性分析发现未接受的求解状态: "
                f"{sorted(unaccepted.unique().tolist())}"
            )
        metrics.to_csv(
            paths.results / "flex_ratio_sensitivity.csv",
            index=False,
        )
        make_flex_ratio_sensitivity_plots(metrics, paths.figures)

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
            "scenario_status": "houston_2020_flex_ratio_sensitivity",
            "input_file": str(workload_path),
            "energy_scenario_file": str(energy_path),
            "flex_ratios": list(ratios),
            "baseline_cases": {
                scenario: baseline_case
                for scenario, baseline_case in SENSITIVITY_SCENARIOS
            },
            "operating_cost_accounting": (
                "operating_cost_cny equals the 672-hour analysis cost plus "
                "the 3-hour settlement-tail cost; warmup cost is excluded"
            ),
            "raw_rows": int(len(raw)),
            "energy_scenario_rows": int(len(energy_scenario)),
            "days": max_day,
            "representative_day": representative_day,
            "stress_day": stress_day,
            "parameters": parameter_values,
            "software_versions": software_versions(),
        }
        metadata.update(
            build_run_provenance(
                input_files={
                    "workload": workload_snapshot,
                    "energy": energy_snapshot,
                }
            )
        )
        with (paths.root / "run_metadata.json").open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)

    return FlexRatioSensitivityResult(metrics=metrics, metadata=metadata)
