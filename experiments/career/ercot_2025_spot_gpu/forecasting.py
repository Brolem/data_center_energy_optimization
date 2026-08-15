from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import SOLAR_SIGNAL_MAX_MWH, WIND_SIGNAL_MAX_MWH


_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_FORECAST_HORIZON_HOURS = 24
_MINIMUM_HISTORY_HOURS = 169


def _timestamps(frame: pd.DataFrame) -> pd.Series:
    timestamps = pd.to_datetime(
        frame["timestamp_utc"], format=_TIMESTAMP_FORMAT, errors="coerce"
    )
    if timestamps.isna().any() or timestamps.duplicated().any():
        raise ValueError("timestamp_utc 必须可解析且不重复。")
    return timestamps


def _require_target_values(
    frame: pd.DataFrame,
    target_columns: tuple[str, ...],
) -> pd.DataFrame:
    checked = frame.copy()
    for column in target_columns:
        if column not in checked:
            raise ValueError(f"缺少预测目标字段: {column}")
        values = pd.to_numeric(checked[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"{column} 必须为有限数值。")
        checked[column] = values
    return checked


def _require_forecast_times(forecast_times: pd.DataFrame) -> pd.DataFrame:
    required_columns = ("timestamp_utc", "local_date", "local_hour")
    if any(column not in forecast_times for column in required_columns):
        raise ValueError("预测时点缺少时间字段。")
    checked = forecast_times.loc[:, required_columns].copy()
    timestamps = _timestamps(checked)
    if len(checked) != _FORECAST_HORIZON_HOURS:
        raise ValueError("日前预测必须恰好包含 24 小时。")
    expected = pd.Series(
        pd.date_range(timestamps.iloc[0], periods=_FORECAST_HORIZON_HOURS, freq="h"),
        name="timestamp_utc",
    )
    if not timestamps.reset_index(drop=True).equals(expected):
        raise ValueError("日前预测时点必须逐小时连续。")
    return checked


def _history_lookup(
    history: pd.DataFrame,
    target_column: str,
) -> tuple[pd.Series, pd.Series]:
    timestamps = _timestamps(history)
    if not timestamps.is_monotonic_increasing:
        raise ValueError("历史 timestamp_utc 必须升序。")
    values = pd.to_numeric(history[target_column], errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError(f"{target_column} 历史值必须为有限数值。")
    return timestamps, pd.Series(values.to_numpy(dtype=float), index=timestamps)


def previous_day_forecast(
    *,
    history: pd.DataFrame,
    forecast_times: pd.DataFrame,
    target_columns: tuple[str, ...],
) -> pd.DataFrame:
    """Forecast the next day by copying the prior day's matching hours."""
    checked_history = _require_target_values(history, target_columns)
    checked_times = _require_forecast_times(forecast_times)
    future_timestamps = _timestamps(checked_times)
    result = checked_times.copy()
    for column in target_columns:
        _, lookup = _history_lookup(checked_history, column)
        source_timestamps = future_timestamps - pd.Timedelta(hours=24)
        values = lookup.reindex(source_timestamps)
        if values.isna().any():
            raise ValueError(f"{column} 缺少前一日同小时历史值。")
        result[column] = values.to_numpy(dtype=float)
    return result


@dataclass(frozen=True)
class _FittedTargetModel:
    feature_means: np.ndarray
    feature_scales: np.ndarray
    coefficients: np.ndarray


@dataclass(frozen=True)
class ForecastEvaluation:
    metrics: pd.DataFrame
    baseline_validation_score: float
    feature_model_validation_score: float
    feature_model_deployable: bool


class DirectRidgeDayAheadForecaster:
    """Direct 24-hour forecast using prior-day/week lags and known calendar data."""

    def __init__(self, target_columns: tuple[str, ...], alpha: float = 1.0) -> None:
        if not target_columns:
            raise ValueError("target_columns 必须非空。")
        if not np.isfinite(alpha) or alpha <= 0.0:
            raise ValueError("alpha 必须为有限正数。")
        self.target_columns = tuple(target_columns)
        self.alpha = float(alpha)

    @staticmethod
    def _calendar_features(timestamps: pd.Series) -> np.ndarray:
        hour = timestamps.dt.hour.to_numpy(dtype=float)
        weekday = timestamps.dt.dayofweek.to_numpy(dtype=int)
        weekday_one_hot = np.eye(7, dtype=float)[weekday]
        return np.column_stack(
            (
                np.sin(2.0 * np.pi * hour / 24.0),
                np.cos(2.0 * np.pi * hour / 24.0),
                weekday_one_hot,
            )
        )

    def _fit_target(
        self,
        *,
        history: pd.DataFrame,
        target_column: str,
    ) -> _FittedTargetModel:
        timestamps, values_by_timestamp = _history_lookup(history, target_column)
        if len(history) < _MINIMUM_HISTORY_HOURS:
            raise ValueError("特征预测器至少需要 169 小时历史。")
        values = values_by_timestamp.to_numpy(dtype=float)
        target_indices = np.arange(168, len(history), dtype=int)
        training_timestamps = timestamps.iloc[target_indices].reset_index(drop=True)
        raw_features = np.column_stack(
            (
                values[target_indices - 24],
                values[target_indices - 168],
                self._calendar_features(training_timestamps),
            )
        )
        feature_means = raw_features.mean(axis=0)
        feature_scales = raw_features.std(axis=0)
        feature_scales[feature_scales == 0.0] = 1.0
        standardized = (raw_features - feature_means) / feature_scales
        design = np.column_stack((np.ones(len(standardized)), standardized))
        penalty = np.eye(design.shape[1], dtype=float)
        penalty[0, 0] = 0.0
        coefficients = np.linalg.solve(
            design.T @ design + self.alpha * penalty,
            design.T @ values[target_indices],
        )
        return _FittedTargetModel(
            feature_means=feature_means,
            feature_scales=feature_scales,
            coefficients=coefficients,
        )

    def fit_predict(
        self,
        *,
        history: pd.DataFrame,
        forecast_times: pd.DataFrame,
    ) -> pd.DataFrame:
        checked_history = _require_target_values(history, self.target_columns)
        checked_times = _require_forecast_times(forecast_times)
        future_timestamps = _timestamps(checked_times)
        result = checked_times.copy()
        for column in self.target_columns:
            fitted = self._fit_target(history=checked_history, target_column=column)
            _, values_by_timestamp = _history_lookup(checked_history, column)
            lag_24 = values_by_timestamp.reindex(
                future_timestamps - pd.Timedelta(hours=24)
            )
            lag_168 = values_by_timestamp.reindex(
                future_timestamps - pd.Timedelta(hours=168)
            )
            if lag_24.isna().any() or lag_168.isna().any():
                raise ValueError(f"{column} 缺少日前特征所需历史。")
            raw_features = np.column_stack(
                (
                    lag_24.to_numpy(dtype=float),
                    lag_168.to_numpy(dtype=float),
                    self._calendar_features(future_timestamps),
                )
            )
            standardized = (
                raw_features - fitted.feature_means
            ) / fitted.feature_scales
            design = np.column_stack((np.ones(len(standardized)), standardized))
            values = design @ fitted.coefficients
            if column == "erco_solar_generation_mwh":
                values = np.clip(values, 0.0, SOLAR_SIGNAL_MAX_MWH)
            elif column == "erco_wind_generation_mwh":
                values = np.clip(values, 0.0, WIND_SIGNAL_MAX_MWH)
            result[column] = values
        return result


def generate_day_ahead_forecast(
    *,
    frame: pd.DataFrame,
    forecast_origin_utc: str,
    target_columns: tuple[str, ...],
    forecaster: DirectRidgeDayAheadForecaster,
) -> pd.DataFrame:
    """Create 24 forecasts using only rows strictly before the cutoff."""
    checked = _require_target_values(frame, target_columns)
    timestamps = _timestamps(checked)
    origin = pd.to_datetime(
        forecast_origin_utc, format=_TIMESTAMP_FORMAT, errors="raise"
    )
    history = checked.loc[timestamps < origin].copy().reset_index(drop=True)
    future = checked.loc[timestamps >= origin].iloc[:_FORECAST_HORIZON_HOURS].copy()
    forecast_times = future.loc[:, ["timestamp_utc", "local_date", "local_hour"]]
    baseline = previous_day_forecast(
        history=history,
        forecast_times=forecast_times,
        target_columns=target_columns,
    )
    feature_model = forecaster.fit_predict(
        history=history,
        forecast_times=forecast_times,
    )
    result = forecast_times.copy()
    result.insert(0, "forecast_origin_utc", forecast_origin_utc)
    for column in target_columns:
        result[f"actual_{column}"] = future[column].to_numpy(dtype=float)
        result[f"baseline_{column}"] = baseline[column].to_numpy(dtype=float)
        result[f"feature_model_{column}"] = feature_model[column].to_numpy(dtype=float)
    return result


def evaluate_forecast_table(
    *,
    forecast_table: pd.DataFrame,
    training_frame: pd.DataFrame,
    target_columns: tuple[str, ...],
) -> ForecastEvaluation:
    """Calculate per-target forecast metrics and the fixed validation rule."""
    training = _require_target_values(training_frame, target_columns)
    rows: list[dict[str, object]] = []
    for column in target_columns:
        standard_deviation = float(training[column].std(ddof=0))
        if not math.isfinite(standard_deviation) or standard_deviation <= 0.0:
            raise ValueError(f"{column} 的训练期标准差必须为正数。")
        actual_column = f"actual_{column}"
        for model, prediction_column in (
            ("baseline", f"baseline_{column}"),
            ("feature_model", f"feature_model_{column}"),
        ):
            if actual_column not in forecast_table or prediction_column not in forecast_table:
                raise ValueError("预测表缺少评估所需字段。")
            actual = pd.to_numeric(forecast_table[actual_column], errors="coerce")
            prediction = pd.to_numeric(
                forecast_table[prediction_column], errors="coerce"
            )
            values = np.concatenate(
                (actual.to_numpy(dtype=float), prediction.to_numpy(dtype=float))
            )
            if not np.isfinite(values).all():
                raise ValueError("预测表评估字段必须为有限数值。")
            error = prediction.to_numpy(dtype=float) - actual.to_numpy(dtype=float)
            mae = float(np.mean(np.abs(error)))
            rows.append(
                {
                    "model": model,
                    "target": column,
                    "mae": mae,
                    "rmse": float(np.sqrt(np.mean(np.square(error)))),
                    "nmae": mae / standard_deviation,
                    "training_standard_deviation": standard_deviation,
                }
            )
    metrics = pd.DataFrame(rows)
    baseline_score = float(metrics.loc[metrics["model"] == "baseline", "nmae"].mean())
    feature_model_score = float(
        metrics.loc[metrics["model"] == "feature_model", "nmae"].mean()
    )
    return ForecastEvaluation(
        metrics=metrics,
        baseline_validation_score=baseline_score,
        feature_model_validation_score=feature_model_score,
        feature_model_deployable=feature_model_score < baseline_score,
    )
