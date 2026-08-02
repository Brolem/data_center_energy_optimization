import unittest

import numpy as np
import pandas as pd

from dc_energy_opt.config import Parameters
from dc_energy_opt.optimization.types import (
    PendingFlexibleTask,
    WindowSolveState,
)
from dc_energy_opt.reporting.metrics import (
    COST_COLUMNS,
    summarize_case_metrics,
    summarize_costs,
    summarize_daily_window,
)


CASE_METRIC_KEYS = (
    "case",
    "status",
    "shift_enabled",
    "storage_enabled",
    "renewables_enabled",
    "grid_purchase_cost_cny",
    "solar_om_cost_cny",
    "wind_om_cost_cny",
    "battery_om_cost_cny",
    "battery_degradation_cost_cny",
    "operating_cost_cny",
    "analysis_operating_cost_cny",
    "settlement_tail_operating_cost_cny",
    "analysis_hours",
    "settlement_tail_hours",
    "grid_capacity_mw",
    "grid_purchase_energy_mwh",
    "grid_peak_power_mw",
    "grid_mean_power_mw",
    "grid_binding_hours",
    "grid_minimum_margin_mw",
    "renewable_available_energy_mwh",
    "renewable_used_energy_mwh",
    "renewable_curtailment_energy_mwh",
    "renewable_curtailment_rate_pct",
    "grid_supply_share_pct",
    "solar_supply_share_pct",
    "wind_supply_share_pct",
    "battery_discharge_supply_share_pct",
    "battery_charged_energy_mwh",
    "battery_discharged_energy_mwh",
    "battery_throughput_energy_mwh",
    "battery_equivalent_full_cycles",
    "initial_stored_energy_mwh",
    "final_stored_energy_mwh",
    "soc_cycle_error",
    "max_simultaneous_charge_discharge_mw2",
    "warmup_carry_in_task_cpu_pu_hours",
    "cross_day_task_cpu_pu_hours",
    "total_task_delay_cpu_hours",
    "average_flexible_task_delay_h",
    "maximum_task_delay_h",
    "cpu_conservation_error",
    "power_balance_max_error_mw",
    "rolling_solve_time_s",
    "warmup_solve_time_s",
    "soc_coordination_solve_time_s",
    "solve_time_s",
    "mip_gap",
)


def _metric_hourly_rows() -> pd.DataFrame:
    hours = 27
    return pd.DataFrame(
        {
            "period_role": ["analysis"] * 24 + ["settlement_tail"] * 3,
            "hourly_grid_purchase_cost_cny": [10.0] * hours,
            "hourly_solar_om_cost_cny": [1.0] * hours,
            "hourly_wind_om_cost_cny": [2.0] * hours,
            "hourly_battery_om_cost_cny": [3.0] * hours,
            "hourly_battery_degradation_cost_cny": [4.0] * hours,
            "hourly_operating_cost_cny": [20.0] * hours,
            "solar_available_mw": [2.0] * hours,
            "wind_available_mw": [3.0] * hours,
            "solar_used_mw": [1.0] * hours,
            "wind_used_mw": [2.0] * hours,
            "solar_curtailed_mw": [1.0] * hours,
            "wind_curtailed_mw": [1.0] * hours,
            "grid_power_mw": [4.0] * hours,
            "discharge_mw": [0.5] * hours,
            "charge_mw": [0.25] * hours,
            "dc_power_mw": [7.25] * hours,
            "stored_energy_end_mwh": [1.0] * hours,
            "soc_start": [0.5] * hours,
            "soc_end": [0.5] * hours,
            "cpu_scheduled_pu": [0.6] * hours,
        }
    )


