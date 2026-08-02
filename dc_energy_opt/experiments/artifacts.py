from __future__ import annotations

import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import uuid4


@dataclass(frozen=True)
class RunPaths:
    root: Path
    inputs: Path
    results: Path
    figures: Path
    models: Path


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _validate_generated_path(
    path: Path,
    *,
    parent: Path,
    prefix: str,
) -> Path:
    resolved_parent = parent.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    if resolved_path.parent != resolved_parent:
        raise RuntimeError(
            f"拒绝清理不在输出同级目录中的路径: {resolved_path}"
        )
    if not path.name.startswith(prefix):
        raise RuntimeError(
            f"拒绝清理不带事务前缀 {prefix!r} 的路径: {resolved_path}"
        )
    return resolved_path


def _make_writable_and_retry(
    function: object,
    path: str,
    error_info: object,
) -> None:
    target = Path(path)
    target.chmod(stat.S_IWRITE)
    function(path)


def _remove_generated_path(
    path: Path,
    *,
    parent: Path,
    prefix: str,
) -> None:
    resolved_path = _validate_generated_path(
        path,
        parent=parent,
        prefix=prefix,
    )
    if not _path_exists(resolved_path):
        return
    if resolved_path.is_symlink() or resolved_path.is_file():
        try:
            resolved_path.unlink()
        except PermissionError:
            resolved_path.chmod(stat.S_IWRITE)
            resolved_path.unlink()
        return
    if not resolved_path.is_dir():
        raise RuntimeError(f"拒绝清理未知文件系统对象: {resolved_path}")
    shutil.rmtree(resolved_path, onexc=_make_writable_and_retry)


@contextmanager
def staged_run_directory(final_output_dir: Path) -> Iterator[RunPaths]:
    """Build a complete run tree beside final_output_dir and publish atomically."""
    final_path = Path(final_output_dir).resolve(strict=False)
    parent = final_path.parent
    if final_path == parent:
        raise ValueError("正式输出目录不得为文件系统根目录。")
    parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = parent.resolve(strict=False)
    staging_prefix = f".{final_path.name}-staging-"
    backup_prefix = f".{final_path.name}-backup-"
    staging_path = Path(
        tempfile.mkdtemp(
            prefix=staging_prefix,
            dir=resolved_parent,
        )
    ).resolve(strict=False)
    _validate_generated_path(
        staging_path,
        parent=resolved_parent,
        prefix=staging_prefix,
    )

    paths = RunPaths(
        root=staging_path,
        inputs=staging_path / "inputs",
        results=staging_path / "results",
        figures=staging_path / "figures",
        models=staging_path / "models",
    )
    for directory in (
        paths.inputs,
        paths.results,
        paths.figures,
        paths.models,
    ):
        directory.mkdir()

    backup_path = resolved_parent / f"{backup_prefix}{uuid4().hex}"
    _validate_generated_path(
        backup_path,
        parent=resolved_parent,
        prefix=backup_prefix,
    )
    try:
        yield paths
        if _path_exists(final_path):
            os.replace(final_path, backup_path)
        try:
            os.replace(staging_path, final_path)
        except BaseException as publish_error:
            if _path_exists(backup_path):
                try:
                    os.replace(backup_path, final_path)
                except BaseException as restore_error:
                    raise RuntimeError(
                        "发布失败且旧结果恢复失败；"
                        f"备份保留在 {backup_path.resolve(strict=False)}: "
                        f"{restore_error}"
                    ) from publish_error
            raise
        if _path_exists(backup_path):
            try:
                _remove_generated_path(
                    backup_path,
                    parent=resolved_parent,
                    prefix=backup_prefix,
                )
            except BaseException as cleanup_error:
                raise RuntimeError(
                    "发布成功但备份清理失败；"
                    f"备份保留在 {backup_path.resolve(strict=False)}: "
                    f"{cleanup_error}"
                ) from cleanup_error
    finally:
        if _path_exists(staging_path):
            _remove_generated_path(
                staging_path,
                parent=resolved_parent,
                prefix=staging_prefix,
            )
