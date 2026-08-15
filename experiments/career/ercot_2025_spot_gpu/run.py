from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from dc_energy_opt.artifacts import build_run_provenance, staged_run_directory
from dc_energy_opt.config import Parameters

from .config import (
    FORECAST_TARGET_COLUMNS,
    PROJECT_ROOT,
    REPLAY_START_SECONDS,
    REPLAY_STOP_SECONDS,
    SOLAR_SIGNAL_MAX_MWH,
    WIND_SIGNAL_MAX_MWH,
)
from .data import (
    EnergySplits,
    build_energy_splits,
    load_energy_table,
    map_generation_signal_to_available_mw,
)
from .forecasting import (
    DirectRidgeDayAheadForecaster,
    ForecastEvaluation,
    evaluate_forecast_table,
    generate_day_ahead_forecast,
)
from .replay import SpotReplay, build_spot_replay
from .reporting import (
    write_forecast_comparison_figure,
    write_settlement_comparison_figure,
)
from .rolling import MARKET_ENERGY_COLUMNS, run_rolling_market_dispatch
from .settlement import build_decision_metrics, settle_schedule


@dataclass(frozen=True)
class CareerRunResult:
    output_directory: Path
    decision_metrics: pd.DataFrame
    forecast_evaluation: ForecastEvaluation
    metadata: dict[str, object]


def _validate_input_output_separation(
    *,
    energy_path: Path,
    spot_job_path: Path,
    output_directory: Path,
) -> None:
    resolved_output = output_directory.resolve(strict=False)
    outputs_root = (PROJECT_ROOT / "outputs").resolve(strict=False)
    career_output_root = (outputs_root / "career").resolve(strict=False)
    if resolved_output.is_relative_to(outputs_root) and not resolved_output.is_relative_to(
        career_output_root
    ):
        raise ValueError(
            "项目内输出目录只能位于 outputs/career/ 下；"
            "不得写入论文线或其他 outputs 路径。"
        )
    for identifier, source_path in (
        ("energy_path", energy_path),
        ("spot_job_path", spot_job_path),
    ):
        resolved_source = source_path.resolve(strict=False)
        if resolved_source == resolved_output or resolved_source.is_relative_to(resolved_output):
            raise ValueError(
                f"{identifier} 不得等于 output_directory 或位于其目录树内。"
            )


def _format_timestamps_for_csv(frame: pd.DataFrame) -> pd.DataFrame:
    formatted = frame.copy()
    if "timestamp_utc" in formatted:
        timestamps = pd.to_datetime(formatted["timestamp_utc"], errors="raise", utc=True)
        formatted["timestamp_utc"] = timestamps.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return formatted


def _market_energy_from_raw(frame: pd.DataFrame, params: Parameters) -> pd.DataFrame:
    solar_available, wind_available = map_generation_signal_to_available_mw(
        solar_generation_mwh=frame["erco_solar_generation_mwh"].to_numpy(dtype=float),
        wind_generation_mwh=frame["erco_wind_generation_mwh"].to_numpy(dtype=float),
        params=params,
    )
    return pd.DataFrame(
        {
            "timestamp_utc": frame["timestamp_utc"].to_numpy(),
            "price_usd_per_mwh": frame["dam_lz_houston_usd_per_mwh"].to_numpy(dtype=float),
            "solar_available_mw": solar_available,
            "wind_available_mw": wind_available,
        },
        columns=MARKET_ENERGY_COLUMNS,
    )


def _daily_forecasts(
    *,
    energy_table: pd.DataFrame,
    dates: pd.Series,
    forecast_horizon_hours: int,
) -> pd.DataFrame:
    forecaster = DirectRidgeDayAheadForecaster(FORECAST_TARGET_COLUMNS)
    batches: list[pd.DataFrame] = []
    for local_date in dates.tolist():
        origin_rows = energy_table.loc[energy_table["local_date"] == local_date]
        if origin_rows.empty:
            raise ValueError(f"未找到预测日期 {local_date} 的能源记录。")
        forecast = generate_day_ahead_forecast(
            frame=energy_table,
            forecast_origin_utc=str(origin_rows["timestamp_utc"].iloc[0]),
            target_columns=FORECAST_TARGET_COLUMNS,
            forecaster=forecaster,
            forecast_horizon_hours=forecast_horizon_hours,
        )
        forecast.insert(1, "forecast_local_date", local_date)
        forecast.insert(2, "forecast_horizon_hour", np.arange(len(forecast), dtype=int))
        batches.append(forecast)
    return pd.concat(batches, ignore_index=True)


