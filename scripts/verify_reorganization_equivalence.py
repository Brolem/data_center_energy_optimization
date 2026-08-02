from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype


RESULT_FILENAMES = {
    "legacy": {
        "hourly": "hourly_case_results.csv",
        "daily": "daily_case_metrics.csv",
        "case": "case_metrics.csv",
    },
    "current": {
        "hourly": "hourly_dispatch.csv",
        "daily": "daily_metrics.csv",
        "case": "case_metrics.csv",
    },
}

TIMING_COLUMNS = {
    "rolling_solve_time_s",
    "warmup_solve_time_s",
    "soc_coordination_solve_time_s",
    "solve_time_s",
}

DEFAULT_ATOL = 1e-9


class EquivalenceError(ValueError):
    """Raised when two result sets do not satisfy the equivalence contract."""


def _load_tables(directory: Path, layout: str) -> dict[str, pd.DataFrame]:
    return {
        table_name: pd.read_csv(directory / filename)
        for table_name, filename in RESULT_FILENAMES[layout].items()
    }


def _validate_timing_column(
    values: pd.Series,
    *,
    table_name: str,
    column_name: str,
    side: str,
) -> None:
    if not is_numeric_dtype(values.dtype):
        raise EquivalenceError(
            f"{table_name}.{column_name}: {side}计时字段不是数值类型"
        )
    numeric_values = values.to_numpy(dtype=float)
    if not np.isfinite(numeric_values).all() or (numeric_values < 0.0).any():
        raise EquivalenceError(
            f"{table_name}.{column_name}: {side}计时字段必须有限且非负"
        )


def _compare_table(
    reference: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    table_name: str,
    atol: float,
) -> dict[str, int | float]:
    if list(reference.columns) != list(actual.columns):
        raise EquivalenceError(f"{table_name}: 列名或列顺序不一致")
    if len(reference) != len(actual):
        raise EquivalenceError(
            f"{table_name}: 行数不一致，reference={len(reference)}，actual={len(actual)}"
        )

    max_abs_diff = 0.0
    for column_name in reference.columns:
        reference_values = reference[column_name]
        actual_values = actual[column_name]

        if column_name in TIMING_COLUMNS:
            _validate_timing_column(
                reference_values,
                table_name=table_name,
                column_name=column_name,
                side="reference",
            )
            _validate_timing_column(
                actual_values,
                table_name=table_name,
                column_name=column_name,
                side="actual",
            )
            continue

        reference_is_numeric = is_numeric_dtype(reference_values.dtype)
        actual_is_numeric = is_numeric_dtype(actual_values.dtype)
        reference_is_boolean = reference_values.dtype == bool
        actual_is_boolean = actual_values.dtype == bool
        if (
            reference_is_numeric
            and actual_is_numeric
            and not reference_is_boolean
            and not actual_is_boolean
        ):
            reference_array = reference_values.to_numpy(dtype=float)
            actual_array = actual_values.to_numpy(dtype=float)
            if not np.allclose(
                reference_array,
                actual_array,
                rtol=0.0,
                atol=atol,
                equal_nan=True,
            ):
                finite_differences = np.abs(reference_array - actual_array)
                observed = float(np.nanmax(finite_differences))
                raise EquivalenceError(
                    f"{table_name}.{column_name}: 数值差超过绝对容差 {atol}，"
                    f"最大绝对差={observed}"
                )
            finite_differences = np.abs(reference_array - actual_array)
            if finite_differences.size:
                column_max = float(np.nanmax(finite_differences))
                if np.isfinite(column_max):
                    max_abs_diff = max(max_abs_diff, column_max)
            continue

        if reference_values.dtype != actual_values.dtype or not reference_values.equals(
            actual_values
        ):
            raise EquivalenceError(
                f"{table_name}.{column_name}: 文本或布尔值不一致"
            )

    return {"rows": len(reference), "max_abs_diff": max_abs_diff}


def compare_result_sets(
    *,
    reference_dir: Path,
    actual_dir: Path,
    reference_layout: str,
    actual_layout: str,
    atol: float = DEFAULT_ATOL,
) -> dict[str, object]:
    reference_tables = _load_tables(reference_dir, reference_layout)
    actual_tables = _load_tables(actual_dir, actual_layout)
    comparisons = {
        table_name: _compare_table(
            reference_tables[table_name],
            actual_tables[table_name],
            table_name=table_name,
            atol=atol,
        )
        for table_name in ("hourly", "daily", "case")
    }
    return {
        "equivalent": True,
        "absolute_tolerance": atol,
        "reference_layout": reference_layout,
        "actual_layout": actual_layout,
        "tables": comparisons,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="逐列验证仓库重组前后的三张核心结果表数值等价",
    )
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--actual-dir", type=Path, required=True)
    parser.add_argument(
        "--reference-layout",
        choices=tuple(RESULT_FILENAMES),
        default="legacy",
    )
    parser.add_argument(
        "--actual-layout",
        choices=tuple(RESULT_FILENAMES),
        default="current",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = compare_result_sets(
            reference_dir=args.reference_dir,
            actual_dir=args.actual_dir,
            reference_layout=args.reference_layout,
            actual_layout=args.actual_layout,
        )
    except (EquivalenceError, FileNotFoundError, pd.errors.ParserError) as error:
        print(f"等价验证失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
