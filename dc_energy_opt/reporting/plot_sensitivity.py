from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from .plot_shared import (
    BACKGROUND,
    CASE_COLORS,
    CASE_LABELS,
    GRID,
    MUTED,
    PANEL,
    TEXT,
    _draw_dashed_line,
    _draw_header,
    _draw_legend,
    _draw_vertical_text,
    _font,
    _tick_label,
)

FLEX_RATIO_SCENARIOS = ("renewables_shift", "joint")
FLEX_RATIO_SENSITIVITY_COLUMNS = (
    "scenario",
    "baseline_case",
    "flex_ratio",
    "status",
    "analysis_operating_cost_cny",
    "settlement_tail_operating_cost_cny",
    "operating_cost_cny",
    "baseline_operating_cost_cny",
    "cost_savings_cny",
    "cost_savings_pct",
    "marginal_cost_savings_cny_per_flex_ratio",
    "total_task_delay_cpu_hours",
    "average_flexible_task_delay_h",
    "maximum_task_delay_h",
    "saturation_onset",
)
FLEX_RATIO_PLOT_FILENAMES = (
    "flex_ratio_total_cost.png",
    "flex_ratio_cost_savings.png",
    "flex_ratio_marginal_savings.png",
)
STORAGE_SCALE_SENSITIVITY_COLUMNS = (
    "storage_scale",
    "battery_energy_mwh",
    "battery_power_mw",
    "renewables_storage_cost_cny",
    "joint_cost_cny",
    "no_storage_shift_savings_cny",
    "storage_shift_savings_cny",
)
STORAGE_SCALE_PLOT_FILENAMES = (
    "storage_scale_total_cost.png",
    "storage_scale_shift_value.png",
)
STORAGE_ENERGY_POWER_PLOT_FILENAMES = (
    "storage_energy_power_joint_cost.png",
    "storage_energy_power_shift_effect.png",
)