def _predicted_market_energy(
    *,
    forecasts: pd.DataFrame,
    prediction_prefix: str,
    params: Parameters,
) -> pd.DataFrame:
    prediction_columns = {
        target: f"{prediction_prefix}_{target}" for target in FORECAST_TARGET_COLUMNS
    }
    missing_columns = [
        column for column in prediction_columns.values() if column not in forecasts
    ]
    if missing_columns:
        raise ValueError("预测表缺少日前调度字段。")
    raw_shape = pd.DataFrame(
        {
            "timestamp_utc": forecasts["timestamp_utc"].to_numpy(),
            "dam_lz_houston_usd_per_mwh": forecasts[
                prediction_columns["dam_lz_houston_usd_per_mwh"]
            ].to_numpy(dtype=float),
            "erco_solar_generation_mwh": forecasts[
                prediction_columns["erco_solar_generation_mwh"]
            ].to_numpy(dtype=float),
            "erco_wind_generation_mwh": forecasts[
                prediction_columns["erco_wind_generation_mwh"]
            ].to_numpy(dtype=float),
        }
    )
    return _market_energy_from_raw(raw_shape, params)


def _test_forecast_schedule_inputs(test_forecasts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    analysis = test_forecasts.loc[
        test_forecasts["forecast_horizon_hour"] < 24
    ].copy()
    closure = test_forecasts.loc[
        (test_forecasts["forecast_local_date"] == test_forecasts["forecast_local_date"].iloc[-1])
        & (test_forecasts["forecast_horizon_hour"] >= 24)
    ].copy()
    aligned = pd.concat((analysis, closure), ignore_index=True)
    if len(analysis) != 720 or len(closure) != 3 or len(aligned) != 723:
        raise ValueError("测试日前预测必须包含 720 小时分析期和 3 小时结算尾段。")
    timestamps = pd.to_datetime(aligned["timestamp_utc"], format="%Y-%m-%dT%H:%M:%SZ")
    expected = pd.Series(pd.date_range(timestamps.iloc[0], periods=723, freq="h"))
    if not timestamps.reset_index(drop=True).equals(expected):
        raise ValueError("测试日前预测时间索引必须逐小时连续。")
    return analysis, aligned


def _energy_split_snapshot(splits: EnergySplits) -> pd.DataFrame:
    frames = (
        splits.train.assign(split="train"),
        splits.validation.assign(split="validation"),
        splits.test.assign(split="test"),
        splits.test_with_closure.iloc[-3:].assign(split="settlement_closure"),
    )
    return pd.concat(frames, ignore_index=True)


def _input_manifest(
    *,
    provenance: dict[str, object],
    energy_path: Path,
    spot_job_path: Path,
    replay: SpotReplay,
) -> dict[str, object]:
    return {
        "input_provenance": provenance,
        "input_paths": {
            "annual_energy": str(energy_path.resolve(strict=False)),
            "spot_job_table": str(spot_job_path.resolve(strict=False)),
        },
        "annual_energy_schema": [
            "timestamp_utc",
            "local_date",
            "local_hour",
            "local_time_end",
            "delivery_date",
            "hour_ending",
            "repeated_hour_flag",
            "dam_lz_houston_usd_per_mwh",
            "erco_solar_generation_mwh",
            "erco_wind_generation_mwh",
            "erco_consumed_co2_intensity_lbs_per_kwh",
        ],
        "split_contract": {
            "train_local_dates": ["2025-01-01", "2025-06-30"],
            "validation_local_dates": ["2025-07-01", "2025-07-30"],
            "test_local_dates": ["2025-08-01", "2025-08-30"],
            "settlement_closure": "2025-08-31 local hours 1-3",
        },
        "forecaster": {
            "type": "direct_ridge_day_ahead",
            "alpha": 1.0,
            "lag_hours": [24, 168],
            "calendar_features": ["hour_sin", "hour_cos", "weekday_one_hot"],
            "baseline": "previous_day_same_hour",
        },
        "generation_scenario_normalization": {
            "solar_signal_max_mwh": SOLAR_SIGNAL_MAX_MWH,
            "wind_signal_max_mwh": WIND_SIGNAL_MAX_MWH,
            "meaning": "system-generation signals are mapped to bounded scenario availability",
        },
        "spot_replay": {
            "relative_second_interval": [REPLAY_START_SECONDS, REPLAY_STOP_SECONDS],
            "spot_job_count": replay.spot_job_count,
            "gpu_hour_proxy_formula": "gpu_request * worker_num * duration / 3600",
            "utilization_mapping": "0.60 * hourly_gpu_hour_work / max(hourly_gpu_hour_work)",
        },
        "interpretation": {
            "counterfactual_replay": "Spot GPU jobs are replayed as a counterfactual workload scenario; this does not assert an Alibaba operation in ERCOT or Houston.",
            "renewable_signal": "ERCO solar and wind are system-generation scenario signals, not local data-center generation measurements.",
            "workload_power": "The GPU-hour-to-utilization mapping is a proxy and not measured power or measured cluster utilization.",
        },
    }


def run_career_day_ahead(
    *,
    energy_path: Path,
    spot_job_path: Path,
    output_directory: Path,
    params: Parameters | None = None,
    show_solver_log: bool = False,
) -> CareerRunResult:
    """Run the fixed career forecasting and counterfactual dispatch workflow."""
    annual_energy_path = Path(energy_path)
    job_path = Path(spot_job_path)
    final_output = Path(output_directory)
    if not job_path.is_file():
        raise FileNotFoundError(f"找不到 Spot 作业表: {job_path}")
    _validate_input_output_separation(
        energy_path=annual_energy_path,
        spot_job_path=job_path,
        output_directory=final_output,
    )
    experiment_params = Parameters() if params is None else params
    annual_energy = load_energy_table(annual_energy_path)
    splits = build_energy_splits(annual_energy)
    replay = build_spot_replay(pd.read_csv(job_path))
    validation_forecasts = _daily_forecasts(
        energy_table=annual_energy,
        dates=splits.validation["local_date"].drop_duplicates(),
        forecast_horizon_hours=24,
    )
    forecast_evaluation = evaluate_forecast_table(
        forecast_table=validation_forecasts,
        training_frame=splits.train,
        target_columns=FORECAST_TARGET_COLUMNS,
    )
    test_forecasts = _daily_forecasts(
        energy_table=annual_energy,
        dates=splits.test["local_date"].drop_duplicates(),
        forecast_horizon_hours=27,
    )
    test_export, test_forecast_inputs = _test_forecast_schedule_inputs(test_forecasts)
    actual_market = _market_energy_from_raw(splits.test_with_closure, experiment_params)
    baseline_market = _predicted_market_energy(
        forecasts=test_forecast_inputs,
        prediction_prefix="baseline",
        params=experiment_params,
    )
    feature_market = _predicted_market_energy(
        forecasts=test_forecast_inputs,
        prediction_prefix="feature_model",
        params=experiment_params,
    )
    if not pd.Series(actual_market["timestamp_utc"]).equals(
        pd.Series(baseline_market["timestamp_utc"])
    ) or not pd.Series(actual_market["timestamp_utc"]).equals(
        pd.Series(feature_market["timestamp_utc"])
    ):
        raise RuntimeError("实际与预测市场场景的时间索引不一致。")
    provenance = build_run_provenance(
        input_files={"annual_energy": annual_energy_path, "spot_job_table": job_path}
    )
    metadata: dict[str, object] = {
        "project": "ercot_2025_spot_gpu_prediction_driven_dispatch",
        "model_type": "rolling_24_plus_3_forecast_driven_market_dispatch",
        "actual_settlement": "Fixed planned actions are settled with actual price and renewable-signal availability.",
        "feature_model_deployable": forecast_evaluation.feature_model_deployable,
        "baseline_validation_score": forecast_evaluation.baseline_validation_score,
        "feature_model_validation_score": forecast_evaluation.feature_model_validation_score,
        "parameters": asdict(experiment_params),
        **provenance,
    }
    workload = replay.hourly["workload_arrival_pu"].to_numpy(dtype=float)
    with staged_run_directory(final_output) as paths:
        _format_timestamps_for_csv(_energy_split_snapshot(splits)).to_csv(
            paths.inputs / "energy_splits.csv", index=False
        )
        replay.hourly.to_csv(paths.inputs / "spot_replay_720h.csv", index=False)
        with (paths.inputs / "input_manifest.json").open("w", encoding="utf-8") as file:
            json.dump(
                _input_manifest(
                    provenance=provenance,
                    energy_path=annual_energy_path,
                    spot_job_path=job_path,
                    replay=replay,
                ),
                file,
                ensure_ascii=False,
                indent=2,
            )
        validation_metrics = forecast_evaluation.metrics.copy()
        validation_metrics["baseline_validation_score"] = forecast_evaluation.baseline_validation_score
        validation_metrics["feature_model_validation_score"] = forecast_evaluation.feature_model_validation_score
        validation_metrics["feature_model_deployable"] = forecast_evaluation.feature_model_deployable
        validation_metrics.to_csv(paths.models / "forecast_validation_metrics.csv", index=False)
        _format_timestamps_for_csv(test_export).to_csv(
            paths.models / "test_day_ahead_predictions.csv", index=False
        )
        schedules_by_case: dict[str, pd.DataFrame] = {}
        daily_metrics_by_case: dict[str, pd.DataFrame] = {}
        for case_name, market_scenario in (
            ("oracle_actual", actual_market),
            ("baseline_forecast", baseline_market),
            ("feature_model_forecast", feature_market),
        ):
            schedule, daily_metrics = run_rolling_market_dispatch(
                workload_arrival_pu=workload,
                energy_scenario=market_scenario,
                params=experiment_params,
                case_name=case_name,
                model_output_dir=paths.models / "lp" / case_name,
                show_log=show_solver_log,
            )
            schedules_by_case[case_name] = schedule
            daily_metrics_by_case[case_name] = daily_metrics
            _format_timestamps_for_csv(schedule).to_csv(
                paths.results / f"{case_name}_hourly_schedule.csv", index=False
            )
        settlements_by_case = {
            case_name: settle_schedule(
                planned_schedule=schedule,
                actual_energy=actual_market,
                params=experiment_params,
            )
            for case_name, schedule in schedules_by_case.items()
        }
        all_settlements = pd.concat(
            tuple(settlements_by_case.values()), ignore_index=True
        )
        _format_timestamps_for_csv(all_settlements).to_csv(
            paths.results / "actual_hourly_settlement.csv", index=False
        )
        decision_metrics = build_decision_metrics(
            settlements_by_case=settlements_by_case,
            daily_metrics_by_case=daily_metrics_by_case,
        )
        oracle_regret = float(
            decision_metrics.loc[
                decision_metrics["case"] == "oracle_actual", "decision_regret_usd"
            ].iloc[0]
        )
        if abs(oracle_regret) > 1e-6:
            raise RuntimeError("oracle_actual 的决策遗憾必须为零。")
        decision_metrics.to_csv(paths.results / "decision_metrics.csv", index=False)
        write_forecast_comparison_figure(
            test_export, paths.figures / "forecast_actual_vs_prediction.png"
        )
        write_settlement_comparison_figure(
            decision_metrics, paths.figures / "actual_settlement_comparison.png"
        )
        with (paths.root / "run_metadata.json").open("w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
    return CareerRunResult(
        output_directory=final_output,
        decision_metrics=decision_metrics,
        forecast_evaluation=forecast_evaluation,
        metadata=metadata,
    )
