from __future__ import annotations

import hashlib
import subprocess
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dc_energy_opt.artifacts import build_run_provenance


class RunProvenanceTests(unittest.TestCase):
    def test_records_utc_revision_and_input_hashes(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workload_path = root / "workload.csv"
            energy_path = root / "energy.csv"
            workload_path.write_bytes(b"workload\n")
            energy_path.write_bytes(b"energy\n")

            with patch(
                "dc_energy_opt.artifacts.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "rev-parse", "HEAD"],
                    returncode=0,
                    stdout="0123456789abcdef\n",
                    stderr="",
                ),
            ):
                provenance = build_run_provenance(
                    input_files={
                        "workload": workload_path,
                        "energy": energy_path,
                    },
                    generated_at_utc=datetime(
                        2026, 8, 11, 12, 30, 45, tzinfo=UTC
                    ),
                )

        self.assertEqual(provenance["run_utc"], "2026-08-11T12:30:45Z")
        self.assertEqual(provenance["git_commit"], "0123456789abcdef")
        self.assertEqual(
            provenance["input_sha256"],
            {
                "energy": hashlib.sha256(b"energy\n").hexdigest(),
                "workload": hashlib.sha256(b"workload\n").hexdigest(),
            },
        )

    def test_records_null_revision_when_git_is_unavailable(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "input.csv"
            path.write_bytes(b"input\n")

            with patch(
                "dc_energy_opt.artifacts.subprocess.run",
                side_effect=OSError("git unavailable"),
            ):
                provenance = build_run_provenance(
                    input_files={"input": path},
                    generated_at_utc=datetime(
                        2026, 8, 11, 0, 0, tzinfo=UTC
                    ),
                )

        self.assertIsNone(provenance["git_commit"])


if __name__ == "__main__":
    unittest.main()
