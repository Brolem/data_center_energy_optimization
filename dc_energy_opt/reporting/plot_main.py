from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from .plot_shared import (
    BACKGROUND,
    CASE_COLORS,
    CASE_LABELS,
    CASE_ORDER,
    GRID,
    MUTED,
    PANEL,
    PLOT_FILENAMES,
    TEXT,
    _battery_power_series,
    _case_data,
    _draw_case_lines_panel,
    _draw_dashed_line,
    _draw_header,
    _draw_legend,
    _draw_series,
    _font,
    _hour_axis,
    _hour_interval_axis,
    _mark_settlement_tail,
    _nonnegative_limit,
    _normalized_nonnegative_cost,
    _panel_axes,
    _soc_boundary_series,
    _tick_label,
    _validate_plot_inputs,
    _draw_vertical_text,
    _xy_points,
)

def _draw_day_ahead_power_results(
    hourly_results: pd.DataFrame,
    output_path: Path,
    header_title: str = "Rolling 24+3 h Day-Ahead Power Results",
) -> None:
    image = Image.new("RGB", (1800, 1120), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, header_title)
    panels = [
        ((35, 105, 885, 595), "Data-center demand", "dc_power_mw"),
        ((915, 105, 1765, 595), "Grid purchase", "grid_power_mw"),
        ((35, 620, 885, 1090), "Solar power used", "solar_used_mw"),
        ((915, 620, 1765, 1090), "Wind power used", "wind_used_mw"),
    ]
    for bounds, title, column in panels:
        _draw_case_lines_panel(
            draw,
            hourly_results,
            bounds,
            title,
            column,
            "Power (MW)",
        )
    image.save(output_path)


def _draw_compute_scheduling_results(
    hourly_results: pd.DataFrame,
    output_path: Path,
    header_title: str = "Rolling 24+3 h Day-Ahead Compute Scheduling",
) -> None:
    image = Image.new("RGB", (1800, 820), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, header_title)
    baseline = _case_data(hourly_results, "renewables_only")
    scheduled_values = [
        _case_data(hourly_results, case_name)["cpu_scheduled_pu"].to_numpy(
            dtype=float
        )
        for case_name in CASE_ORDER
    ]
    arrival = baseline["cpu_arrival_pu"].to_numpy(dtype=float)
    cpu_values = [arrival, *scheduled_values]
    cpu_min = min(float(np.min(values)) for values in cpu_values)
    cpu_max = max(float(np.max(values)) for values in cpu_values)
    padding = max((cpu_max - cpu_min) * 0.12, 0.01)
    y_min = max(0.0, cpu_min - padding)
    y_max = cpu_max + padding

    arrival_bounds = (35, 105, 885, 790)
    arrival_plot = _panel_axes(
        draw,
        arrival_bounds,
        "CPU arrival",
        y_min,
        y_max,
        "CPU utilization (p.u.); common to all four cases",
        x_min=_hour_axis(baseline)[0],
        x_max=_hour_axis(baseline)[1],
        x_ticks=_hour_axis(baseline)[2],
    )
    x_min, x_max, _ = _hour_axis(baseline)
    _mark_settlement_tail(draw, baseline, arrival_plot, x_min, x_max)
    hours = baseline["hour"].to_numpy(dtype=float)
    _draw_series(
        draw,
        hours,
        arrival,
        arrival_plot,
        y_min,
        y_max,
        "#334155",
        width=4,
        x_min=x_min,
        x_max=x_max,
    )
    _draw_legend(
        draw,
        arrival_bounds[0] + 90,
        arrival_bounds[1] + 69,
        [("CPU arrival", "#334155")],
        max_x=arrival_bounds[2] - 18,
    )

    scheduled_bounds = (915, 105, 1765, 790)
    scheduled_plot = _panel_axes(
        draw,
        scheduled_bounds,
        "CPU scheduled",
        y_min,
        y_max,
        "CPU utilization (p.u.)",
        x_min=x_min,
        x_max=x_max,
        x_ticks=_hour_axis(baseline)[2],
    )
    _mark_settlement_tail(draw, baseline, scheduled_plot, x_min, x_max)
    for case_name, values in zip(CASE_ORDER, scheduled_values, strict=True):
        data = _case_data(hourly_results, case_name)
        _draw_series(
            draw,
            data["hour"].to_numpy(dtype=float),
            values,
            scheduled_plot,
            y_min,
            y_max,
            CASE_COLORS[case_name],
            width=4 if case_name == "joint" else 2,
            x_min=x_min,
            x_max=x_max,
        )
    _draw_legend(
        draw,
        scheduled_bounds[0] + 90,
        scheduled_bounds[1] + 69,
        [(CASE_LABELS[name], CASE_COLORS[name]) for name in CASE_ORDER],
        max_x=scheduled_bounds[2] - 18,
    )
    image.save(output_path)


