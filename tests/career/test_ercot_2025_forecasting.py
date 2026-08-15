from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from experiments.career.ercot_2025_spot_gpu.forecasting import (
    DirectRidgeDayAheadForecaster,
    _ridge_normal_equations,
    _solve_linear_system,
    evaluate_forecast_table,
    generate_day_ahead_forecast,
    previous_day_forecast,
)


TARGET_COLUMNS = (
    "dam_lz_houston_usd_per_mwh",
    "erco_solar_generation_mwh",
    "erco_wind_generation_mwh",
)


def _hourly_frame(hours: int) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01 00:00:00", periods=hours, freq="h")
    hour = np.arange(hours, dtype=float)
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "local_date": timestamps.strftime("%Y-%m-%d"),
            "local_hour": timestamps.hour + 1,
            "dam_lz_houston_usd_per_mwh": 10.0 + hour,
            "erco_solar_generation_mwh": np.maximum(
                0.0, 100.0 * np.sin((timestamps.hour - 6) * np.pi / 12.0)
            ),
            "erco_wind_generation_mwh": 500.0 + 2.0 * hour,
        }
    )


class DayAheadForecastTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = _hourly_frame(240)
        self.forecast_origin_utc = self.frame.loc[216, "timestamp_utc"]
        self.history = self.frame.iloc[:216].copy()
        self.forecast_times = self.frame.iloc[216:240].loc[
            :, ["timestamp_utc", "local_date", "local_hour"]
        ]

    def test_previous_day_baseline_copies_matching_hour(self) -> None:
        forecast = previous_day_forecast(
            history=self.history,
            forecast_times=self.forecast_times,
            target_columns=TARGET_COLUMNS,
        )

        np.testing.assert_allclose(
            forecast["dam_lz_houston_usd_per_mwh"].to_numpy(),
            self.frame.loc[192:215, "dam_lz_houston_usd_per_mwh"].to_numpy(),
        )

    def test_linear_solver_returns_the_known_solution(self) -> None:
        coefficients = _solve_linear_system(
            np.array([[3.0, 1.0], [1.0, 2.0]]),
            np.array([9.0, 8.0]),
        )

        np.testing.assert_allclose(coefficients, np.array([2.0, 3.0]))

    def test_ridge_normal_equations_use_an_unpenalized_intercept(self) -> None:
        matrix, right_hand_side = _ridge_normal_equations(
            np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]),
            np.array([7.0, 8.0, 9.0]),
            alpha=0.5,
        )

        np.testing.assert_allclose(matrix, np.array([[35.0, 44.0], [44.0, 56.5]]))
        np.testing.assert_allclose(right_hand_side, np.array([76.0, 100.0]))

    def test_feature_forecast_does_not_use_values_after_cutoff(self) -> None:
        original = generate_day_ahead_forecast(
            frame=self.frame,
            forecast_origin_utc=self.forecast_origin_utc,
            target_columns=TARGET_COLUMNS,
            forecaster=DirectRidgeDayAheadForecaster(TARGET_COLUMNS),
        )
        changed_future = self.frame.copy()
        changed_future.loc[216:, TARGET_COLUMNS] = 1_000_000.0
        changed = generate_day_ahead_forecast(
            frame=changed_future,
            forecast_origin_utc=self.forecast_origin_utc,
            target_columns=TARGET_COLUMNS,
            forecaster=DirectRidgeDayAheadForecaster(TARGET_COLUMNS),
        )

        for column in TARGET_COLUMNS:
            np.testing.assert_allclose(
                original[f"baseline_{column}"].to_numpy(),
                changed[f"baseline_{column}"].to_numpy(),
            )
            np.testing.assert_allclose(
                original[f"feature_model_{column}"].to_numpy(),
                changed[f"feature_model_{column}"].to_numpy(),
            )
        self.assertFalse(
            np.array_equal(
                original[f"actual_{TARGET_COLUMNS[0]}"].to_numpy(),
                changed[f"actual_{TARGET_COLUMNS[0]}"].to_numpy(),
            )
        )

    def test_feature_forecast_clips_only_renewable_targets(self) -> None:
        forecaster = DirectRidgeDayAheadForecaster(TARGET_COLUMNS)
        forecast = forecaster.fit_predict(
            history=self.history,
            forecast_times=self.forecast_times,
        )

        self.assertTrue((forecast["erco_solar_generation_mwh"] >= 0.0).all())
        self.assertTrue((forecast["erco_wind_generation_mwh"] >= 0.0).all())
        self.assertIn("dam_lz_houston_usd_per_mwh", forecast.columns)

    def test_day_ahead_forecast_can_include_three_hour_closure_preview(self) -> None:
        frame_with_closure = _hourly_frame(243)
        forecast = generate_day_ahead_forecast(
            frame=frame_with_closure,
            forecast_origin_utc=self.forecast_origin_utc,
            target_columns=TARGET_COLUMNS,
            forecaster=DirectRidgeDayAheadForecaster(TARGET_COLUMNS),
            forecast_horizon_hours=27,
        )

        self.assertEqual(len(forecast), 27)
        self.assertEqual(
            forecast["timestamp_utc"].iloc[-1],
            frame_with_closure["timestamp_utc"].iloc[242],
        )

    def test_forecast_ignores_missing_values_after_its_horizon(self) -> None:
        frame_with_later_gap = _hourly_frame(300)
        frame_with_later_gap.loc[299, TARGET_COLUMNS] = np.nan

        forecast = generate_day_ahead_forecast(
            frame=frame_with_later_gap,
            forecast_origin_utc=self.forecast_origin_utc,
            target_columns=TARGET_COLUMNS,
            forecaster=DirectRidgeDayAheadForecaster(TARGET_COLUMNS),
        )

        self.assertEqual(len(forecast), 24)

    def test_validation_score_selects_only_the_lower_normalized_error(self) -> None:
        forecast_table = pd.DataFrame(
            {
                "actual_dam_lz_houston_usd_per_mwh": [10.0, 20.0],
                "baseline_dam_lz_houston_usd_per_mwh": [10.0, 20.0],
                "feature_model_dam_lz_houston_usd_per_mwh": [12.0, 22.0],
                "actual_erco_solar_generation_mwh": [50.0, 100.0],
                "baseline_erco_solar_generation_mwh": [50.0, 100.0],
                "feature_model_erco_solar_generation_mwh": [60.0, 110.0],
                "actual_erco_wind_generation_mwh": [400.0, 500.0],
                "baseline_erco_wind_generation_mwh": [400.0, 500.0],
                "feature_model_erco_wind_generation_mwh": [420.0, 520.0],
            }
        )
        training = _hourly_frame(240)

        evaluation = evaluate_forecast_table(
            forecast_table=forecast_table,
            training_frame=training,
            target_columns=TARGET_COLUMNS,
        )

        self.assertFalse(evaluation.feature_model_deployable)
        self.assertLess(
            evaluation.baseline_validation_score,
            evaluation.feature_model_validation_score,
        )
        self.assertEqual(
            set(evaluation.metrics["model"]), {"baseline", "feature_model"}
        )


if __name__ == "__main__":
    unittest.main()
