from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from experiments.career.ercot_2025_spot_gpu.config import (
    ANALYSIS_HOURS,
    REPLAY_START_SECONDS,
    REPLAY_STOP_SECONDS,
    WORKLOAD_PEAK_PU,
)
from experiments.career.ercot_2025_spot_gpu.replay import (
    JOB_COLUMNS,
    build_spot_replay,
)


def _job_row(
    *,
    job_name: str,
    job_type: str,
    submit_time: int,
    gpu_request: float,
    worker_num: int,
    duration: int,
) -> dict[str, object]:
    return {
        "job_name": job_name,
        "organization": "org",
        "gpu_model": "model",
        "cpu_request": 1.0,
        "gpu_request": gpu_request,
        "worker_num": worker_num,
        "submit_time": submit_time,
        "duration": duration,
        "job_type": job_type,
    }


class SpotReplayTests(unittest.TestCase):
    def test_builds_fixed_length_replay_with_half_open_time_interval(self) -> None:
        jobs = pd.DataFrame(
            [
                _job_row(
                    job_name="first",
                    job_type="Spot",
                    submit_time=REPLAY_START_SECONDS,
                    gpu_request=2.0,
                    worker_num=3,
                    duration=1_800,
                ),
                _job_row(
                    job_name="same_hour",
                    job_type="Spot",
                    submit_time=REPLAY_START_SECONDS + 3_599,
                    gpu_request=4.0,
                    worker_num=1,
                    duration=3_600,
                ),
                _job_row(
                    job_name="next_hour",
                    job_type="Spot",
                    submit_time=REPLAY_START_SECONDS + 3_600,
                    gpu_request=1.0,
                    worker_num=2,
                    duration=3_600,
                ),
                _job_row(
                    job_name="stop_boundary",
                    job_type="Spot",
                    submit_time=REPLAY_STOP_SECONDS,
                    gpu_request=8.0,
                    worker_num=8,
                    duration=3_600,
                ),
                _job_row(
                    job_name="non_spot",
                    job_type="HP",
                    submit_time=REPLAY_START_SECONDS,
                    gpu_request=8.0,
                    worker_num=8,
                    duration=3_600,
                ),
            ],
            columns=JOB_COLUMNS,
        )

        replay = build_spot_replay(jobs)

        self.assertEqual(len(replay.hourly), ANALYSIS_HOURS)
        self.assertEqual(replay.spot_job_count, 3)
        self.assertEqual(replay.hourly.loc[0, "spot_job_count"], 2)
        self.assertEqual(replay.hourly.loc[1, "spot_job_count"], 1)
        self.assertEqual(replay.hourly.loc[2, "spot_job_count"], 0)
        self.assertAlmostEqual(replay.hourly.loc[0, "hourly_gpu_hour_work"], 7.0)
        self.assertAlmostEqual(replay.hourly.loc[1, "hourly_gpu_hour_work"], 2.0)
        self.assertAlmostEqual(replay.hourly.loc[0, "workload_arrival_pu"], WORKLOAD_PEAK_PU)
        self.assertAlmostEqual(
            replay.hourly.loc[1, "workload_arrival_pu"],
            WORKLOAD_PEAK_PU * 2.0 / 7.0,
        )

    def test_rejects_reordered_job_columns(self) -> None:
        jobs = pd.DataFrame(
            [
                _job_row(
                    job_name="first",
                    job_type="Spot",
                    submit_time=REPLAY_START_SECONDS,
                    gpu_request=1.0,
                    worker_num=1,
                    duration=3_600,
                )
            ],
            columns=JOB_COLUMNS,
        )

        with self.assertRaisesRegex(ValueError, "字段顺序"):
            build_spot_replay(jobs.loc[:, list(reversed(JOB_COLUMNS))])

    def test_rejects_zero_peak_spot_work(self) -> None:
        jobs = pd.DataFrame(
            [
                _job_row(
                    job_name="zero",
                    job_type="Spot",
                    submit_time=REPLAY_START_SECONDS,
                    gpu_request=1.0,
                    worker_num=1,
                    duration=0,
                )
            ],
            columns=JOB_COLUMNS,
        )

        with self.assertRaisesRegex(ValueError, "峰值"):
            build_spot_replay(jobs)


if __name__ == "__main__":
    unittest.main()