def _draw_battery_power_panel(
    draw: ImageDraw.ImageDraw,
    data: pd.DataFrame,
    bounds: tuple[int, int, int, int],
    title: str,
) -> None:
    hours, charge, discharge = _battery_power_series(data)
    limit = max(float(np.max(charge)), float(np.max(-discharge)), 1.0) * 1.10
    x_min, x_max, x_ticks = _hour_interval_axis(data)
    plot = _panel_axes(
        draw,
        bounds,
        title,
        -limit,
        limit,
        "Battery power (MW): charge positive; discharge negative",
        x_min=x_min,
        x_max=x_max,
        x_ticks=x_ticks,
    )
    _mark_settlement_tail(
        draw,
        data,
        plot,
        x_min,
        x_max,
        interval_aligned=True,
    )
    zero_y = _xy_points(
        np.array([0.0]),
        np.array([0.0]),
        plot,
        -limit,
        limit,
        x_min=x_min,
        x_max=x_max,
    )[0][1]
    plot_left, _, plot_right, _ = plot
    hour_width = (plot_right - plot_left) / max(len(data), 1)
    bar_half_width = max(round(hour_width * 0.14), 1)
    charge_points = _xy_points(
        hours,
        charge,
        plot,
        -limit,
        limit,
        x_min=x_min,
        x_max=x_max,
    )
    discharge_points = _xy_points(
        hours,
        discharge,
        plot,
        -limit,
        limit,
        x_min=x_min,
        x_max=x_max,
    )
    for charge_point, discharge_point in zip(
        charge_points, discharge_points, strict=True
    ):
        draw.rectangle(
            (
                charge_point[0] - bar_half_width,
                min(charge_point[1], zero_y),
                charge_point[0] + bar_half_width,
                max(charge_point[1], zero_y),
            ),
            fill="#2563EB",
        )
        draw.rectangle(
            (
                discharge_point[0] - bar_half_width,
                min(discharge_point[1], zero_y),
                discharge_point[0] + bar_half_width,
                max(discharge_point[1], zero_y),
            ),
            fill="#EA580C",
        )
    draw.line((plot_left, zero_y, plot_right, zero_y), fill=TEXT, width=2)
    left, top, right, _ = bounds
    _draw_legend(
        draw,
        left + 90,
        top + 69,
        [("Charge (+ MW)", "#2563EB"), ("Discharge (- MW)", "#EA580C")],
        max_x=right - 18,
    )


def _draw_soc_panel(
    draw: ImageDraw.ImageDraw,
    data: pd.DataFrame,
    bounds: tuple[int, int, int, int],
    title: str,
) -> None:
    x_min, x_max, x_ticks = _hour_interval_axis(data)
    plot = _panel_axes(
        draw,
        bounds,
        title,
        0.0,
        1.0,
        "State of charge at hour boundaries (p.u.); bounds 0.10-0.90",
        x_min=x_min,
        x_max=x_max,
        x_ticks=x_ticks,
    )
    _mark_settlement_tail(
        draw,
        data,
        plot,
        x_min,
        x_max,
        interval_aligned=True,
    )
    hours, soc = _soc_boundary_series(data)
    for bound in (0.10, 0.90):
        points = _xy_points(
            np.array([x_min, x_max]),
            np.array([bound, bound]),
            plot,
            0.0,
            1.0,
            x_min=x_min,
            x_max=x_max,
        )
        _draw_dashed_line(draw, points, "#94A3B8", width=2)
    _draw_series(
        draw,
        hours,
        soc,
        plot,
        0.0,
        1.0,
        "#059669",
        width=3,
        x_min=x_min,
        x_max=x_max,
    )
    left, top, right, _ = bounds
    _draw_legend(
        draw,
        left + 90,
        top + 69,
        [
            ("SOC", "#059669"),
            ("Bounds 0.10 / 0.90", "#94A3B8"),
        ],
        max_x=right - 18,
    )


