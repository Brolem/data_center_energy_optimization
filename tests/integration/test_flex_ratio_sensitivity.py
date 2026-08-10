from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from dc_energy_opt.experiments.flex_ratio_sensitivity import (
    run_flex_ratio_sensitivity_experiment,
)


class FlexRatioSensitivityExperimentTests(unittest.TestCase):
    def test_full_experiment_uses_two_baselines_and_publishes_summary(
        self,
    ) -> None:
        hourly = pd.DataFrame(
            {
                "day": np.repeat(np.arange(1, 29), 24),
                "hour": np.tile(np.arange(24), 28),
                "avg_cpu": np.full(672, 0.5),
            }
        )
        energy_scenario = pd.DataFrame(
            {
                "timestamp_lst": pd.date_range(
                    "2020-04-30 00:00:00",
                    periods=699,
                    freq="h",
                ),
                "solar_available_mw": np.zeros(699),
                "wind_available_mw": np.zeros(699),
                "tou_period": ["flat"] * 699,
                "electricity_price_cny_per_kwh": np.full(699, 0.4489),
            }
        )

        def fake_solve(
            **kwargs: object,
        ) -> tuple[pd.DataFrame, dict[str, object], pd.DataFrame]:
            case_name = str(kwargs["case_name"])
            flex_ratio = float(kwargs["params"].flex_ratio)
            baseline_costs = {
                "renewables_only": 100.0,
                "renewables_storage": 80.0,
            }
            total_cost = baseline_costs.get(
                case_name,
                100.0 - 50.0 * flex_ratio
                if case_name == "renewables_shift"
                else 80.0 - 40.0 * flex_ratio,
            )
            return (
                pd.DataFrame(),
                {
                    "case": case_name,
                    "status": "optimal",
                    "analysis_operating_cost_cny": total_cost - 1.0,
                    "settlement_tail_operating_cost_cny": 1.0,
                    "operating_cost_cny": total_cost,
                    "total_task_delay_cpu_hours": flex_ratio,
                    "average_flexible_task_delay_h": flex_ratio,
                    "maximum_task_delay_h": 3,
                },
                pd.DataFrame(),
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workload_path = root / "workload.csv"
            energy_path = root / "energy.csv"
            output_dir = root / "sensitivity"
            workload_path.write_text("workload", encoding="utf-8")
            energy_path.write_text("energy", encoding="utf-8")
            with (
                patch(
                    "dc_energy_opt.experiments.flex_ratio_sensitivity."
                    "load_and_prepare",
                    return_value=(pd.DataFrame(), hourly, 8, 28),
                ),
                patch(
                    "dc_energy_opt.experiments.flex_ratio_sensitivity."
                    "load_houston_energy_scenario",
                    return_value=energy_scenario,
                ),
                patch(
                    "dc_energy_opt.experiments.flex_ratio_sensitivity."
                    "run_rolling_day_ahead",
                    side_effect=fake_solve,
                ) as solve,
            ):
                result = run_flex_ratio_sensitivity_experiment(
                    workload_data=workload_path,
                    energy_data=energy_path,
                    output_dir=output_dir,
                    flex_ratios=(0.0, 0.1, 0.2),
                )

            self.assertEqual(len(result.metrics), 6)
            self.assertEqual(
                result.metrics.groupby("scenario", sort=False)[
                    "flex_ratio"
                ].apply(list).to_dict(),
                {
                    "renewables_shift": [0.0, 0.1, 0.2],
                    "joint": [0.0, 0.1, 0.2],
                },
            )
            self.assertEqual(
                [call.kwargs["case_name"] for call in solve.call_args_list],
                [
                    "renewables_only",
                    "renewables_storage",
                    "renewables_shift",
                    "joint",
                    "renewables_shift",
                    "joint",
                ],
            )
            self.assertEqual(
                [
                    "/".join(
                        Path(call.kwargs["model_output_dir"]).parts[-3:]
                    )
                    for call in solve.call_args_list
                ],
                [
                    "models/renewables_shift/ratio_000",
                    "models/joint/ratio_000",
                    "models/renewables_shift/ratio_010",
                    "models/joint/ratio_010",
                    "models/renewables_shift/ratio_020",
                    "models/joint/ratio_020",
                ],
            )
            self.assertEqual(
                sorted(path.name for path in (output_dir / "inputs").iterdir()),
                [
                    "aligned_28d_hourly.csv",
                    "google_2019_28d_5min.csv",
                    "houston_2020_may_hourly.csv",
                ],
            )
            self.assertEqual(
                sorted(path.name for path in (output_dir / "results").iterdir()),
                ["flex_ratio_sensitivity.csv"],
            )
            self.assertEqual(
                sorted(path.name for path in (output_dir / "figures").iterdir()),
                [
                    "flex_ratio_cost_savings.png",
                    "flex_ratio_marginal_savings.png",
                    "flex_ratio_total_cost.png",
                ],
            )
            self.assertTrue((output_dir / "run_metadata.json").is_file())


if __name__ == "__main__":
    unittest.main()