def _prepare_flex_ratio_sensitivity_inputs(
    sensitivity_metrics: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], tuple[float, ...]]:
    missing_columns = [
        column
        for column in FLEX_RATIO_SENSITIVITY_COLUMNS
        if column not in sensitivity_metrics.columns
    ]
    if missing_columns:
        raise ValueError(
            "sensitivity_metrics missing required columns: "
            f"{', '.join(missing_columns)}"
        )
    numeric_columns = (
        "flex_ratio",
        "analysis_operating_cost_cny",
        "settlement_tail_operating_cost_cny",
        "operating_cost_cny",
        "baseline_operating_cost_cny",
        "cost_savings_cny",
        "cost_savings_pct",
        "total_task_delay_cpu_hours",
        "average_flexible_task_delay_h",
        "maximum_task_delay_h",
    )
    for column in numeric_columns:
        if not pd.api.types.is_numeric_dtype(sensitivity_metrics[column]):
            raise ValueError(
                f"sensitivity_metrics numeric column {column} must be numeric"
            )
        values = sensitivity_metrics[column].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(
                f"sensitivity_metrics numeric column {column} contains "
                "non-finite values"
            )
    if not pd.api.types.is_numeric_dtype(
        sensitivity_metrics["marginal_cost_savings_cny_per_flex_ratio"]
    ):
        raise ValueError(
            "sensitivity_metrics numeric column "
            "marginal_cost_savings_cny_per_flex_ratio must be numeric"
        )
    if not pd.api.types.is_numeric_dtype(sensitivity_metrics["saturation_onset"]):
        raise ValueError(
            "sensitivity_metrics numeric column saturation_onset must be numeric"
        )

    actual_scenarios = sensitivity_metrics["scenario"].drop_duplicates().tolist()
    if set(actual_scenarios) != set(FLEX_RATIO_SCENARIOS):
        raise ValueError(
            "sensitivity_metrics scenario set invalid: "
            f"found={actual_scenarios}"
        )
    rows_by_scenario: dict[str, pd.DataFrame] = {}
    expected_ratios: tuple[float, ...] | None = None
    for scenario in FLEX_RATIO_SCENARIOS:
        rows = (
            sensitivity_metrics.loc[
                sensitivity_metrics["scenario"] == scenario
            ]
            .sort_values("flex_ratio")
            .reset_index(drop=True)
        )
        if rows.empty or not rows["flex_ratio"].is_unique:
            raise ValueError(
                f"sensitivity_metrics scenario {scenario} flex_ratio invalid"
            )
        ratios = tuple(rows["flex_ratio"].to_numpy(dtype=float).tolist())
        if ratios[0] != 0.0 or any(
            not 0.0 <= ratio <= 1.0 for ratio in ratios
        ):
            raise ValueError(
                f"sensitivity_metrics scenario {scenario} flex_ratio invalid"
            )
        if tuple(sorted(ratios)) != ratios:
            raise ValueError(
                f"sensitivity_metrics scenario {scenario} flex_ratio invalid"
            )
        if expected_ratios is None:
            expected_ratios = ratios
        elif ratios != expected_ratios:
            raise ValueError(
                "sensitivity_metrics scenarios must contain identical flex_ratio values"
            )
        if not rows["status"].isin(("optimal", "gaplimit")).all():
            raise ValueError(
                f"sensitivity_metrics scenario {scenario} contains unaccepted status"
            )
        expected_cost = (
            rows["analysis_operating_cost_cny"]
            + rows["settlement_tail_operating_cost_cny"]
        )
        if not np.isclose(
            rows["operating_cost_cny"].to_numpy(dtype=float),
            expected_cost.to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-7,
        ).all():
            raise ValueError(
                "sensitivity_metrics operating cost identity invalid"
            )
        marginal = rows["marginal_cost_savings_cny_per_flex_ratio"]
        if not pd.isna(marginal.iloc[0]) or marginal.iloc[1:].isna().any():
            raise ValueError(
                "sensitivity_metrics marginal savings values invalid"
            )
        onset = rows["saturation_onset"].dropna().to_numpy(dtype=float)
        if len(onset) and (
            not np.isfinite(onset).all()
            or len(np.unique(onset)) != 1
            or float(onset[0]) not in ratios
        ):
            raise ValueError(
                "sensitivity_metrics saturation_onset values invalid"
            )
        rows_by_scenario[scenario] = rows

    assert expected_ratios is not None
    return rows_by_scenario, expected_ratios


def _flex_ratio_y_bounds(
    values: np.ndarray,
    *,
    include_zero: bool,
) -> tuple[float, float]:
    finite_values = values[np.isfinite(values)]
    if len(finite_values) == 0:
        return -1.0, 1.0
    minimum = float(np.min(finite_values))
    maximum = float(np.max(finite_values))
    if include_zero:
        minimum = min(minimum, 0.0)
        maximum = max(maximum, 0.0)
    padding = max((maximum - minimum) * 0.10, abs(maximum) * 0.03, 1.0)
    return minimum - padding, maximum + padding


def _draw_flex_ratio_axes(
    draw: ImageDraw.ImageDraw,
    plot: tuple[int, int, int, int],
    *,
    y_min: float,
    y_max: float,
    panel_title: str,
    y_label: str,
) -> None:
    plot_left, plot_top, plot_right, plot_bottom = plot
    draw.text(
        (plot_left, plot_top - 35),
        panel_title,
        font=_font(16, bold=True),
        fill=TEXT,
    )
    draw.rectangle(plot, outline=MUTED, width=1)
    for index in range(6):
        fraction = index / 5.0
        y = round(plot_bottom - fraction * (plot_bottom - plot_top))
        value = y_min + fraction * (y_max - y_min)
        draw.line((plot_left, y, plot_right, y), fill=GRID, width=1)
        label = _tick_label(value)
        label_width = draw.textlength(label, font=_font(13))
        draw.text(
            (plot_left - label_width - 10, y - 8),
            label,
            font=_font(13),
            fill=MUTED,
        )
    for percentage in (0, 20, 40, 60, 80, 100):
        x = round(
            plot_left + percentage / 100.0 * (plot_right - plot_left)
        )
        draw.line((x, plot_bottom, x, plot_bottom + 5), fill=MUTED, width=1)
        label = f"{percentage}%"
        label_width = draw.textlength(label, font=_font(13))
        draw.text(
            (x - label_width / 2, plot_bottom + 10),
            label,
            font=_font(13),
            fill=MUTED,
        )
    _draw_vertical_text(
        draw._image,
        y_label,
        plot_left - 138,
        (plot_top + plot_bottom) // 2,
    )