def _draw_battery_operation_results(
    hourly_results: pd.DataFrame,
    output_path: Path,
    header_title: str = "Rolling 24+3 h Day-Ahead Battery Operation",
) -> None:
    image = Image.new("RGB", (1800, 1120), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, header_title)
    storage = _case_data(hourly_results, "renewables_storage")
    joint = _case_data(hourly_results, "joint")
    _draw_battery_power_panel(
        draw,
        storage,
        (35, 105, 885, 595),
        "Renewables + battery: charge / discharge",
    )
    _draw_battery_power_panel(
        draw,
        joint,
        (915, 105, 1765, 595),
        "Joint: charge / discharge",
    )
    _draw_soc_panel(
        draw,
        storage,
        (35, 620, 885, 1090),
        "Renewables + battery: SOC trajectory",
    )
    _draw_soc_panel(
        draw,
        joint,
        (915, 620, 1765, 1090),
        "Joint: SOC trajectory",
    )
    image.save(output_path)


def _draw_renewable_panel(
    draw: ImageDraw.ImageDraw,
    data: pd.DataFrame,
    bounds: tuple[int, int, int, int],
    resource: str,
) -> None:
    available_column = f"{resource}_available_mw"
    used_column = f"{resource}_used_mw"
    curtailed_column = f"{resource}_curtailed_mw"
    available = data[available_column].to_numpy(dtype=float)
    used = data[used_column].to_numpy(dtype=float)
    curtailed = data[curtailed_column].to_numpy(dtype=float)
    y_max = _nonnegative_limit([available, used, curtailed])
    title = f"Joint case: {resource.capitalize()} dispatch"
    x_min, x_max, x_ticks = _hour_axis(data)
    plot = _panel_axes(
        draw,
        bounds,
        title,
        0.0,
        y_max,
        "Power (MW)",
        x_min=x_min,
        x_max=x_max,
        x_ticks=x_ticks,
    )
    _mark_settlement_tail(draw, data, plot, x_min, x_max)
    hours = data["hour"].to_numpy(dtype=float)
    _draw_series(
        draw,
        hours,
        available,
        plot,
        0.0,
        y_max,
        "#64748B",
        width=4,
        x_min=x_min,
        x_max=x_max,
    )
    _draw_series(
        draw,
        hours,
        used,
        plot,
        0.0,
        y_max,
        "#059669",
        width=3,
        x_min=x_min,
        x_max=x_max,
    )
    _draw_series(
        draw,
        hours,
        curtailed,
        plot,
        0.0,
        y_max,
        "#DC2626",
        width=3,
        dashed=True,
        x_min=x_min,
        x_max=x_max,
    )
    left, top, right, _ = bounds
    _draw_legend(
        draw,
        left + 90,
        top + 69,
        [
            (f"{resource.capitalize()} available", "#64748B"),
            (f"{resource.capitalize()} used", "#059669"),
            (f"{resource.capitalize()} curtailed", "#DC2626"),
        ],
        max_x=right - 18,
    )


def _draw_renewable_dispatch_results(
    hourly_results: pd.DataFrame,
    output_path: Path,
    header_title: str = "Rolling 24+3 h Day-Ahead Renewable Dispatch",
) -> None:
    image = Image.new("RGB", (1800, 820), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, header_title)
    joint = _case_data(hourly_results, "joint")
    _draw_renewable_panel(draw, joint, (35, 105, 885, 790), "solar")
    _draw_renewable_panel(draw, joint, (915, 105, 1765, 790), "wind")
    image.save(output_path)


