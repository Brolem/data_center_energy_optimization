from __future__ import annotations

import unittest

from experiments.paper.houston_2020.sensitivity.flex_ratio import (
    build_sensitivity_summary,
)


def _metric(
    case_name: str,
    total_cost: float,
    analysis_cost: float,
    tail_cost: float,
) -> dict[str, object]:
    return {
        "case": case_name,
        "status": "optimal",
        "analysis_operating_cost_cny": analysis_cost,
        "settlement_tail_operating_cost_cny": tail_cost,
        "operating_cost_cny": total_cost,
        "total_task_delay_cpu_hours": 4.0,
        "average_flexible_task_delay_h": 1.0,
        "maximum_task_delay_h": 3,
    }


class FlexRatioSensitivityTests(unittest.TestCase):
    def test_build_sensitivity_summary_uses_total_cost_and_marginal_savings(
        self,
    ) -> None:
        metrics = build_sensitivity_summary(
            baseline_metrics={
                "renewables_shift": _metric(
                    "renewables_only",
                    100.0,
                    90.0,
                    10.0,
                ),
                "joint": _metric(
                    "renewables_storage",
                    80.0,
                    72.0,
                    8.0,
                ),
            },
            solved_metrics={
                "renewables_shift": {
                    0.1: _metric("renewables_shift", 95.0, 86.0, 9.0),
                },
                "joint": {
                    0.1: _metric("joint", 70.0, 63.0, 7.0),
                },
            },
            flex_ratios=(0.0, 0.1),
        )

        shift = metrics.loc[
            (metrics["scenario"] == "renewables_shift")
            & (metrics["flex_ratio"] == 0.1)
        ].iloc[0]
        self.assertEqual(float(shift["operating_cost_cny"]), 95.0)
        self.assertEqual(float(shift["cost_savings_cny"]), 5.0)
        self.assertEqual(float(shift["cost_savings_pct"]), 5.0)
        self.assertEqual(
            float(shift["marginal_cost_savings_cny_per_flex_ratio"]),
            50.0,
        )


if __name__ == "__main__":
    unittest.main()
