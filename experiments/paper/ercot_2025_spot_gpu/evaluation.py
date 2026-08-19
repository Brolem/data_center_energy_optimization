from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


LBS_TO_KG = 0.45359237


@dataclass(frozen=True)
class EvaluationMetrics:
    cost_usd: float
    actual_renewable_alignment_index: float
    actual_co2_kg: float


def normalized_renewable_index(
    solar_generation_mwh: np.ndarray,
    wind_generation_mwh: np.ndarray,
) -> np.ndarray:
    combined = np.asarray(solar_generation_mwh, dtype=float) + np.asarray(
        wind_generation_mwh, dtype=float
    )
    positive = combined[combined > 0.0]
    if len(positive) == 0:
        return np.zeros_like(combined)
    return np.maximum(combined, 0.0) / float(positive.max())


def evaluate_hourly_replay(hourly: pd.DataFrame) -> EvaluationMetrics:
    required = {
        "facility_mw",
        "dam_lz_houston_usd_per_mwh",
        "erco_solar_generation_mwh",
        "erco_wind_generation_mwh",
        "erco_consumed_co2_intensity_lbs_per_kwh",
    }
    missing = sorted(required.difference(hourly.columns))
    if missing:
        raise ValueError(f"hourly replay is missing evaluation columns: {missing}")

    facility_mwh = hourly["facility_mw"].to_numpy(dtype=float)
    price = hourly["dam_lz_houston_usd_per_mwh"].to_numpy(dtype=float)
    renewable_index = normalized_renewable_index(
        hourly["erco_solar_generation_mwh"].to_numpy(dtype=float),
        hourly["erco_wind_generation_mwh"].to_numpy(dtype=float),
    )
    carbon = hourly[
        "erco_consumed_co2_intensity_lbs_per_kwh"
    ].to_numpy(dtype=float)
    total_power = float(facility_mwh.sum())
    alignment = (
        float(np.dot(facility_mwh, renewable_index) / total_power)
        if total_power > 0.0
        else 0.0
    )
    return EvaluationMetrics(
        cost_usd=float(np.dot(facility_mwh, price)),
        actual_renewable_alignment_index=alignment,
        actual_co2_kg=float(np.dot(facility_mwh * 1_000.0, carbon) * LBS_TO_KG),
    )