def _flex_ratio_coordinates(
    ratios: tuple[float, ...],
    values: np.ndarray,
    plot: tuple[int, int, int, int],
    y_min: float,
    y_max: float,
) -> list[tuple[int, int]]:
    plot_left, plot_top, plot_right, plot_bottom = plot
    height = plot_bottom - plot_top
    return [
        (
            round(plot_left + ratio * (plot_right - plot_left)),
            round(
                plot_bottom
                - (value - y_min) / (y_max - y_min) * height
            ),
        )
        for ratio, value in zip(ratios, values, strict=True)
    ]


def _draw_flex_ratio_line(
    draw: ImageDraw.ImageDraw,
    ratios: tuple[float, ...],
    values: np.ndarray,
    plot: tuple[int, int, int, int],
    y_min: float,
    y_max: float,
    color: str,
) -> None:
    points = _flex_ratio_coordinates(
        ratios,
        values,
        plot,
        y_min,
        y_max,
    )
    if len(points) > 1:
        draw.line(points, fill=color, width=4, joint="curve")
    for x, y in points:
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)


def _draw_flex_ratio_zero_line(
    draw: ImageDraw.ImageDraw,
    plot: tuple[int, int, int, int],
    y_min: float,
    y_max: float,
) -> None:
    if not y_min <= 0.0 <= y_max:
        return
    _, plot_top, _, plot_bottom = plot
    y = round(
        plot_bottom - (0.0 - y_min) / (y_max - y_min) * (plot_bottom - plot_top)
    )
    draw.line((plot[0], y, plot[2], y), fill=TEXT, width=2)


def _draw_flex_ratio_saturation_mark(
    draw: ImageDraw.ImageDraw,
    rows_by_scenario: dict[str, pd.DataFrame],
    plot: tuple[int, int, int, int],
) -> None:
    plot_left, plot_top, plot_right, plot_bottom = plot
    for scenario in FLEX_RATIO_SCENARIOS:
        onset = rows_by_scenario[scenario]["saturation_onset"].dropna()
        if onset.empty:
            continue
        x = round(
            plot_left
            + float(onset.iloc[0]) * (plot_right - plot_left)
        )
        _draw_dashed_line(
            draw,
            [(x, plot_top), (x, plot_bottom)],
            CASE_COLORS[scenario],
            width=2,
        )


def _draw_flex_ratio_total_cost_plot(
    rows_by_scenario: dict[str, pd.DataFrame],
    ratios: tuple[float, ...],
    output_path: Path,
) -> None:
    values = np.concatenate(
        [
            rows_by_scenario[scenario]["operating_cost_cny"].to_numpy(
                dtype=float
            )
            for scenario in FLEX_RATIO_SCENARIOS
        ]
    )
    y_min, y_max = _flex_ratio_y_bounds(values, include_zero=False)
    image = Image.new("RGB", (1800, 900), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, "Flex-ratio Sensitivity: Total Operating Cost")
    panel_bounds = ((18, 105, 1782, 485), (18, 510, 1782, 890))
    for bounds, scenario in zip(
        panel_bounds,
        FLEX_RATIO_SCENARIOS,
        strict=True,
    ):
        draw.rounded_rectangle(bounds, radius=12, fill=PANEL, outline=GRID)
        plot = (175, bounds[1] + 72, 1745, bounds[3] - 58)
        _draw_flex_ratio_axes(
            draw,
            plot,
            y_min=y_min,
            y_max=y_max,
            panel_title=CASE_LABELS[scenario],
            y_label="Operating cost (CNY)",
        )
        _draw_flex_ratio_line(
            draw,
            ratios,
            rows_by_scenario[scenario]["operating_cost_cny"].to_numpy(
                dtype=float
            ),
            plot,
            y_min,
            y_max,
            CASE_COLORS[scenario],
        )
    image.save(output_path)


