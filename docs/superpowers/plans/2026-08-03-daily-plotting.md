# Daily Plotting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone command that reads an existing `hourly_dispatch.csv`, validates a requested day, and writes five day-specific plots while replacing the misleading full-height settlement-tail line with a light-gray shaded band.

**Architecture:** Keep all rendering in `dc_energy_opt.reporting.plots`. Add one public `make_daily_plots` entry that selects and reindexes one day, derives exact cost metrics from hourly cost columns, and delegates to the existing renderers with day-specific titles. Keep the new root CLI thin: parse three required arguments, read the CSV once, call the public API, and print the exact daily output directory.

**Tech Stack:** Python 3.13, pandas 3.0.5, NumPy 2.5.1, Pillow 12.3.0, `argparse`, `unittest`.

---

## File map

- Create `plot_day_ahead_day.py`: standalone CSV-to-daily-PNG command.
- Modify `dc_energy_opt/reporting/plots.py`: shaded settlement tail, generalized renderer titles, daily selection/validation/cost aggregation, and `make_daily_plots`.
- Modify `dc_energy_opt/reporting/__init__.py`: public daily plotting export.
- Modify `tests/unit/test_plots.py`: regression and daily API tests.
- Modify `tests/integration/test_cli_entrypoints.py`: standalone command tests.
- Modify `README.md`: user-facing daily command.
- Modify `docs/houston_2020_experiment.md`: exact daily output and day-28 tail accounting.

### Task 1: Replace the misleading settlement-tail line

**Files:**
- Modify: `tests/unit/test_plots.py`
- Modify: `dc_energy_opt/reporting/plots.py:520-548`

- [ ] **Step 1: Write the failing shaded-band regression test**

Add `ImageColor` to the Pillow imports and add this test to `PlotTests`:

```python
def test_settlement_tail_uses_gray_shading_without_purple_line(self) -> None:
    data = pd.DataFrame(
        {
            "hour": np.arange(27, dtype=int),
            "period_role": ["analysis"] * 24 + ["settlement_tail"] * 3,
        }
    )
    image = Image.new("RGB", (140, 110), "#FFFFFF")
    draw = ImageDraw.Draw(image)

    plots._mark_settlement_tail(
        draw,
        data,
        (10, 10, 130, 100),
        0.0,
        26.0,
    )

    pixels = list(image.getdata())
    self.assertIn(ImageColor.getrgb("#E2E8F0"), pixels)
    self.assertNotIn(ImageColor.getrgb("#7C3AED"), pixels)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
conda run -n scip_env python -m unittest tests.unit.test_plots.PlotTests.test_settlement_tail_uses_gray_shading_without_purple_line -v
```

Expected: `FAIL` because the current implementation draws `#7C3AED` and does not draw `#E2E8F0`.

- [ ] **Step 3: Implement the light-gray settlement-tail band**

Replace the vertical-line body in `_mark_settlement_tail` with exact band bounds, background fill, and a neutral label:

```python
    boundary_hour = float(np.min(tail_hours)) - 0.5
    plot_left, plot_top, plot_right, plot_bottom = plot
    tail_left = round(
        plot_left
        + (boundary_hour - x_min)
        / max(x_max - x_min, 1.0)
        * (plot_right - plot_left)
    )
    draw.rectangle(
        (tail_left, plot_top, plot_right, plot_bottom),
        fill="#E2E8F0",
    )
    label = "3 h settlement tail"
    label_width = draw.textlength(label, font=_font(12))
    draw.text(
        (max(tail_left + 4, plot_right - label_width - 4), plot_top + 4),
        label,
        font=_font(12),
        fill=MUTED,
    )
```

Keep the existing early return when no `settlement_tail` rows exist. The renderers already call this helper before drawing data series, so curves remain visible above the band.

- [ ] **Step 4: Run the regression test and plot unit tests**

Run:

