from __future__ import annotations

import numpy as np
import pandas as pd

from dc_energy_opt.config import Parameters

from .rolling import MARKET_ENERGY_COLUMNS


_PLANNED_COLUMNS = (
    "timestamp_utc",
    "workload_scheduled_pu",
    "dc_power_mw",
    "charge_mw",
    "discharge_mw",
    "solar_used_mw",
    "wind_used_mw",
)
_GRID_BALANCE_TOLERANCE_MW = 1e-5


def _validated_actual_energy(actual_energy: pd.DataFrame) -> pd.DataFrame:
    if tuple(actual_energy.columns) != MARKET_ENERGY_COLUMNS:
        raise ValueError("实际市场能源字段顺序不符合正式契约。")
    checked = actual_energy.copy()
    timestamps = pd.to_datetime(
        checked["timestamp_utc"], format="%Y-%m-%dT%H:%M:%SZ", errors="coerce"
    )
    if timestamps.isna().any() or timestamps.duplicated().any():
        raise ValueError("实际 timestamp_utc 必须可解析且不重复。")
    checked["timestamp_utc"] = timestamps
    for column, allow_negative in (
        ("price_usd_per_mwh", True),
        ("solar_available_mw", False),
        ("wind_available_mw", False),
    ):
        values = pd.to_numeric(checked[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"{column} 必须为有限数值。")
        if not allow_negative and (values < 0.0).any():
            raise ValueError(f"{column} 必须为非负数值。")
        checked[column] = values
    return checked


def settle_schedule(
    *,
    planned_schedule: pd.DataFrame,
    actual_energy: pd.DataFrame,
    params: Parameters,
) -> pd.DataFrame:
    """Settle fixed planned actions against observed market signals."""
    if any(column not in planned_schedule for column in _PLANNED_COLUMNS):
        raise ValueError("计划调度缺少事后结算所需字段。")
    actual = _validated_actual_energy(actual_energy)
    planned = planned_schedule.copy()
    planned_timestamps = pd.to_datetime(planned["timestamp_utc"], errors="coerce")
    if len(planned) != len(actual) or not planned_timestamps.reset_index(drop=True).equals(
        actual["timestamp_utc"].reset_index(drop=True)
    ):
        raise ValueError("计划调度与实际能源必须具有相同的时间索引。")
    result = planned.copy()
    result["actual_price_usd_per_mwh"] = actual["price_usd_per_mwh"].to_numpy(dtype=float)
    result["actual_solar_available_mw"] = actual["solar_available_mw"].to_numpy(dtype=float)
    result["actual_wind_available_mw"] = actual["wind_available_mw"].to_numpy(dtype=float)
    result["actual_solar_used_mw"] = np.minimum(
        result["solar_used_mw"].to_numpy(dtype=float),
        result["actual_solar_available_mw"].to_numpy(dtype=float),
    )
    result["actual_wind_used_mw"] = np.minimum(
        result["wind_used_mw"].to_numpy(dtype=float),
        result["actual_wind_available_mw"].to_numpy(dtype=float),
    )
    result["actual_solar_curtailed_mw"] = (
        result["actual_solar_available_mw"] - result["actual_solar_used_mw"]
    )
    result["actual_wind_curtailed_mw"] = (
        result["actual_wind_available_mw"] - result["actual_wind_used_mw"]
    )
    result["actual_grid_power_mw"] = (
        result["dc_power_mw"]
        + result["charge_mw"]
        - result["discharge_mw"]
        - result["actual_solar_used_mw"]
        - result["actual_wind_used_mw"]
    )
    if (result["actual_grid_power_mw"] < -_GRID_BALANCE_TOLERANCE_MW).any():
        minimum_grid_power = float(result["actual_grid_power_mw"].min())
        raise RuntimeError(
            "固定计划在实际能源下产生负购电功率: "
            f"最小值={minimum_grid_power:.12g} MW。"
        )
    result["actual_grid_power_mw"] = result["actual_grid_power_mw"].clip(lower=0.0)
    result["actual_grid_settlement_usd"] = (
        result["actual_price_usd_per_mwh"]
        * result["actual_grid_power_mw"]
        * params.time_step_h
    )
    return result


def build_decision_metrics(
    *,
    settlements_by_case: dict[str, pd.DataFrame],
    daily_metrics_by_case: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Summarize actual settlements and regret against the oracle schedule."""
    if "oracle_actual" not in settlements_by_case:
        raise ValueError("决策指标必须包含 oracle_actual 结算结果。")
    rows: list[dict[str, object]] = []
    for case_name, settlement in settlements_by_case.items():
        if case_name not in daily_metrics_by_case:
            raise ValueError(f"{case_name} 缺少逐日调度指标。")
        daily = daily_metrics_by_case[case_name]
        required_daily_columns = (
            "total_work_delay_pu_hours",
            "flexible_work_pu_hours",
            "maximum_work_delay_h",
        )
        if any(column not in daily for column in required_daily_columns):
            raise ValueError(f"{case_name} 逐日指标不完整。")
        required_settlement_columns = (
            "actual_grid_settlement_usd",
            "actual_grid_power_mw",
            "actual_solar_curtailed_mw",
            "actual_wind_curtailed_mw",
            "charge_mw",
            "discharge_mw",
            "workload_arrival_pu",
            "workload_scheduled_pu",
        )
        if any(column not in settlement for column in required_settlement_columns):
            raise ValueError(f"{case_name} 结算结果不完整。")
        arrived_work = float(settlement["workload_arrival_pu"].sum())
        scheduled_work = float(settlement["workload_scheduled_pu"].sum())
        flexible_work = float(daily["flexible_work_pu_hours"].sum())
        total_delay = float(daily["total_work_delay_pu_hours"].sum())
        rows.append(
            {
                "case": case_name,
                "actual_grid_settlement_usd": float(
                    settlement["actual_grid_settlement_usd"].sum()
                ),
                "actual_grid_purchase_energy_mwh": float(
                    settlement["actual_grid_power_mw"].sum()
                ),
                "actual_renewable_curtailment_energy_mwh": float(
                    (
                        settlement["actual_solar_curtailed_mw"]
                        + settlement["actual_wind_curtailed_mw"]
                    ).sum()
                ),
                "battery_charged_energy_mwh": float(settlement["charge_mw"].sum()),
                "battery_discharged_energy_mwh": float(
                    settlement["discharge_mw"].sum()
                ),
                "spot_work_arrived_pu_hours": arrived_work,
                "spot_work_scheduled_pu_hours": scheduled_work,
                "spot_work_completion_rate": (
                    min(1.0, scheduled_work / arrived_work)
                    if arrived_work > 0.0
                    else 1.0
                ),
                "average_flexible_work_delay_h": (
                    total_delay / flexible_work if flexible_work > 0.0 else 0.0
                ),
                "maximum_work_delay_h": float(daily["maximum_work_delay_h"].max()),
            }
        )
    metrics = pd.DataFrame(rows)
    oracle_settlement = float(
        metrics.loc[
            metrics["case"] == "oracle_actual", "actual_grid_settlement_usd"
        ].iloc[0]
    )
    metrics["decision_regret_usd"] = (
        metrics["actual_grid_settlement_usd"] - oracle_settlement
    )
    return metrics
