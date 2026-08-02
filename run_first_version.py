from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import tempfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from scip_first_version.config import Parameters
from scip_first_version.data import (
    load_and_prepare,
    load_houston_energy_scenario,
)
from scip_first_version.model import build_and_solve
from scip_first_version.rolling import ROLLING_CASES, run_rolling_day_ahead
from scip_first_version.reporting import (
    LEGACY_PLOT_FILENAMES,
    make_plots,
    software_versions,
)

__all__ = [
    "Parameters",
    "load_and_prepare",
    "load_houston_energy_scenario",
    "build_and_solve",
    "run_rolling_day_ahead",
    "make_plots",
    "main",
]


LEGACY_GENERATED_FILENAMES = [
    *LEGACY_PLOT_FILENAMES,
    "model_input_typical_day.csv",
    *(
        f"{case_name}_{stage}.lp"
        for case_name in (
            "grid_only",
            "renewables_only",
            "renewables_shift",
            "renewables_storage",
            "joint",
        )
        for stage in ("primary", "secondary")
    ),
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
        "--energy-scenario",
        type=Path,
        default=Path(
            "data/houston_2020_main_experiment_energy_scenario.csv"
        ),
        help="699 小时 Houston 2020 风光与外生论文分段电价场景 CSV",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/day_ahead_deterministic"),
        help="结果输出目录",
    )
    parser.add_argument(
        "--show-scip-log",
        action="store_true",
        help="显示 SCIP 求解日志",
    )
    return parser.parse_args()


def _normalized_path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _generated_output_names() -> set[str]:
    case_names = [case_name for case_name, _, _ in ROLLING_CASES]
    lp_names = {
        f"{case_name}_day_{day:02d}_{stage}.lp"
        for case_name in case_names
        for day in range(1, 29)
        for stage in ("primary", "secondary")
    }
    lp_names.update(
        f"{case_name}_warmup_{stage}.lp"
        for case_name, enable_shift, _ in ROLLING_CASES
        if enable_shift
        for stage in ("primary", "secondary")
    )
    lp_names.update(
        f"{case_name}_soc_coordination_{stage}.lp"
        for case_name, _, enable_storage in ROLLING_CASES
        if enable_storage
        for stage in ("primary", "secondary")
    )
    return {
        "all_days_hourly.csv",
        "model_input_28_days.csv",
        "hourly_case_results.csv",
        "daily_case_metrics.csv",
        "case_metrics.csv",
        "run_metadata.json",
        *lp_names,
        "day_ahead_power_results.png",
        "compute_scheduling_results.png",
        "battery_operation_results.png",
        "renewable_dispatch_results.png",
        "operating_cost_comparison.png",
    }


def _reserved_output_names() -> set[str]:
    return _generated_output_names() | set(LEGACY_GENERATED_FILENAMES)


def _validate_archive_targets(
    source_paths: list[Path],
    output_dir: Path,
) -> None:
    reserved_target_names = {
        _normalized_path_key(output_dir / name): name
        for name in _reserved_output_names()
    }
    source_by_target_key: dict[str, Path] = {}
    for source_path in source_paths:
        resolved_source = source_path.resolve(strict=False)
        target_path = output_dir / source_path.name
        target_key = _normalized_path_key(target_path)
        reserved_name = reserved_target_names.get(target_key)
        if reserved_name is not None:
            raise ValueError(
                f"源文件 {resolved_source} 与保留生成物目标 "
                f"{reserved_name} 冲突"
            )
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


def _archive_source_files(
    source_paths: list[Path],
    output_dir: Path,
) -> None:
    _validate_archive_targets(source_paths, output_dir)

    for source_path in source_paths:
        target_path = output_dir / source_path.name
        if _normalized_path_key(source_path) == _normalized_path_key(
            target_path
        ):
            continue
        shutil.copy2(source_path, target_path)