```powershell
conda run -n scip_env python -m unittest tests.unit.test_plots -v
```

Expected: all plot unit tests pass.

- [ ] **Step 5: Commit the isolated visual fix**

```powershell
git add -- tests/unit/test_plots.py dc_energy_opt/reporting/plots.py
git commit -m "fix: shade settlement tail in plots"
```

### Task 2: Add the public single-day plotting API

**Files:**
- Modify: `tests/unit/test_plots.py`
- Modify: `dc_energy_opt/reporting/plots.py:607-1170`
- Modify: `dc_energy_opt/reporting/__init__.py`

- [ ] **Step 1: Add exact single-day fixtures and failing API tests**

Extend the existing zero-data helper so each hourly row also has a numeric `day`. Add a helper that builds selected-day inputs with four exact cases:

```python
def _daily_plot_inputs(day_number: int) -> pd.DataFrame:
    row_count = 27 if day_number == 28 else 24
    rows = []
    for case_name in CASE_ORDER:
        for local_hour in range(row_count):
            rows.append(
                {
                    "case": case_name,
                    "day": day_number,
                    "hour": (day_number - 1) * 24 + local_hour,
                    "period_role": (
                        "settlement_tail"
                        if day_number == 28 and local_hour >= 24
                        else "analysis"
                    ),
                    "cpu_arrival_pu": 0.0,
                    "cpu_scheduled_pu": 0.0,
                    "it_power_mw": 0.0,
                    "dc_power_mw": 0.0,
                    "grid_power_mw": 0.0,
                    "solar_available_mw": 0.0,
                    "solar_used_mw": 0.0,
                    "solar_curtailed_mw": 0.0,
                    "wind_available_mw": 0.0,
                    "wind_used_mw": 0.0,
                    "wind_curtailed_mw": 0.0,
                    "charge_mw": 0.0,
                    "discharge_mw": 0.0,
                    "soc_start": 0.5,
                    "soc_end": 0.5,
                    "electricity_price_cny_per_kwh": 0.0,
                    "hourly_grid_purchase_cost_cny": 0.0,
                    "hourly_solar_om_cost_cny": 0.0,
                    "hourly_wind_om_cost_cny": 0.0,
                    "hourly_battery_om_cost_cny": 0.0,
                    "hourly_battery_degradation_cost_cny": 0.0,
                    "hourly_operating_cost_cny": 0.0,
                }
            )
    return pd.DataFrame(rows)
```

Import `make_daily_plots` and add separate tests for day 1, day 28, and invalid inputs:

```python
def test_make_daily_plots_writes_five_day_01_images(self) -> None:
    hourly_results = _daily_plot_inputs(1)
    with tempfile.TemporaryDirectory() as temporary_directory:
        output_root = Path(temporary_directory) / "figures"

        daily_output = make_daily_plots(hourly_results, 1, output_root)

        self.assertEqual(daily_output, output_root / "day_01")
        self.assertEqual(
            sorted(path.name for path in daily_output.glob("*.png")),
            sorted(PLOT_FILENAMES),
        )

def test_make_daily_plots_writes_day_28_with_settlement_tail(self) -> None:
    hourly_results = _daily_plot_inputs(28)
    drawn_headers: list[str] = []
    original_header = plots._draw_header

    def record_header(
        draw: ImageDraw.ImageDraw,
        title: str,
        subtitle: str = plots.SCENARIO_SUBTITLE,
    ) -> None:
        drawn_headers.append(title)
        original_header(draw, title, subtitle)

    with tempfile.TemporaryDirectory() as temporary_directory:
        output_root = Path(temporary_directory) / "figures"
        with patch.object(plots, "_draw_header", new=record_header):
            daily_output = make_daily_plots(
                hourly_results,
                28,
                output_root,
            )

        self.assertEqual(daily_output, output_root / "day_28")
        self.assertEqual(len(list(daily_output.glob("*.png"))), 5)
        self.assertTrue(all("Day 28" in title for title in drawn_headers))

def test_make_daily_plots_rejects_invalid_day_before_writing(self) -> None:
    hourly_results = _daily_plot_inputs(1)
    with tempfile.TemporaryDirectory() as temporary_directory:
        output_root = Path(temporary_directory) / "figures"
        for invalid_day in (0, 29, 1.5, True):
            with self.subTest(invalid_day=invalid_day):
                with self.assertRaises((TypeError, ValueError)):
                    make_daily_plots(
                        hourly_results,
                        invalid_day,
                        output_root,
                    )
                self.assertFalse(output_root.exists())
```

