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
from scip_first_version.data import load_and_prepare, load_energy_scenario
from scip_first_version.model import build_and_solve
from scip_first_version.reporting import (
    LEGACY_PLOT_FILENAMES,
    make_plots,
    software_versions,
)

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


def _generated_output_names() -> set[str]:
    case_names = [
        "grid_only",
        "renewables_only",
        "renewables_shift",
        "renewables_storage",
        "joint",
    ]
    return {
        "all_days_hourly.csv",
        "model_input_typical_day.csv",
        "hourly_case_results.csv",
        "case_metrics.csv",
        "run_metadata.json",
        *(
            f"{case_name}_{stage}.lp"
            for case_name in case_names
            for stage in ("primary", "secondary")
        ),
        "day_ahead_power_results.png",
        "compute_scheduling_results.png",
        "battery_operation_results.png",
        "renewable_dispatch_results.png",
        "operating_cost_comparison.png",
    }


def _reserved_output_names() -> set[str]:
    return _generated_output_names() | set(LEGACY_PLOT_FILENAMES)


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
    weather_source_path = args.weather_source
    energy_scenario_path = args.energy_scenario
    final_output_dir = args.output_dir
    source_paths = [csv_path, weather_source_path, energy_scenario_path]
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
    _validate_archive_targets(source_paths, final_output_dir)
    final_output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".day-ahead-staging-",
        dir=final_output_dir.parent,
    ) as staging_name:
        output_dir = Path(staging_name)
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
            remove_names=set(LEGACY_PLOT_FILENAMES),
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