def _draw_flex_ratio_cost_savings_plot(
    rows_by_scenario: dict[str, pd.DataFrame],
    ratios: tuple[float, ...],
    output_path: Path,
) -> None:
    values = np.concatenate(
        [
            rows_by_scenario[scenario]["cost_savings_pct"].to_numpy(
                dtype=float
            )
            for scenario in FLEX_RATIO_SCENARIOS
        ]
    )
    y_min, y_max = _flex_ratio_y_bounds(values, include_zero=True)
    image = Image.new("RGB", (1800, 900), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, "Flex-ratio Sensitivity: Cost Savings")
    panel = (18, 105, 1782, 890)
    draw.rounded_rectangle(panel, radius=12, fill=PANEL, outline=GRID)
    plot = (175, 205, 1745, 735)
    _draw_flex_ratio_axes(
        draw,
        plot,
        y_min=y_min,
        y_max=y_max,
        panel_title="Savings versus each zero-shift baseline",
        y_label="Cost savings (%)",
    )
    _draw_flex_ratio_zero_line(draw, plot, y_min, y_max)
    for scenario in FLEX_RATIO_SCENARIOS:
        _draw_flex_ratio_line(
            draw,
            ratios,
            rows_by_scenario[scenario]["cost_savings_pct"].to_numpy(
                dtype=float
            ),
            plot,
            y_min,
            y_max,
            CASE_COLORS[scenario],
        )
    _draw_flex_ratio_saturation_mark(draw, rows_by_scenario, plot)
    _draw_legend(
        draw,
        230,
        146,
        [
            (CASE_LABELS[scenario], CASE_COLORS[scenario])
            for scenario in FLEX_RATIO_SCENARIOS
        ],
        max_x=1715,
    )
    image.save(output_path)


def _draw_flex_ratio_marginal_savings_plot(
    rows_by_scenario: dict[str, pd.DataFrame],
    ratios: tuple[float, ...],
    output_path: Path,
) -> None:
    marginal_values = np.concatenate(
        [
            rows_by_scenario[scenario][
                "marginal_cost_savings_cny_per_flex_ratio"
            ].to_numpy(dtype=float)[1:]
            for scenario in FLEX_RATIO_SCENARIOS
        ]
    )
    y_min, y_max = _flex_ratio_y_bounds(marginal_values, include_zero=True)
    image = Image.new("RGB", (1800, 900), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, "Flex-ratio Sensitivity: Marginal Cost Savings")
    panel = (18, 105, 1782, 890)
    draw.rounded_rectangle(panel, radius=12, fill=PANEL, outline=GRID)
    plot = (175, 205, 1745, 735)
    _draw_flex_ratio_axes(
        draw,
        plot,
        y_min=y_min,
        y_max=y_max,
        panel_title="Savings per unit increase in flex ratio",
        y_label="Marginal savings (CNY)",
    )
    _draw_flex_ratio_zero_line(draw, plot, y_min, y_max)
    plot_left, plot_top, plot_right, plot_bottom = plot
    baseline_y = round(
        plot_bottom
        - (0.0 - y_min) / (y_max - y_min) * (plot_bottom - plot_top)
    )
    positive_ratios = ratios[1:]
    slot_width = (plot_right - plot_left) / max(len(positive_ratios), 1)
    bar_width = max(8, min(30, round(slot_width * 0.28)))
    bar_gap = 8
    group_width = 2 * bar_width + bar_gap
    for ratio_index, ratio in enumerate(positive_ratios):
        center = round(
            plot_left
            + group_width / 2
            + ratio * (plot_right - plot_left - group_width)
        )
        for scenario_index, scenario in enumerate(FLEX_RATIO_SCENARIOS):
            value = float(
                rows_by_scenario[scenario].iloc[ratio_index + 1][
                    "marginal_cost_savings_cny_per_flex_ratio"
                ]
            )
            value_y = round(
                plot_bottom
                - (value - y_min) / (y_max - y_min) * (plot_bottom - plot_top)
            )
            left = (
                center - bar_width - bar_gap // 2
                if scenario_index == 0
                else center + bar_gap // 2
            )
            draw.rectangle(
                (
                    left,
                    min(value_y, baseline_y),
                    left + bar_width,
                    max(value_y, baseline_y),
                ),
                fill=CASE_COLORS[scenario],
            )
    _draw_flex_ratio_saturation_mark(draw, rows_by_scenario, plot)
    _draw_legend(
        draw,
        230,
        146,
        [
            (CASE_LABELS[scenario], CASE_COLORS[scenario])
            for scenario in FLEX_RATIO_SCENARIOS
        ],
        max_x=1715,
    )
    image.save(output_path)


