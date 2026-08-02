import hashlib
import unittest
from pathlib import Path


class WorkloadDataTests(unittest.TestCase):
    def test_committed_google_file_preserves_raw_sha256(self) -> None:
        path = Path("data/workload/google_2019_28d_5min.csv")

        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            "3F2A240BCBCC97FE74D3609381029C03AAD97D4ADF28B753D2B058CBD448D20D",
        )

    def test_committed_google_file_aggregates_to_672_hours(self) -> None:
        from dc_energy_opt.data.workload import load_and_prepare

        raw, hourly, representative_day, stress_day = load_and_prepare(
            Path("data/workload/google_2019_28d_5min.csv")
        )

        self.assertEqual(len(raw), 8064)
        self.assertEqual(len(hourly), 672)
        self.assertEqual(representative_day, 8)
        self.assertEqual(stress_day, 28)