Add malformed-structure subtests that remove `day`, remove `joint`, remove one hour, or change a day-28 tail role; each must raise before the output directory exists.

- [ ] **Step 2: Run the new API tests and verify RED**

Run:

```powershell
conda run -n scip_env python -m unittest tests.unit.test_plots.PlotTests.test_make_daily_plots_writes_five_day_01_images tests.unit.test_plots.PlotTests.test_make_daily_plots_writes_day_28_with_settlement_tail tests.unit.test_plots.PlotTests.test_make_daily_plots_rejects_invalid_day_before_writing -v
```

Expected: import failure because `make_daily_plots` does not exist.

- [ ] **Step 3: Generalize renderer headers without changing full-run output**

Add a required `header_title: str` parameter to these private renderers:

```python
def _draw_day_ahead_power_results(
    hourly_results: pd.DataFrame,
    output_path: Path,
    header_title: str,
) -> None: ...

def _draw_compute_scheduling_results(
    hourly_results: pd.DataFrame,
    output_path: Path,
    header_title: str,
) -> None: ...

def _draw_battery_operation_results(
    hourly_results: pd.DataFrame,
    output_path: Path,
    header_title: str,
) -> None: ...

def _draw_renewable_dispatch_results(
    hourly_results: pd.DataFrame,
    output_path: Path,
    header_title: str,
) -> None: ...

def _draw_cost_comparison(
    metrics: pd.DataFrame,
    output_path: Path,
    header_title: str,
    cost_axis_label: str,
) -> None: ...
```

Replace each hard-coded `_draw_header` title with `header_title`, and replace the cost chart vertical label with `cost_axis_label`. Update `make_plots` to pass the existing titles and the existing `Operating cost (CNY; analysis + settlement tail)` axis text exactly, preserving current behavior.

- [ ] **Step 4: Implement daily selection, validation, and cost aggregation**

Add `day` validation before any output directory is created. Use a private helper with this exact contract:

```python
def _prepare_daily_plot_inputs(
    hourly_results: pd.DataFrame,
    day_number: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
```

The helper must:

1. Reject `bool` and non-`int` values with `TypeError`.
2. Reject integers outside `1..28` with `ValueError`.
3. Require the exact `day` column, numeric integer values, and finite values.
4. Filter `hourly_results["day"] == day_number`.
5. Require all and only `CASE_ORDER`.
6. Require 24 rows per case for days 1–27 and 27 rows per case for day 28.
7. Require roles `analysis × 24` for days 1–27 and `analysis × 24 + settlement_tail × 3` for day 28.
8. Sort each case by original `hour` and replace `hour` with `groupby("case", sort=False).cumcount()` so axes are exactly `0..23` or `0..26`.
9. Build one metric row per exact case using the existing `summarize_costs` function.
10. Run the existing numeric, physical, case, hour, and arrival-consistency validation against the selected rows and derived metrics.

Refactor `_validate_plot_inputs` only enough to accept an exact expected role sequence supplied by `make_plots` or `_prepare_daily_plot_inputs`; do not weaken existing full-run validation.

- [ ] **Step 5: Implement `make_daily_plots` and shared plot-set writing**

Extract a private `_write_plot_set(...)` that receives validated hourly rows, validated metrics, output directory, five exact titles, and the exact cost axis label. Then implement:

```python
def make_daily_plots(
    hourly_results: pd.DataFrame,
    day_number: int,
    output_dir: Path,
) -> Path:
    daily_results, daily_metrics = _prepare_daily_plot_inputs(
        hourly_results,
        day_number,
    )
    daily_output_dir = Path(output_dir) / f"day_{day_number:02d}"
    scope = "24+3 h" if day_number == 28 else "24 h"
    _write_plot_set(
        daily_results,
        daily_metrics,
        daily_output_dir,
        power_title=f"Day {day_number:02d} {scope} Day-Ahead Power Results",
        compute_title=(
            f"Day {day_number:02d} {scope} Day-Ahead Compute Scheduling"
        ),
        battery_title=(
            f"Day {day_number:02d} {scope} Day-Ahead Battery Operation"
        ),
        renewable_title=(
            f"Day {day_number:02d} {scope} Day-Ahead Renewable Dispatch"
        ),
        cost_title=f"Day {day_number:02d} Operating Cost",
        cost_axis_label=(
            "Operating cost (CNY; analysis + settlement tail)"
            if day_number == 28
            else "Operating cost (CNY; analysis)"
        ),
    )
    return daily_output_dir
```

Export it precisely:

```python
from .plots import PLOT_FILENAMES, make_daily_plots, make_plots, software_versions

__all__ = [
    "summarize_costs",
    "summarize_daily_window",
    "summarize_case_metrics",
    "PLOT_FILENAMES",
    "make_plots",
    "make_daily_plots",
    "software_versions",
]
```

- [ ] **Step 6: Run focused and full plot tests**

Run:

```powershell
conda run -n scip_env python -m unittest tests.unit.test_plots -v
```

Expected: all plot tests pass and every generated file retains its existing dimensions and RGB mode.

- [ ] **Step 7: Commit the daily plotting API**

```powershell
git add -- tests/unit/test_plots.py dc_energy_opt/reporting/plots.py dc_energy_opt/reporting/__init__.py
git commit -m "feat: add specified-day plot generation"
```

### Task 3: Add the standalone plotting command

**Files:**
- Create: `plot_day_ahead_day.py`
- Modify: `tests/integration/test_cli_entrypoints.py`

- [ ] **Step 1: Write failing parser and delegation tests**

Import `plot_day_ahead_day` and add tests with these exact expectations:

```python
def test_daily_plot_parser_requires_exact_arguments(self) -> None:
    arguments = plot_day_ahead_day.parse_args(
        [
            "--hourly-dispatch",
            "dispatch.csv",
            "--day",
            "28",
            "--output-dir",
            "figures",
        ]
    )
    self.assertEqual(arguments.hourly_dispatch, Path("dispatch.csv"))
    self.assertEqual(arguments.day, 28)
    self.assertEqual(arguments.output_dir, Path("figures"))

def test_daily_plot_main_reads_once_and_writes_selected_day(self) -> None:
    hourly = pd.DataFrame({"day": [28]})
    with (
        patch("plot_day_ahead_day.pd.read_csv", return_value=hourly) as read_csv,
        patch(
            "plot_day_ahead_day.make_daily_plots",
            return_value=Path("figures/day_28"),
        ) as make_daily,
        patch("pathlib.Path.is_file", return_value=True),
        patch("sys.stdout", new_callable=io.StringIO) as stdout,
    ):
        plot_day_ahead_day.main(
            [
                "--hourly-dispatch",
                "dispatch.csv",
                "--day",
                "28",
                "--output-dir",
                "figures",
            ]
        )

    read_csv.assert_called_once_with(Path("dispatch.csv"))
    make_daily.assert_called_once_with(hourly, 28, Path("figures"))
    self.assertIn("figures\\day_28", stdout.getvalue())
```

Also test that a missing `hourly_dispatch.csv` raises `FileNotFoundError` before `pd.read_csv` is called.