def _unlink_for_rollback(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except PermissionError:
        if os.name != "nt":
            raise
        path.chmod(stat.S_IWRITE)
        path.unlink()


def _publish_staged_outputs(
    staging_dir: Path,
    output_dir: Path,
    remove_names: set[str] | None = None,
) -> None:
    staged_files = sorted(
        (path for path in staging_dir.iterdir() if path.is_file()),
        key=lambda path: path.name,
    )
    staged_target_keys = {
        _normalized_path_key(output_dir / staged_path.name)
        for staged_path in staged_files
    }
    removal_targets_by_key: dict[str, Path] = {}
    for remove_name in sorted(remove_names or set()):
        remove_path = Path(remove_name)
        if (
            not remove_name
            or remove_name in {".", ".."}
            or remove_path.is_absolute()
            or remove_path.name != remove_name
        ):
            raise ValueError(
                f"remove_names 只允许扁平文件名: {remove_name!r}"
            )
        target_path = output_dir / remove_name
        target_key = _normalized_path_key(target_path)
        if target_key not in staged_target_keys:
            removal_targets_by_key.setdefault(target_key, target_path)

    output_dir_existed = output_dir.exists()
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(
        tempfile.mkdtemp(
            prefix=".day-ahead-backup-",
            dir=output_dir.parent,
        )
    )
    backed_up_targets: list[tuple[Path, Path]] = []
    published_targets: list[Path] = []
    try:
        for staged_path in staged_files:
            target_path = output_dir / staged_path.name
            if target_path.exists():
                backup_path = backup_dir / staged_path.name
                os.replace(target_path, backup_path)
                backed_up_targets.append((target_path, backup_path))

        for target_path in removal_targets_by_key.values():
            if target_path.exists():
                backup_path = backup_dir / target_path.name
                os.replace(target_path, backup_path)
                backed_up_targets.append((target_path, backup_path))

        for staged_path in staged_files:
            target_path = output_dir / staged_path.name
            os.replace(staged_path, target_path)
            published_targets.append(target_path)
    except BaseException as publish_error:
        rollback_errors: list[str] = []
        for target_path in reversed(published_targets):
            try:
                _unlink_for_rollback(target_path)
            except BaseException as error:
                rollback_errors.append(f"删除 {target_path} 失败: {error}")

        restore_errors: list[str] = []
        for target_path, backup_path in reversed(backed_up_targets):
            try:
                os.replace(backup_path, target_path)
            except BaseException as error:
                restore_errors.append(
                    f"恢复 {backup_path} 到 {target_path} 失败: {error}"
                )
        if restore_errors:
            raise RuntimeError(
                f"发布失败且旧目标恢复失败；备份保留在 {backup_dir}: "
                + "; ".join(restore_errors)
            ) from publish_error

        try:
            backup_dir.rmdir()
        except BaseException as error:
            rollback_errors.append(f"清理 {backup_dir} 失败: {error}")
        if not output_dir_existed:
            try:
                output_dir.rmdir()
            except BaseException as error:
                rollback_errors.append(f"清理 {output_dir} 失败: {error}")
        if rollback_errors:
            raise RuntimeError(
                "发布失败且回滚清理未完整完成: "
                + "; ".join(rollback_errors)
            ) from publish_error
        raise
    else:
        try:
            for _, backup_path in backed_up_targets:
                _unlink_for_rollback(backup_path)
            backup_dir.rmdir()
        except BaseException as error:
            raise RuntimeError(
                f"发布成功但备份清理失败；备份保留在 {backup_dir}: "
                f"{error}"
            ) from error


def main() -> None:
    args = parse_args()
    csv_path = args.input
    energy_scenario_path = args.energy_scenario
    final_output_dir = args.output_dir
    source_paths = [csv_path, energy_scenario_path]
    params = Parameters()

    raw, hourly, representative_day, stress_day = load_and_prepare(csv_path)
    energy_scenario = load_houston_energy_scenario(
        energy_scenario_path,
        params,
    )
    max_day = int(hourly["day"].max())
    ordered_hourly = hourly.sort_values(["day", "hour"]).reset_index(drop=True)
    if max_day != 28 or len(ordered_hourly) != 672:
        raise ValueError("主实验算力数据必须严格包含 28 个完整日、672 个小时。")
    analysis_energy = energy_scenario.iloc[24:696].reset_index(drop=True)
    model_input = ordered_hourly.rename(
        columns={"avg_cpu": "cpu_arrival_pu"}
    ).copy()
    for column in energy_scenario.columns:
        model_input[column] = analysis_energy[column].to_numpy()
    _validate_archive_targets(source_paths, final_output_dir)
    final_output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".day-ahead-staging-",
        dir=final_output_dir.parent,
    ) as staging_name:
        output_dir = Path(staging_name)
        model_input.to_csv(
            output_dir / "model_input_28_days.csv",
            index=False,
        )
        hourly.to_csv(output_dir / "all_days_hourly.csv", index=False)

        cpu_arrival = model_input["cpu_arrival_pu"].to_numpy(dtype=float)

        results = []
        metric_rows = []
        daily_results = []
        for (
            case_name,
            enable_shift,
            enable_storage,
        ) in ROLLING_CASES:
            result, metrics, daily_metrics = run_rolling_day_ahead(
                cpu_arrival=cpu_arrival,
                energy_scenario=energy_scenario,
                params=params,
                case_name=case_name,
                enable_shift=enable_shift,
                enable_storage=enable_storage,
                output_dir=output_dir,
                show_log=args.show_scip_log,
            )
            results.append(result)
            metric_rows.append(metrics)
            daily_results.append(daily_metrics)

        all_results = pd.concat(results, ignore_index=True)
        metrics = pd.DataFrame(metric_rows)
        daily_metrics = pd.concat(daily_results, ignore_index=True)
        renewables_only_cost = float(
            metrics.loc[
                metrics["case"] == "renewables_only", "operating_cost_cny"
            ].iloc[0]
        )
        metrics["operating_cost_savings_vs_renewables_only_pct"] = (
            100.0
            * (renewables_only_cost - metrics["operating_cost_cny"])
            / renewables_only_cost
            if renewables_only_cost > 0.0
            else 0.0
        )

        all_results.to_csv(output_dir / "hourly_case_results.csv", index=False)
        daily_metrics.to_csv(output_dir / "daily_case_metrics.csv", index=False)
        metrics.to_csv(output_dir / "case_metrics.csv", index=False)
        make_plots(all_results, metrics, output_dir)

        parameter_values = asdict(params)
        parameter_values.update(
            {
                "server_idle_power_kw": params.server_idle_power_kw,
                "solar_capacity_mw": params.solar_capacity_mw,
                "solar_inverter_capacity_mw": (
                    params.solar_inverter_capacity_mw
                ),
                "wind_capacity_mw": params.wind_capacity_mw,
            }
        )
        metadata = {
            "model_type": "rolling_24_plus_3_deterministic_day_ahead",
            "scenario_status": "houston_2020_main_experiment",
            "input_file": str(csv_path),
            "energy_scenario_file": str(energy_scenario_path),
            "renewable_data_source": {
                "file": str(energy_scenario_path),
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
                "file": str(energy_scenario_path),
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
                "maximum_task_delay_hours": params.max_delay_h,
                "soc_coordination": (
                    "one full-period deterministic coordination solve; "
                    "daily boundary targets enforced in rolling windows"
                ),
            },
            "formal_cases": [case_name for case_name, _, _ in ROLLING_CASES],
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
        with (output_dir / "run_metadata.json").open(
            "w", encoding="utf-8"
        ) as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)

        archived_source_paths = [
            source_path
            for source_path in source_paths
            if _normalized_path_key(source_path)
            != _normalized_path_key(final_output_dir / source_path.name)
        ]
        _archive_source_files(archived_source_paths, output_dir)
        _publish_staged_outputs(
            output_dir,
            final_output_dir,
            remove_names=set(LEGACY_GENERATED_FILENAMES),
        )

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