def make_flex_ratio_sensitivity_plots(
    sensitivity_metrics: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    rows_by_scenario, ratios = _prepare_flex_ratio_sensitivity_inputs(
        sensitivity_metrics
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / filename for filename in FLEX_RATIO_PLOT_FILENAMES
    ]
    _draw_flex_ratio_total_cost_plot(
        rows_by_scenario,
        ratios,
        output_paths[0],
    )
    _draw_flex_ratio_cost_savings_plot(
        rows_by_scenario,
        ratios,
        output_paths[1],
    )
    _draw_flex_ratio_marginal_savings_plot(
        rows_by_scenario,
        ratios,
        output_paths[2],
    )
    return output_paths


def _prepare_storage_scale_sensitivity_inputs(
    sensitivity_metrics: pd.DataFrame,
) -> pd.DataFrame:
    missing_columns = [
        column
        for column in STORAGE_SCALE_SENSITIVITY_COLUMNS
        if column not in sensitivity_metrics
    ]
    if missing_columns:
        raise ValueError(
            "storage-scale sensitivity metrics missing columns: "
            f"{', '.join(missing_columns)}"
        )
    rows = sensitivity_metrics.loc[
        :,
        list(STORAGE_SCALE_SENSITIVITY_COLUMNS),
    ].copy()
    if rows.empty:
        raise ValueError("storage-scale sensitivity metrics must not be empty")
    if rows["storage_scale"].duplicated().any():
        raise ValueError("storage_scale values must be unique")
    numeric_columns = STORAGE_SCALE_SENSITIVITY_COLUMNS[1:]
    for column in numeric_columns:
        if not pd.api.types.is_numeric_dtype(rows[column]):
            raise ValueError(
                f"storage-scale sensitivity column {column} must be numeric"
            )
        values = rows[column].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(
                f"storage-scale sensitivity column {column} must be finite"
            )
    return rows.reset_index(drop=True)


def _storage_scale_y_bounds(
    values: np.ndarray,
    *,
    include_zero: bool,
) -> tuple[float, float]:
    lower = float(np.min(values))
    upper = float(np.max(values))
    if include_zero:
        lower = min(lower, 0.0)
        upper = max(upper, 0.0)
    span = max(upper - lower, abs(upper) * 0.05, 1.0)
    margin = span * 0.12
    if include_zero:
        return lower - margin, upper + margin
    return lower - margin, upper + margin


def _draw_storage_scale_grouped_bars(
    *,
    output_path: Path,
    title: str,
    panel_title: str,
    y_label: str,
    rows: pd.DataFrame,
    first_column: str,
    first_label: str,
    first_color: str,
    second_column: str,
    second_label: str,
    second_color: str,
    include_zero: bool,
) -> None:
    first_values = rows[first_column].to_numpy(dtype=float)
    second_values = rows[second_column].to_numpy(dtype=float)
    y_min, y_max = _storage_scale_y_bounds(
        np.concatenate((first_values, second_values)),
        include_zero=include_zero,
    )
    image = Image.new("RGB", (1800, 900), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, title)
    panel = (18, 105, 1782, 890)
    draw.rounded_rectangle(panel, radius=12, fill=PANEL, outline=GRID)
    draw.text((52, 130), panel_title, font=_font(21, bold=True), fill=TEXT)
    draw.text((52, 162), y_label, font=_font(14), fill=MUTED)
    plot = (175, 235, 1745, 700)
    plot_left, plot_top, plot_right, plot_bottom = plot
    draw.rectangle(plot, outline=MUTED, width=1)
    for index in range(5):
        fraction = index / 4.0
        y = round(plot_bottom - fraction * (plot_bottom - plot_top))
        value = y_min + fraction * (y_max - y_min)
        draw.line((plot_left, y, plot_right, y), fill=GRID, width=1)
        label = _tick_label(value)
        label_width = draw.textlength(label, font=_font(13))
        draw.text(
            (plot_left - label_width - 8, y - 8),
            label,
            font=_font(13),
            fill=MUTED,
        )
    y_span = max(y_max - y_min, 1e-12)

    def y_coordinate(value: float) -> int:
        return round(
            plot_bottom
            - (value - y_min) / y_span * (plot_bottom - plot_top)
        )

    baseline_y = y_coordinate(0.0) if include_zero else plot_bottom
    if include_zero and plot_top <= baseline_y <= plot_bottom:
        draw.line((plot_left, baseline_y, plot_right, baseline_y), fill=TEXT, width=2)
    group_count = len(rows)
    group_width = (plot_right - plot_left) / group_count
    bar_width = max(32, min(110, round(group_width * 0.25)))
    bar_gap = max(12, round(bar_width * 0.18))
    for index, row in enumerate(rows.itertuples(index=False)):
        center = round(plot_left + (index + 0.5) * group_width)
        values_and_colors = (
            (float(getattr(row, first_column)), first_color, -1),
            (float(getattr(row, second_column)), second_color, 1),
        )
        for value, color, side in values_and_colors:
            left = (
                center - bar_gap // 2 - bar_width
                if side < 0
                else center + bar_gap // 2
            )
            value_y = y_coordinate(value)
            draw.rectangle(
                (
                    left,
                    min(value_y, baseline_y),
                    left + bar_width,
                    max(value_y, baseline_y),
                ),
                fill=color,
            )
        energy_label = f"{float(row.battery_energy_mwh):g} MWh"
        power_label = f"{float(row.battery_power_mw):g} MW"
        for offset, label in ((0, energy_label), (20, power_label)):
            label_width = draw.textlength(label, font=_font(14))
            draw.text(
                (center - label_width / 2, plot_bottom + 14 + offset),
                label,
                font=_font(14),
                fill=MUTED,
            )
    x_label = "Battery energy / power"
    x_label_width = draw.textlength(x_label, font=_font(14))
    draw.text(
        ((plot_left + plot_right - x_label_width) / 2, 790),
        x_label,
        font=_font(14),
        fill=MUTED,
    )
    _draw_legend(
        draw,
        225,
        195,
        [(first_label, first_color), (second_label, second_color)],
        max_x=1715,
    )
    image.save(output_path)


def make_storage_scale_sensitivity_plots(
    sensitivity_metrics: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    rows = _prepare_storage_scale_sensitivity_inputs(sensitivity_metrics)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / filename for filename in STORAGE_SCALE_PLOT_FILENAMES
    ]
    _draw_storage_scale_grouped_bars(
        output_path=output_paths[0],
        title="Storage-scale Sensitivity: Total Operating Cost",
        panel_title="Storage-enabled cases at fixed 3-hour delay",
        y_label="Operating cost (CNY)",
        rows=rows,
        first_column="renewables_storage_cost_cny",
        first_label="Renewables + battery",
        first_color=CASE_COLORS["renewables_storage"],
        second_column="joint_cost_cny",
        second_label="Joint",
        second_color=CASE_COLORS["joint"],
        include_zero=False,
    )
    _draw_storage_scale_grouped_bars(
        output_path=output_paths[1],
        title="Storage-scale Sensitivity: Shift Value",
        panel_title="Task-shifting savings at fixed 3-hour delay",
        y_label="Shift savings (CNY)",
        rows=rows,
        first_column="no_storage_shift_savings_cny",
        first_label="No battery",
        first_color=CASE_COLORS["renewables_shift"],
        second_column="storage_shift_savings_cny",
        second_label="With battery",
        second_color=CASE_COLORS["joint"],
        include_zero=True,
    )
    return output_paths


def _storage_energy_power_grid(
    sensitivity_metrics: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[float, ...], tuple[float, ...]]:
    rows = _prepare_storage_scale_sensitivity_inputs(sensitivity_metrics)
    if rows.duplicated(
        ["battery_energy_mwh", "battery_power_mw"]
    ).any():
        raise ValueError(
            "storage-energy-power sensitivity contains duplicate grid cells"
        )
    energy_values = tuple(
        sorted(rows["battery_energy_mwh"].unique().tolist())
    )
    power_values = tuple(
        sorted(rows["battery_power_mw"].unique().tolist())
    )
    expected_cells = {
        (energy_mwh, power_mw)
        for energy_mwh in energy_values
        for power_mw in power_values
    }
    actual_cells = set(
        zip(
            rows["battery_energy_mwh"],
            rows["battery_power_mw"],
            strict=True,
        )
    )
    if actual_cells != expected_cells:
        raise ValueError(
            "storage-energy-power sensitivity must contain a complete grid"
        )
    return rows, energy_values, power_values


def _interpolate_color(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    fraction: float,
) -> tuple[int, int, int]:
    clipped_fraction = min(max(fraction, 0.0), 1.0)
    return tuple(
        round(
            start_value
            + (end_value - start_value) * clipped_fraction
        )
        for start_value, end_value in zip(start, end, strict=True)
    )


def _heatmap_cell_color(
    value: float,
    *,
    minimum: float,
    maximum: float,
    divergent: bool,
) -> tuple[int, int, int]:
    if divergent:
        span = max(abs(minimum), abs(maximum), 1e-12)
        if value < 0.0:
            return _interpolate_color(
                (255, 255, 255),
                (220, 38, 38),
                abs(value) / span,
            )
        return _interpolate_color(
            (255, 255, 255),
            (5, 150, 105),
            value / span,
        )
    span = max(maximum - minimum, 1e-12)
    return _interpolate_color(
        (219, 234, 254),
        (30, 64, 175),
        (value - minimum) / span,
    )


def _draw_storage_energy_power_heatmap(
    *,
    rows: pd.DataFrame,
    energy_values: tuple[float, ...],
    power_values: tuple[float, ...],
    output_path: Path,
    title: str,
    metric_column: str,
    metric_label: str,
    divergent: bool,
) -> None:
    values_by_cell = {
        (float(row.battery_energy_mwh), float(row.battery_power_mw)): float(
            getattr(row, metric_column)
        )
        for row in rows.itertuples(index=False)
    }
    values = np.array(list(values_by_cell.values()), dtype=float)
    minimum = float(values.min())
    maximum = float(values.max())
    image = Image.new("RGB", (1800, 900), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, title)
    panel = (18, 105, 1782, 890)
    draw.rounded_rectangle(panel, radius=12, fill=PANEL, outline=GRID)
    draw.text(
        (52, 130),
        metric_label,
        font=_font(21, bold=True),
        fill=TEXT,
    )
    draw.text(
        (52, 162),
        "Fixed 3-hour delay; each cell is an independent 28-day run",
        font=_font(14),
        fill=MUTED,
    )
    plot_left, plot_top, plot_right, plot_bottom = (330, 235, 1700, 690)
    cell_width = (plot_right - plot_left) / len(power_values)
    cell_height = (plot_bottom - plot_top) / len(energy_values)
    for row_index, energy_mwh in enumerate(reversed(energy_values)):
        top = round(plot_top + row_index * cell_height)
        bottom = round(plot_top + (row_index + 1) * cell_height)
        energy_label = f"{energy_mwh:g}"
        label_width = draw.textlength(energy_label, font=_font(17))
        draw.text(
            (plot_left - label_width - 22, (top + bottom - 18) / 2),
            energy_label,
            font=_font(17),
            fill=MUTED,
        )
        for column_index, power_mw in enumerate(power_values):
            left = round(plot_left + column_index * cell_width)
            right = round(plot_left + (column_index + 1) * cell_width)
            value = values_by_cell[(energy_mwh, power_mw)]
            draw.rectangle(
                (left, top, right, bottom),
                fill=_heatmap_cell_color(
                    value,
                    minimum=minimum,
                    maximum=maximum,
                    divergent=divergent,
                ),
                outline=BACKGROUND,
                width=4,
            )
            label = f"{value:,.2f}"
            label_width = draw.textlength(label, font=_font(24, bold=True))
            draw.text(
                ((left + right - label_width) / 2, (top + bottom - 27) / 2),
                label,
                font=_font(24, bold=True),
                fill=TEXT,
            )
    for column_index, power_mw in enumerate(power_values):
        left = round(plot_left + column_index * cell_width)
        right = round(plot_left + (column_index + 1) * cell_width)
        label = f"{power_mw:g}"
        label_width = draw.textlength(label, font=_font(17))
        draw.text(
            ((left + right - label_width) / 2, plot_bottom + 18),
            label,
            font=_font(17),
            fill=MUTED,
        )
    draw.text(
        (52, (plot_top + plot_bottom - 18) / 2),
        "Energy (MWh)",
        font=_font(17),
        fill=MUTED,
    )
    x_label = "Power (MW)"
    x_label_width = draw.textlength(x_label, font=_font(17))
    draw.text(
        ((plot_left + plot_right - x_label_width) / 2, 755),
        x_label,
        font=_font(17),
        fill=MUTED,
    )
    if divergent:
        legend = "Red: battery weakens shift value    Green: battery strengthens it"
    else:
        legend = "Darker blue: lower joint operating cost"
    draw.text((52, 815), legend, font=_font(15), fill=MUTED)
    image.save(output_path)


def make_storage_energy_power_sensitivity_plots(
    sensitivity_metrics: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    rows, energy_values, power_values = _storage_energy_power_grid(
        sensitivity_metrics
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / filename
        for filename in STORAGE_ENERGY_POWER_PLOT_FILENAMES
    ]
    _draw_storage_energy_power_heatmap(
        rows=rows,
        energy_values=energy_values,
        power_values=power_values,
        output_path=output_paths[0],
        title="Storage Energy x Power Sensitivity: Joint Cost",
        metric_column="joint_cost_cny",
        metric_label="Joint operating cost (CNY)",
        divergent=False,
    )
    rows = rows.copy()
    rows["storage_effect_on_shift_cny"] = (
        rows["storage_shift_savings_cny"]
        - rows["no_storage_shift_savings_cny"]
    )
    _draw_storage_energy_power_heatmap(
        rows=rows,
        energy_values=energy_values,
        power_values=power_values,
        output_path=output_paths[1],
        title="Storage Energy x Power Sensitivity: Shift Effect",
        metric_column="storage_effect_on_shift_cny",
        metric_label="Battery effect on shift value (CNY)",
        divergent=True,
    )
    return output_paths