class MetricTests(unittest.TestCase):
    def test_summarize_costs_adds_exact_hourly_components(self) -> None:
        rows = pd.DataFrame(
            {
                "hourly_grid_purchase_cost_cny": [10.0, 20.0],
                "hourly_solar_om_cost_cny": [1.0, 2.0],
                "hourly_wind_om_cost_cny": [3.0, 4.0],
                "hourly_battery_om_cost_cny": [5.0, 6.0],
                "hourly_battery_degradation_cost_cny": [7.0, 8.0],
                "hourly_operating_cost_cny": [26.0, 40.0],
            }
        )

        summary = summarize_costs(rows)

        self.assertEqual(tuple(summary), tuple(COST_COLUMNS))
        self.assertEqual(summary["operating_cost_cny"], 66.0)

    def test_summarize_daily_window_preserves_exact_row(self) -> None:
        result = _metric_hourly_rows()
        carry_in = (PendingFlexibleTask(origin_hour=-1, remaining_cpu_pu=0.3),)
        state = WindowSolveState(
            stored_energy_mwh=1.2,
            pending_flexible_tasks=(
                PendingFlexibleTask(origin_hour=23, remaining_cpu_pu=0.4),
            ),
        )
        window_metrics = {
            "committed_task_delay_cpu_hours": 2.5,
            "committed_maximum_task_delay_h": 3,
        }

        summary = summarize_daily_window(
            case_name="joint",
            day_number=28,
            result=result,
            stored_energy_mwh=1.1,
            state=state,
            committed_energy_mwh=1.2,
            terminal_energy_mwh=1.3,
            initial_energy_mwh=1.0,
            carry_in_tasks=carry_in,
            window_metrics=window_metrics,
            is_final_day=True,
        )

        self.assertEqual(
            summary,
            {
                "case": "joint",
                "day": 28,
                "grid_purchase_cost_cny": 240.0,
                "solar_om_cost_cny": 24.0,
                "wind_om_cost_cny": 48.0,
                "battery_om_cost_cny": 72.0,
                "battery_degradation_cost_cny": 96.0,
                "operating_cost_cny": 480.0,
                "settlement_tail_operating_cost_cny": 60.0,
                "initial_stored_energy_mwh": 1.1,
                "committed_end_stored_energy_mwh": 1.2,
                "coordinated_committed_stored_energy_mwh": 1.2,
                "window_terminal_stored_energy_mwh": 1.3,
                "actual_window_terminal_stored_energy_mwh": 1.0,
                "carry_in_task_cpu_pu_hours": 0.3,
                "carry_out_task_cpu_pu_hours": 0.4,
                "committed_task_delay_cpu_hours": 2.5,
                "committed_maximum_task_delay_h": 3,
            },
        )

    def test_summarize_case_metrics_preserves_keys_formulas_and_types(
        self,
    ) -> None:
        hourly = _metric_hourly_rows()
        rolling_metrics = [
            {
                "status": "optimal",
                "total_task_delay_cpu_hours": 4.0,
                "maximum_task_delay_h": 2,
                "total_cross_day_task_cpu_pu_hours": 0.5,
                "solve_time_s": 1.5,
                "mip_gap": 0.0,
            }
        ]

        metrics = summarize_case_metrics(
            hourly=hourly,
            workload=np.ones(24),
            params=Parameters(),
            case_name="joint",
            enable_shift=True,
            enable_storage=True,
            warmup_carry_in_cpu=0.2,
            warmup_metrics=None,
            coordination_metrics=None,
            rolling_metrics=rolling_metrics,
        )

        self.assertEqual(tuple(metrics), CASE_METRIC_KEYS)
        self.assertIs(type(metrics["analysis_hours"]), int)
        self.assertIs(type(metrics["settlement_tail_hours"]), int)
        self.assertIs(type(metrics["maximum_task_delay_h"]), int)
        self.assertEqual(metrics["operating_cost_cny"], 540.0)
        self.assertEqual(metrics["analysis_operating_cost_cny"], 480.0)
        self.assertEqual(
            metrics["settlement_tail_operating_cost_cny"],
            60.0,
        )
        self.assertAlmostEqual(metrics["grid_minimum_margin_mw"], 2.6)
        self.assertAlmostEqual(metrics["total_task_delay_cpu_hours"], 4.0)
        self.assertAlmostEqual(
            metrics["average_flexible_task_delay_h"],
            4.0 / (0.3 * 24.0 + 0.2),
        )


if __name__ == "__main__":
    unittest.main()
