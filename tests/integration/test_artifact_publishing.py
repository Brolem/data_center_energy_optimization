from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from dc_energy_opt.experiments.artifacts import (
    _remove_generated_path,
    staged_run_directory,
)


def _tree_hashes(root: Path) -> dict[str, str]:
    if root.is_file():
        return {".": hashlib.sha256(root.read_bytes()).hexdigest()}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class ArtifactPublishingTests(unittest.TestCase):
    def assert_no_transaction_paths(self, parent: Path, name: str) -> None:
        self.assertEqual(list(parent.glob(f".{name}-staging-*")), [])
        self.assertEqual(list(parent.glob(f".{name}-backup-*")), [])

    def test_layout_is_precreated_and_paths_are_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            final_output_dir = Path(temporary_directory) / "run"
            with staged_run_directory(final_output_dir) as paths:
                self.assertEqual(paths.inputs, paths.root / "inputs")
                self.assertEqual(paths.results, paths.root / "results")
                self.assertEqual(paths.figures, paths.root / "figures")
                self.assertEqual(paths.models, paths.root / "models")
                self.assertEqual(
                    sorted(path.name for path in paths.root.iterdir()),
                    ["figures", "inputs", "models", "results"],
                )
                with self.assertRaises(FrozenInstanceError):
                    paths.root = final_output_dir
                (paths.results / "marker.txt").write_text(
                    "new", encoding="utf-8"
                )

            self.assertEqual(
                (final_output_dir / "results" / "marker.txt").read_text(
                    encoding="utf-8"
                ),
                "new",
            )
            self.assert_no_transaction_paths(
                final_output_dir.parent,
                final_output_dir.name,
            )

    def test_success_replaces_the_complete_previous_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"
            final_output_dir.mkdir()
            (final_output_dir / "old.bin").write_bytes(b"old\x00\xff")

            with staged_run_directory(final_output_dir) as paths:
                (paths.root / "run_metadata.json").write_text(
                    "{}", encoding="utf-8"
                )

            self.assertFalse((final_output_dir / "old.bin").exists())
            self.assertTrue((final_output_dir / "run_metadata.json").is_file())
            self.assertEqual(
                sorted(path.name for path in final_output_dir.iterdir()),
                [
                    "figures",
                    "inputs",
                    "models",
                    "results",
                    "run_metadata.json",
                ],
            )
            self.assert_no_transaction_paths(parent, "run")

    def test_yield_exception_preserves_previous_tree_and_cleans_staging(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"
            (final_output_dir / "nested").mkdir(parents=True)
            (final_output_dir / "nested" / "old.bin").write_bytes(
                b"old\x00\xff"
            )
            before = _tree_hashes(final_output_dir)

            with self.assertRaisesRegex(RuntimeError, "stop"):
                with staged_run_directory(final_output_dir) as paths:
                    (paths.results / "new.txt").write_text(
                        "new", encoding="utf-8"
                    )
                    raise RuntimeError("stop")

            self.assertEqual(_tree_hashes(final_output_dir), before)
            self.assert_no_transaction_paths(parent, "run")

    def test_publish_failure_restores_previous_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"
            final_output_dir.mkdir()
            (final_output_dir / "old.txt").write_text(
                "old", encoding="utf-8"
            )
            before = _tree_hashes(final_output_dir)
            real_replace = os.replace
            replace_count = 0

            def fail_publish(source: Path, target: Path) -> None:
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("injected publish failure")
                real_replace(source, target)

            with (
                patch(
                    "dc_energy_opt.experiments.artifacts.os.replace",
                    side_effect=fail_publish,
                ),
                self.assertRaisesRegex(OSError, "injected publish failure"),
            ):
                with staged_run_directory(final_output_dir) as paths:
                    (paths.results / "new.txt").write_text(
                        "new", encoding="utf-8"
                    )

            self.assertEqual(_tree_hashes(final_output_dir), before)
            self.assert_no_transaction_paths(parent, "run")

    def test_restore_failure_preserves_backup_at_reported_exact_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"
            final_output_dir.mkdir()
            (final_output_dir / "old.txt").write_text(
                "old", encoding="utf-8"
            )
            real_replace = os.replace
            replace_count = 0

            def fail_publish_and_restore(source: Path, target: Path) -> None:
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("injected publish failure")
                if replace_count == 3:
                    raise OSError("injected restore failure")
                real_replace(source, target)

            with (
                patch(
                    "dc_energy_opt.experiments.artifacts.os.replace",
                    side_effect=fail_publish_and_restore,
                ),
                self.assertRaises(RuntimeError) as context,
            ):
                with staged_run_directory(final_output_dir) as paths:
                    (paths.results / "new.txt").write_text(
                        "new", encoding="utf-8"
                    )

            backups = list(parent.glob(".run-backup-*"))
            self.assertEqual(len(backups), 1)
            backup_path = backups[0].resolve()
            message = str(context.exception)
            self.assertIn(str(backup_path), message)
            self.assertIn("injected restore failure", message)
            self.assertEqual(
                (backup_path / "old.txt").read_text(encoding="utf-8"),
                "old",
            )
            self.assertFalse(final_output_dir.exists())
            self.assertEqual(list(parent.glob(".run-staging-*")), [])

    def test_readonly_previous_tree_is_removed_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"
            final_output_dir.mkdir()
            readonly_path = final_output_dir / "readonly.txt"
            readonly_path.write_text("old", encoding="utf-8")
            readonly_path.chmod(stat.S_IREAD)

            try:
                with staged_run_directory(final_output_dir) as paths:
                    (paths.results / "new.txt").write_text(
                        "new", encoding="utf-8"
                    )
                self.assertFalse(readonly_path.exists())
                self.assert_no_transaction_paths(parent, "run")
            finally:
                for path in parent.rglob("*"):
                    if path.is_file():
                        path.chmod(stat.S_IWRITE)

    def test_existing_file_at_final_path_is_replaced_by_run_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"
            final_output_dir.write_bytes(b"old file")

            with staged_run_directory(final_output_dir) as paths:
                (paths.results / "new.txt").write_text(
                    "new", encoding="utf-8"
                )

            self.assertTrue(final_output_dir.is_dir())
            self.assertEqual(
                (final_output_dir / "results" / "new.txt").read_text(
                    encoding="utf-8"
                ),
                "new",
            )
            self.assert_no_transaction_paths(parent, "run")

    def test_publish_failure_without_previous_tree_cleans_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"
            with (
                patch(
                    "dc_energy_opt.experiments.artifacts.os.replace",
                    side_effect=OSError("injected publish failure"),
                ),
                self.assertRaisesRegex(OSError, "injected publish failure"),
            ):
                with staged_run_directory(final_output_dir) as paths:
                    (paths.results / "new.txt").write_text(
                        "new", encoding="utf-8"
                    )

            self.assertFalse(final_output_dir.exists())
            self.assert_no_transaction_paths(parent, "run")

    def test_readonly_staging_file_is_cleaned_after_yield_exception(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"

            with self.assertRaisesRegex(RuntimeError, "stop"):
                with staged_run_directory(final_output_dir) as paths:
                    readonly_path = paths.results / "readonly.txt"
                    readonly_path.write_text("new", encoding="utf-8")
                    readonly_path.chmod(stat.S_IREAD)
                    raise RuntimeError("stop")

            self.assertFalse(final_output_dir.exists())
            self.assert_no_transaction_paths(parent, "run")

    def test_publish_failure_restores_readonly_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"
            final_output_dir.mkdir()
            readonly_path = final_output_dir / "readonly.txt"
            readonly_path.write_text("old", encoding="utf-8")
            readonly_path.chmod(stat.S_IREAD)
            real_replace = os.replace
            replace_count = 0

            def fail_publish(source: Path, target: Path) -> None:
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("injected publish failure")
                real_replace(source, target)

            try:
                with (
                    patch(
                        "dc_energy_opt.experiments.artifacts.os.replace",
                        side_effect=fail_publish,
                    ),
                    self.assertRaisesRegex(
                        OSError, "injected publish failure"
                    ),
                ):
                    with staged_run_directory(final_output_dir) as paths:
                        (paths.results / "new.txt").write_text(
                            "new", encoding="utf-8"
                        )

                self.assertEqual(
                    readonly_path.read_text(encoding="utf-8"),
                    "old",
                )
                self.assert_no_transaction_paths(parent, "run")
            finally:
                if readonly_path.exists():
                    readonly_path.chmod(stat.S_IWRITE)

    def test_backup_cleanup_failure_keeps_backup_and_published_tree(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            final_output_dir = parent / "run"
            final_output_dir.mkdir()
            (final_output_dir / "old.txt").write_text(
                "old", encoding="utf-8"
            )

            with (
                patch(
                    "dc_energy_opt.experiments.artifacts.shutil.rmtree",
                    side_effect=OSError("injected backup cleanup failure"),
                ),
                self.assertRaises(RuntimeError) as context,
            ):
                with staged_run_directory(final_output_dir) as paths:
                    (paths.results / "new.txt").write_text(
                        "new", encoding="utf-8"
                    )

            self.assertIn(
                "injected backup cleanup failure", str(context.exception)
            )
            self.assertEqual(
                (final_output_dir / "results" / "new.txt").read_text(
                    encoding="utf-8"
                ),
                "new",
            )
            backups = list(parent.glob(".run-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                (backups[0] / "old.txt").read_text(encoding="utf-8"),
                "old",
            )

    def test_cleanup_rejects_non_generated_literal_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            protected_path = parent / "protected"
            protected_path.mkdir()
            (protected_path / "marker.txt").write_text(
                "keep", encoding="utf-8"
            )

            with self.assertRaisesRegex(RuntimeError, "事务前缀"):
                _remove_generated_path(
                    protected_path,
                    parent=parent,
                    prefix=".run-staging-",
                )

            self.assertEqual(
                (protected_path / "marker.txt").read_text(encoding="utf-8"),
                "keep",
            )


if __name__ == "__main__":
    unittest.main()
