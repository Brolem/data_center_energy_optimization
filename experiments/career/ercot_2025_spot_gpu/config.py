from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]

ENERGY_COLUMNS = (
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
)
FORECAST_TARGET_COLUMNS = (
    "dam_lz_houston_usd_per_mwh",
    "erco_solar_generation_mwh",
    "erco_wind_generation_mwh",
)

TRAIN_START = "2025-01-01"
TRAIN_END = "2025-06-30"
VALIDATION_START = "2025-07-01"
VALIDATION_END = "2025-07-30"
TEST_START = "2025-08-01"
TEST_END = "2025-08-30"
SETTLEMENT_CLOSURE_DATE = "2025-08-31"

TRAIN_LOCAL_DAYS = 181
TRAIN_HOURS = 4_343
VALIDATION_LOCAL_DAYS = 30
VALIDATION_HOURS = 720
ANALYSIS_LOCAL_DAYS = 30
ANALYSIS_HOURS = 720
SETTLEMENT_CLOSURE_HOURS = 3

SOLAR_SIGNAL_MAX_MWH = 29_503.0
WIND_SIGNAL_MAX_MWH = 28_264.0
REPLAY_START_SECONDS = 7_776_000
REPLAY_STOP_SECONDS = 10_368_000
WORKLOAD_PEAK_PU = 0.60


@dataclass(frozen=True)
class CareerPaths:
    energy_table: Path = (
        PROJECT_ROOT / "data" / "energy" / "ercot_2025_houston_hourly.csv"
    )
    spot_job_table: Path = (
        PROJECT_ROOT
        / "data"
        / "workload"
        / "alibaba_2026_spot_gpu_job_info_df.csv"
    )
    output_directory: Path = (
        PROJECT_ROOT
        / "outputs"
        / "career"
        / "ercot_2025_spot_gpu_prediction_driven_dispatch"
        / "day_ahead"
    )