def _draw_cost_comparison(
    metrics: pd.DataFrame,
    output_path: Path,
    header_title: str = "Rolling 28-Day Operating Cost",
    cost_axis_label: str = (
        "Operating cost (CNY; analysis + settlement tail)"
    ),
) -> None:
    ordered = metrics.set_index("case").loc[CASE_ORDER]
    component_columns = [
        "grid_purchase_cost_cny",
        "solar_om_cost_cny",
        "wind_om_cost_cny",
        "battery_om_cost_cny",
        "battery_degradation_cost_cny",
    ]
    component_labels = [
        "Grid purchase",
        "Solar O&M",
        "Wind O&M",
        "Battery O&M",
        "Battery degradation",
    ]
    component_colors = [
        "#4F46E5",
        "#F59E0B",
        "#0284C7",
        "#EA580C",
        "#DB2777",
    ]
    components = [
        np.array(
            [
                _normalized_nonnegative_cost(value)
                for value in ordered[column].to_numpy(dtype=float)
            ],
            dtype=float,
        )
        for column in component_columns
    ]
    totals = np.sum(np.vstack(components), axis=0)
    y_max = max(float(np.max(totals)) * 1.15, 1.0)

    image = Image.new("RGB", (1800, 1050), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, header_title)
    plot = (180, 170, 1750, 910)
    plot_left, plot_top, plot_right, plot_bottom = plot
    draw.rectangle(plot, fill=PANEL, outline=MUTED)
    for index in range(6):
        fraction = index / 5.0
        y = round(plot_bottom - fraction * (plot_bottom - plot_top))
        value = fraction * y_max
        draw.line((plot_left, y, plot_right, y), fill=GRID, width=1)
        label = _tick_label(value)
        label_width = draw.textlength(label, font=_font(14))
        draw.text(
            (plot_left - label_width - 12, y - 9),
            label,
            font=_font(14),
            fill=MUTED,
        )
    _draw_vertical_text(
        image,
        cost_axis_label,
        35,
        (plot_top + plot_bottom) // 2,
    )
    _draw_legend(
        draw,
        plot_left,
        121,
        list(zip(component_labels, component_colors, strict=True)),
        max_x=plot_right,
    )

    centers = np.linspace(plot_left + 150, plot_right - 150, len(CASE_ORDER))
    bar_width = 145
    for case_index, center in enumerate(centers):
        cumulative = 0.0
        for values, color in zip(components, component_colors, strict=True):
            value = float(values[case_index])
            lower_y = round(
                plot_bottom
                - cumulative / y_max * (plot_bottom - plot_top)
            )
            cumulative += value
            upper_y = round(
                plot_bottom
                - cumulative / y_max * (plot_bottom - plot_top)
            )
            if value > 0.0:
                draw.rectangle(
                    (
                        round(center - bar_width / 2),
                        upper_y,
                        round(center + bar_width / 2),
                        lower_y,
                    ),
                    fill=color,
                )
        total_label = f"CNY {totals[case_index]:,.0f}"
        total_width = draw.textlength(total_label, font=_font(16, bold=True))
        total_y = round(
            plot_bottom
            - totals[case_index] / y_max * (plot_bottom - plot_top)
        )
        draw.text(
            (center - total_width / 2, max(plot_top + 4, total_y - 27)),
            total_label,
            font=_font(16, bold=True),
            fill=TEXT,
        )
        case_label = CASE_LABELS[CASE_ORDER[case_index]]
        label_width = draw.textlength(case_label, font=_font(15))
        draw.text(
            (center - label_width / 2, plot_bottom + 16),
            case_label,
            font=_font(15),
            fill=MUTED,
        )
    image.save(output_path)


def make_plots(
    hourly_results: pd.DataFrame,
    metrics: pd.DataFrame,
    output_dir: Path,
) -> None:
    _validate_plot_inputs(hourly_results, metrics)
    output_dir.mkdir(parents=True, exist_ok=True)

    _draw_day_ahead_power_results(
        hourly_results,
        output_dir / PLOT_FILENAMES[0],
    )
    _draw_compute_scheduling_results(
        hourly_results,
        output_dir / PLOT_FILENAMES[1],
    )
    _draw_battery_operation_results(
        hourly_results,
        output_dir / PLOT_FILENAMES[2],
    )
    _draw_renewable_dispatch_results(
        hourly_results,
        output_dir / PLOT_FILENAMES[3],
    )
    _draw_cost_comparison(metrics, output_dir / PLOT_FILENAMES[4])