- [ ] **Step 2: Run the command tests and verify RED**

Run:

```powershell
conda run -n scip_env python -m unittest tests.integration.test_cli_entrypoints.CliEntrypointTests.test_daily_plot_parser_requires_exact_arguments tests.integration.test_cli_entrypoints.CliEntrypointTests.test_daily_plot_main_reads_once_and_writes_selected_day -v
```

Expected: import failure because `plot_day_ahead_day.py` does not exist.

- [ ] **Step 3: Implement the thin standalone command**

Create `plot_day_ahead_day.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from dc_energy_opt.reporting import make_daily_plots


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从现有小时调度结果生成指定日期的五张图。",
    )
    parser.add_argument(
        "--hourly-dispatch",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--day",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.hourly_dispatch.is_file():
        raise FileNotFoundError(
            f"hourly_dispatch.csv 不存在: {args.hourly_dispatch}"
        )
    hourly_results = pd.read_csv(args.hourly_dispatch)
    daily_output_dir = make_daily_plots(
        hourly_results,
        args.day,
        args.output_dir,
    )
    print(f"Daily plots written to: {daily_output_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the complete CLI test module**

Run:

```powershell
conda run -n scip_env python -m unittest tests.integration.test_cli_entrypoints -v
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit the standalone command**

```powershell
git add -- plot_day_ahead_day.py tests/integration/test_cli_entrypoints.py
git commit -m "feat: add daily plot command"
```

### Task 4: Document and verify the completed workflow

**Files:**
- Modify: `README.md`
- Modify: `docs/houston_2020_experiment.md`

- [ ] **Step 1: Add the exact user command and output tree**

Document this command in both files:

```powershell
python plot_day_ahead_day.py `
  --hourly-dispatch outputs/houston_2020_main/results/hourly_dispatch.csv `
  --day 28 `
  --output-dir outputs/houston_2020_main/figures
```

Document that days 1–27 contain 24 hours, day 28 contains 24 analysis hours plus a three-hour light-gray settlement-tail band, and each `figures/day_XX/` directory contains the five exact `PLOT_FILENAMES`.

- [ ] **Step 2: Run the standalone command against the committed output**

Run:

```powershell
conda run -n scip_env python plot_day_ahead_day.py --hourly-dispatch outputs/houston_2020_main/results/hourly_dispatch.csv --day 28 --output-dir outputs/houston_2020_main/figures
```

Expected: prints `Daily plots written to: outputs\houston_2020_main\figures\day_28` and writes five valid PNG files.

- [ ] **Step 3: Visually inspect all five day-28 images**

Open every PNG in `outputs/houston_2020_main/figures/day_28/`. Confirm titles contain `Day 28`; the four time-series plots use hours `0..26`; the final three hours have a light-gray band; no full-height purple settlement marker remains; the cost plot includes the tail cost.

- [ ] **Step 4: Run the full formal suite**

Run:

```powershell
conda run -n scip_env python -m unittest discover -s tests -t . -v
```

Expected: all runnable formal tests pass; only environment-dependent symbolic-link tests may report `skipped` for the already documented Windows privilege restriction.

- [ ] **Step 5: Run the archive suite**

Run:

```powershell
conda run -n scip_env python -m unittest discover -s archive/legacy_phoenix/tests -t . -v
```

Expected: all 11 archive tests pass.

- [ ] **Step 6: Run repository hygiene checks**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intentional implementation and documentation changes are present before the final documentation commit.

- [ ] **Step 7: Commit documentation**

```powershell
git add -- README.md docs/houston_2020_experiment.md
git commit -m "docs: explain specified-day plotting"
```

- [ ] **Step 8: Final verification after all commits**

Run the formal suite, archive suite, `git diff --check`, and `git status --short` once more. Record exact test counts, skipped tests, generated daily output path, and final commit identifiers in the handoff.
