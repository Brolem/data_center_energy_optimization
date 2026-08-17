from __future__ import annotations

import unittest

from experiments.paper.ercot_2025_spot_gpu.power import PowerModel
from experiments.paper.ercot_2025_spot_gpu.workload import (
    aggregate_model_capacities,
    normalize_job,
    select_replay_core,
)


class ReplayContractTests(unittest.TestCase):
    def test_normalization_preserves_model_gang_and_hour_semantics(self) -> None:
        spot = normalize_job(
            {
                "job_name": "spot-1",
                "organization": "org-a",
                "job_type": "Spot",
                "gpu_model": "model-a",
                "gpu_request": 2,
                "worker_num": 4,
                "submit_time": 36_001,
                "duration": 7_201,
            },
            completion_slack_hours=3,
        )

        self.assertEqual(spot.gpu_model, "model-a")
        self.assertEqual(spot.gpu_count, 8.0)
        self.assertEqual(spot.release_hour, 10)
        self.assertEqual(spot.required_run_hours, 3)
        self.assertEqual(spot.deadline_hour, 16)

    def test_hp_has_no_invented_deadline(self) -> None:
        hp = normalize_job(
            {
                "job_name": "hp-1",
                "organization": "org-a",
                "job_type": "HP",
                "gpu_model": "model-a",
                "gpu_request": 0.5,
                "worker_num": 2,
                "submit_time": 0,
                "duration": 3_600,
            }
        )

        self.assertEqual(hp.gpu_count, 1.0)
        self.assertIsNone(hp.deadline_hour)

    def test_capacities_sum_node_rows_by_exact_model(self) -> None:
        capacities = aggregate_model_capacities(
            [
                {"gpu_model": "model-a", "gpu_capacity_num": 4},
                {"gpu_model": "model-a", "gpu_capacity_num": 8},
                {"gpu_model": "model-b", "gpu_capacity_num": 1},
            ]
        )

        self.assertEqual(capacities, {"model-a": 12.0, "model-b": 1.0})

    def test_core_selection_is_deterministic_and_excludes_long_spot(self) -> None:
        jobs = [
            normalize_job(
                {
                    "job_name": f"spot-{hour}",
                    "organization": "org-a",
                    "job_type": "Spot",
                    "gpu_model": "model-a",
                    "gpu_request": 1,
                    "worker_num": 1,
                    "submit_time": hour * 3_600,
                    "duration": duration_hours * 3_600,
                }
            )
            for hour, duration_hours in ((0, 1), (1, 1), (2, 1), (3, 4), (4, 4), (4, 169))
        ]

        original = select_replay_core(jobs, core_hours=3, max_duration_hours=168)
        reversed_input = select_replay_core(
            list(reversed(jobs)), core_hours=3, max_duration_hours=168
        )

        self.assertEqual(original.core_start_hour, 0)
        self.assertEqual(original.core_start_hour, reversed_input.core_start_hour)
        self.assertEqual(
            [job.job_id for job in original.spot_jobs],
            [job.job_id for job in reversed_input.spot_jobs],
        )
        self.assertTrue(all(job.required_run_hours <= 168 for job in original.spot_jobs))
        self.assertEqual(original.excluded_spot_over_max_duration_count, 0)

    def test_partial_final_trace_hour_is_not_treated_as_complete(self) -> None:
        jobs = [
            normalize_job(
                {
                    "job_name": f"spot-{hour}",
                    "organization": "org-a",
                    "job_type": "Spot",
                    "gpu_model": "model-a",
                    "gpu_request": 1,
                    "worker_num": 1,
                    "submit_time": hour * 3_600 + (1_800 if hour == 4 else 0),
                    "duration": duration_hours * 3_600,
                }
            )
            for hour, duration_hours in ((0, 1), (1, 1), (2, 1), (3, 4), (4, 100))
        ]

        selection = select_replay_core(jobs, core_hours=3, max_duration_hours=168)

        self.assertEqual(selection.core_start_hour, 0)

    def test_power_is_model_specific_and_scenarios_are_ordered(self) -> None:
        low = PowerModel.low()
        baseline = PowerModel.baseline()
        high = PowerModel.high()
        allocation = {"A10": 2.0, "A100-SXM4-80GB": 1.0}

        expected_baseline_mw = 1.20 * 1.15 * 0.70 * (2 * 150 + 400) / 1_000_000
        self.assertAlmostEqual(baseline.facility_mw(allocation), expected_baseline_mw)
        self.assertLess(low.facility_mw(allocation), baseline.facility_mw(allocation))
        self.assertLess(baseline.facility_mw(allocation), high.facility_mw(allocation))
        with self.assertRaisesRegex(ValueError, "missing power mapping"):
            baseline.facility_mw({"unknown-model": 1.0})


if __name__ == "__main__":
    unittest.main()
