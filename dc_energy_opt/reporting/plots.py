from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from pyscipopt import Model

from .metrics import summarize_costs


BACKGROUND = "#F8FAFC"
GRID = "#CBD5E1"
TEXT = "#0F172A"
MUTED = "#475569"
PANEL = "#FFFFFF"
SCENARIO_SUBTITLE = "Houston 2020 Renewables + Exogenous Paper TOU"

CASE_ORDER = [
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
]
CASE_LABELS = {
    "renewables_only": "Renewables",
    "renewables_shift": "Renewables + shift",
    "renewables_storage": "Renewables + battery",
    "joint": "Joint",
}
CASE_COLORS = {
    "renewables_only": "#059669",
    "renewables_shift": "#2563EB",
    "renewables_storage": "#F59E0B",
    "joint": "#DC2626",
}
PLOT_FILENAMES = [
    "power_dispatch.png",
    "compute_schedule.png",
    "battery_dispatch.png",
    "renewable_dispatch.png",
    "cost_breakdown.png",
]
TASK_DELAY_PLOT_FILENAME = "task_delay_objectives.png"
TASK_DELAY_CASES = ("renewables_shift", "joint")
DAILY_COST_PLOT_FILENAMES = {
    case_name: f"daily_cost_{case_name}.png"
    for case_name in CASE_ORDER
}
HOURLY_NUMERIC_COLUMNS = [
    "hour",
    "cpu_arrival_pu",
    "cpu_scheduled_pu",
    "it_power_mw",
    "dc_power_mw",
    "grid_power_mw",
    "solar_available_mw",
    "solar_used_mw",
    "solar_curtailed_mw",
    "wind_available_mw",
    "wind_used_mw",
    "wind_curtailed_mw",
    "charge_mw",
    "discharge_mw",
    "soc_start",
    "soc_end",
    "electricity_price_cny_per_kwh",
    "hourly_grid_purchase_cost_cny",
    "hourly_solar_om_cost_cny",
    "hourly_wind_om_cost_cny",
    "hourly_battery_om_cost_cny",
    "hourly_battery_degradation_cost_cny",
    "hourly_operating_cost_cny",
]
METRIC_NUMERIC_COLUMNS = [
    "grid_purchase_cost_cny",
    "solar_om_cost_cny",
    "wind_om_cost_cny",
    "battery_om_cost_cny",
    "battery_degradation_cost_cny",
    "operating_cost_cny",
]
NONNEGATIVE_HOURLY_COLUMNS = [
    "cpu_arrival_pu",
    "cpu_scheduled_pu",
    "it_power_mw",
    "dc_power_mw",
    "grid_power_mw",
    "solar_available_mw",
    "solar_used_mw",
    "solar_curtailed_mw",
    "wind_available_mw",
    "wind_used_mw",
    "wind_curtailed_mw",
    "charge_mw",
    "discharge_mw",
    "electricity_price_cny_per_kwh",
    "hourly_grid_purchase_cost_cny",
    "hourly_solar_om_cost_cny",
    "hourly_wind_om_cost_cny",
    "hourly_battery_om_cost_cny",
    "hourly_battery_degradation_cost_cny",
    "hourly_operating_cost_cny",
]
NONNEGATIVE_TOLERANCE = 1e-10


def software_versions() -> dict[str, str]:
    model = Model()
    return {
        "python": __import__("sys").version.split()[0],
        "pyscipopt": __import__("pyscipopt").__version__,
        "scip": ".".join(
            map(
                str,
                [
                    model.getMajorVersion(),
                    model.getMinorVersion(),
                    model.getTechVersion(),
                ],
            )
        ),
        "pillow": __import__("PIL").__version__,
        "nrel_pysam": __import__("PySAM").__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }


def _normalized_nonnegative_cost(value: float) -> float:
    if value < -NONNEGATIVE_TOLERANCE:
        raise ValueError(
            f"cost value {value} is below -{NONNEGATIVE_TOLERANCE}"
        )
    if value < 0.0:
        return 0.0
    return value


def _validate_plot_inputs(
    hourly_results: pd.DataFrame,
    metrics: pd.DataFrame,
    *,
    expected_period_roles: tuple[str, ...] | None = None,
) -> None:
    required_columns = {
        "hourly_results": ["case", "period_role", *HOURLY_NUMERIC_COLUMNS],
        "metrics": ["case", *METRIC_NUMERIC_COLUMNS],
    }
    dataframes = {
        "hourly_results": hourly_results,
        "metrics": metrics,
    }
    for dataframe_name, required in required_columns.items():
        dataframe = dataframes[dataframe_name]
        missing = [
            column for column in required if column not in dataframe.columns
        ]
        if missing:
            raise ValueError(
                f"{dataframe_name} missing required columns: "
                f"{', '.join(missing)}"
            )

    numeric_columns = {
        "hourly_results": HOURLY_NUMERIC_COLUMNS,
        "metrics": METRIC_NUMERIC_COLUMNS,
    }
    for dataframe_name, columns in numeric_columns.items():
        dataframe = dataframes[dataframe_name]
        for column in columns:
            if not pd.api.types.is_numeric_dtype(dataframe[column]):
                raise ValueError(
                    f"{dataframe_name} numeric column {column} "
                    "must have a numeric dtype"
                )
            values = dataframe[column].to_numpy(dtype=float)
            if not np.isfinite(values).all():
                raise ValueError(
                    f"{dataframe_name} numeric column {column} "
                    "contains non-finite values"
                )

    hour_values = hourly_results["hour"].to_numpy(dtype=float)
    if not np.equal(hour_values, np.round(hour_values)).all():
        raise ValueError("hourly_results hour values must be integers")

    for column in NONNEGATIVE_HOURLY_COLUMNS:
        if (
            hourly_results[column].to_numpy(dtype=float)
            < -NONNEGATIVE_TOLERANCE
        ).any():
            raise ValueError(
                f"hourly_results physical column {column} "
                f"contains values below -{NONNEGATIVE_TOLERANCE}"
            )

    for column in ("soc_start", "soc_end"):
        values = hourly_results[column].to_numpy(dtype=float)
        if ((values < 0.10 - 1e-9) | (values > 0.90 + 1e-9)).any():
            raise ValueError(
                f"hourly_results {column} must be within "
                "[0.10 - 1e-9, 0.90 + 1e-9]"
            )

    for column in METRIC_NUMERIC_COLUMNS:
        if (
            metrics[column].to_numpy(dtype=float)
            < -NONNEGATIVE_TOLERANCE
        ).any():
            raise ValueError(
                f"metrics cost column {column} contains values below "
                f"-{NONNEGATIVE_TOLERANCE}"
            )

    for dataframe_name, dataframe in dataframes.items():
        missing_cases = [
            case_name
            for case_name in CASE_ORDER
            if not dataframe["case"].eq(case_name).any()
        ]
        unexpected_cases = (
            dataframe.loc[
                ~dataframe["case"].isin(CASE_ORDER), "case"
            ]
            .drop_duplicates()
            .tolist()
        )
        if missing_cases or unexpected_cases:
            raise ValueError(
                f"{dataframe_name} case set invalid: "
                f"missing={missing_cases}, unexpected={unexpected_cases}"
            )

    baseline_rows = (
        hourly_results.loc[
            hourly_results["case"] == "renewables_only"
        ]
        .sort_values("hour")
        .reset_index(drop=True)
    )
    if len(baseline_rows) < 3:
        raise ValueError("hourly_results must contain the settlement tail")
    expected_hours = set(range(len(baseline_rows)))
    baseline_cpu_arrival = baseline_rows["cpu_arrival_pu"].to_numpy(
        dtype=float
    )
    if expected_period_roles is None:
        expected_roles = np.array(
            ["analysis"] * (len(baseline_rows) - 3)
            + ["settlement_tail"] * 3,
            dtype=object,
        )
    else:
        expected_roles = np.array(expected_period_roles, dtype=object)
        if len(expected_roles) != len(baseline_rows):
            raise ValueError(
                "expected_period_roles length must match hourly rows"
            )
    for case_name in CASE_ORDER:
        case_rows = hourly_results.loc[
            hourly_results["case"] == case_name
        ]
        if len(case_rows) != len(baseline_rows):
            raise ValueError(
                f"hourly_results case {case_name} must have exactly "
                f"{len(baseline_rows)} rows; "
                f"found {len(case_rows)}"
            )
        hours = case_rows["hour"]
        if not hours.is_unique or set(hours.tolist()) != expected_hours:
            raise ValueError(
                f"hourly_results case {case_name} hour values must be "
                f"unique 0..{len(baseline_rows) - 1}"
            )

        sorted_case_rows = case_rows.sort_values("hour")
        case_cpu_arrival = sorted_case_rows["cpu_arrival_pu"].to_numpy(
            dtype=float
        )
        if not np.allclose(
            case_cpu_arrival,
            baseline_cpu_arrival,
            rtol=0.0,
            atol=1e-10,
        ):
            raise ValueError(
                f"hourly_results case {case_name} cpu_arrival_pu "
                "does not match renewables_only by hour"
            )
        if not np.array_equal(
            sorted_case_rows["period_role"].to_numpy(dtype=object),
            expected_roles,
        ):
            raise ValueError(
                f"hourly_results case {case_name} period_role must mark "
                "the final three rows as settlement_tail"
            )

        metric_row_count = int(metrics["case"].eq(case_name).sum())
        if metric_row_count != 1:
            raise ValueError(
                f"metrics case {case_name} must have exactly one row; "
                f"found {metric_row_count}"
            )


@lru_cache(maxsize=None)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    filenames = (
        ("arialbd.ttf", "arial.ttf")
        if bold
        else ("segoeui.ttf", "arial.ttf")
    )
    windows_font_dir = Path("C:/Windows/Fonts")
    for filename in filenames:
        font_path = windows_font_dir / filename
        if font_path.is_file():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default(size=size)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    title: str,
) -> None:
    draw.text((42, 20), title, font=_font(32, bold=True), fill=TEXT)
    draw.text(
        (44, 62),
        f"Development scenario: {SCENARIO_SUBTITLE}",
        font=_font(19),
        fill=MUTED,
    )


def _tick_label(value: float) -> str:
    if abs(value) >= 1000.0:
        return f"{value:,.0f}"
    if abs(value) >= 10.0:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _panel_axes(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    title: str,
    y_min: float,
    y_max: float,
    y_label: str,
    *,
    x_min: float = 0.0,
    x_max: float = 23.0,
    x_ticks: tuple[int, ...] = (0, 6, 12, 18, 23),
    x_label: str = "Hour",
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=12, fill=PANEL, outline=GRID)
    draw.text(
        (left + 18, top + 12),
        title,
        font=_font(21, bold=True),
        fill=TEXT,
    )
    draw.text(
        (left + 18, top + 43),
        y_label,
        font=_font(14),
        fill=MUTED,
    )
    plot = (left + 86, top + 102, right - 24, bottom - 50)
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
    x_span = max(x_max - x_min, 1.0)
    for tick in x_ticks:
        x = round(
            plot_left
            + (float(tick) - x_min) / x_span * (plot_right - plot_left)
        )
        draw.line((x, plot_bottom, x, plot_bottom + 5), fill=MUTED, width=1)
        label = str(tick)
        label_width = draw.textlength(label, font=_font(13))
        draw.text(
            (x - label_width / 2, plot_bottom + 9),
            label,
            font=_font(13),
            fill=MUTED,
        )
    x_label_width = draw.textlength(x_label, font=_font(13))
    draw.text(
        ((plot_left + plot_right - x_label_width) / 2, bottom - 24),
        x_label,
        font=_font(13),
        fill=MUTED,
    )
    return plot


def _xy_points(
    x_values: np.ndarray,
    y_values: np.ndarray,
    plot: tuple[int, int, int, int],
    y_min: float,
    y_max: float,
    *,
    x_min: float = 0.0,
    x_max: float = 23.0,
) -> list[tuple[int, int]]:
    plot_left, plot_top, plot_right, plot_bottom = plot
    x_span = max(x_max - x_min, 1.0)
    y_span = max(y_max - y_min, 1e-12)
    return [
        (
            round(
                plot_left
                + (float(x) - x_min) / x_span * (plot_right - plot_left)
            ),
            round(
                plot_bottom
                - (float(y) - y_min) / y_span * (plot_bottom - plot_top)
            ),
        )
        for x, y in zip(x_values, y_values, strict=True)
    ]


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    color: str,
    width: int = 3,
) -> None:
    for index in range(len(points) - 1):
        if index % 2 == 0:
            draw.line((points[index], points[index + 1]), fill=color, width=width)


def _draw_series(
    draw: ImageDraw.ImageDraw,
    x_values: np.ndarray,
    y_values: np.ndarray,
    plot: tuple[int, int, int, int],
    y_min: float,
    y_max: float,
    color: str,
    *,
    width: int = 3,
    dashed: bool = False,
    x_min: float = 0.0,
    x_max: float = 23.0,
) -> None:
    points = _xy_points(
        x_values,
        y_values,
        plot,
        y_min,
        y_max,
        x_min=x_min,
        x_max=x_max,
    )
    if dashed:
        _draw_dashed_line(draw, points, color, width)
    elif len(points) > 1:
        draw.line(points, fill=color, width=width, joint="curve")
    elif points:
        x, y = points[0]
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)


def _draw_legend(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    items: list[tuple[str, str]],
    *,
    max_x: int,
) -> None:
    cursor_x = x
    cursor_y = y
    font = _font(13)
    for label, color in items:
        item_width = 32 + round(draw.textlength(label, font=font)) + 20
        if cursor_x > x and cursor_x + item_width > max_x:
            cursor_x = x
            cursor_y += 20
        draw.line(
            (cursor_x, cursor_y + 7, cursor_x + 20, cursor_y + 7),
            fill=color,
            width=4,
        )
        draw.text(
            (cursor_x + 25, cursor_y),
            label,
            font=font,
            fill=MUTED,
        )
        cursor_x += item_width


def _case_data(
    hourly_results: pd.DataFrame,
    case_name: str,
) -> pd.DataFrame:
    return (
        hourly_results.loc[hourly_results["case"] == case_name]
        .sort_values("hour")
        .reset_index(drop=True)
    )


def _hour_axis(data: pd.DataFrame) -> tuple[float, float, tuple[int, ...]]:
    last_hour = int(data["hour"].max())
    x_max = float(max(last_hour, 1))
    ticks = tuple(
        dict.fromkeys(
            round(value)
            for value in np.linspace(0.0, float(last_hour), 5)
        )
    )
    return 0.0, x_max, ticks


def _hour_interval_axis(
    data: pd.DataFrame,
) -> tuple[float, float, tuple[int, ...]]:
    first_hour = int(data["hour"].min())
    final_boundary = int(data["hour"].max()) + 1
    ticks = tuple(
        dict.fromkeys(
            round(value)
            for value in np.linspace(
                float(first_hour),
                float(final_boundary),
                5,
            )
        )
    )
    return float(first_hour), float(final_boundary), ticks


def _mark_settlement_tail(
    draw: ImageDraw.ImageDraw,
    data: pd.DataFrame,
    plot: tuple[int, int, int, int],
    x_min: float,
    x_max: float,
    *,
    interval_aligned: bool = False,
) -> None:
    tail_hours = data.loc[
        data["period_role"] == "settlement_tail", "hour"
    ].to_numpy(dtype=float)
    if len(tail_hours) == 0:
        return
    boundary_hour = float(np.min(tail_hours))
    if not interval_aligned:
        boundary_hour -= 0.5
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
        (max(plot_left + 4, plot_right - label_width - 4), plot_top + 4),
        label,
        font=_font(12),
        fill=MUTED,
    )


def _battery_power_series(
    data: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    interval_centers = data["hour"].to_numpy(dtype=float) + 0.5
    charge = data["charge_mw"].to_numpy(dtype=float)
    discharge = -data["discharge_mw"].to_numpy(dtype=float)
    return interval_centers, charge, discharge


def _soc_boundary_series(
    data: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    hours = data["hour"].to_numpy(dtype=float)
    boundary_hours = np.concatenate((hours, np.array([hours[-1] + 1.0])))
    soc = np.concatenate(
        (
            np.array([float(data["soc_start"].iloc[0])]),
            data["soc_end"].to_numpy(dtype=float),
        )
    )
    return boundary_hours, soc


def _nonnegative_limit(values: list[np.ndarray]) -> float:
    maxima = [float(np.max(value)) for value in values if value.size]
    return max(max(maxima, default=0.0) * 1.10, 1.0)


def _draw_case_lines_panel(
    draw: ImageDraw.ImageDraw,
    hourly_results: pd.DataFrame,
    bounds: tuple[int, int, int, int],
    title: str,
    column: str,
    y_label: str,
) -> None:
    values = [
        _case_data(hourly_results, case_name)[column].to_numpy(dtype=float)
        for case_name in CASE_ORDER
    ]
    y_max = _nonnegative_limit(values)
    baseline = _case_data(hourly_results, CASE_ORDER[0])
    x_min, x_max, x_ticks = _hour_axis(baseline)
    plot = _panel_axes(
        draw,
        bounds,
        title,
        0.0,
        y_max,
        y_label,
        x_min=x_min,
        x_max=x_max,
        x_ticks=x_ticks,
    )
    _mark_settlement_tail(draw, baseline, plot, x_min, x_max)
    for case_name, series in zip(CASE_ORDER, values, strict=True):
        data = _case_data(hourly_results, case_name)
        _draw_series(
            draw,
            data["hour"].to_numpy(dtype=float),
            series,
            plot,
            0.0,
            y_max,
            CASE_COLORS[case_name],
            width=4 if case_name == "joint" else 2,
            x_min=x_min,
            x_max=x_max,
        )
    left, top, right, _ = bounds
    _draw_legend(
        draw,
        left + 90,
        top + 69,
        [(CASE_LABELS[name], CASE_COLORS[name]) for name in CASE_ORDER],
        max_x=right - 18,
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


def _draw_vertical_text(
    image: Image.Image,
    text: str,
    x: int,
    center_y: int,
) -> None:
    font = _font(17, bold=True)
    box = font.getbbox(text)
    width = box[2] - box[0]
    height = box[3] - box[1]
    label = Image.new("RGBA", (width + 8, height + 8), (0, 0, 0, 0))
    label_draw = ImageDraw.Draw(label)
    label_draw.text((4 - box[0], 4 - box[1]), text, font=font, fill=TEXT)
    rotated = label.rotate(90, expand=True)
    image.paste(rotated, (x, center_y - rotated.height // 2), rotated)


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


def _prepare_daily_case_cost_inputs(
    daily_metrics: pd.DataFrame,
    hourly_dispatch: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], tuple[pd.Timestamp, ...], float, float]:
    daily_required = [
        "case",
        "day",
        "operating_cost_cny",
        "settlement_tail_operating_cost_cny",
    ]
    hourly_required = ["case", "day", "timestamp_lst", "period_role"]
    for dataframe_name, dataframe, required in (
        ("daily_metrics", daily_metrics, daily_required),
        ("hourly_dispatch", hourly_dispatch, hourly_required),
    ):
        missing = [
            column for column in required if column not in dataframe.columns
        ]
        if missing:
            raise ValueError(
                f"{dataframe_name} missing required columns: "
                f"{', '.join(missing)}"
            )

    for column in (
        "day",
        "operating_cost_cny",
        "settlement_tail_operating_cost_cny",
    ):
        if not pd.api.types.is_numeric_dtype(daily_metrics[column]):
            raise ValueError(
                f"daily_metrics numeric column {column} must be numeric"
            )
        values = daily_metrics[column].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(
                f"daily_metrics numeric column {column} contains "
                "non-finite values"
            )
    daily_days = daily_metrics["day"].to_numpy(dtype=float)
    if not np.equal(daily_days, np.round(daily_days)).all():
        raise ValueError("daily_metrics day values must be integers")
    for column in (
        "operating_cost_cny",
        "settlement_tail_operating_cost_cny",
    ):
        if (
            daily_metrics[column].to_numpy(dtype=float)
            < -NONNEGATIVE_TOLERANCE
        ).any():
            raise ValueError(
                f"daily_metrics cost column {column} contains values below "
                f"-{NONNEGATIVE_TOLERANCE}"
            )

    rows_by_case: dict[str, pd.DataFrame] = {}
    expected_days: tuple[int, ...] | None = None
    all_costs: list[float] = []
    for case_name in CASE_ORDER:
        rows = (
            daily_metrics.loc[daily_metrics["case"] == case_name]
            .sort_values("day")
            .reset_index(drop=True)
        )
        if rows.empty:
            raise ValueError(f"daily_metrics missing {case_name}")
        if not rows["day"].is_unique:
            raise ValueError(
                f"daily_metrics case {case_name} day values must be unique"
            )
        case_days = tuple(rows["day"].astype(int).tolist())
        if expected_days is None:
            expected_days = case_days
        elif case_days != expected_days:
            raise ValueError(
                "daily_metrics cases must contain identical day values"
            )
        rows_by_case[case_name] = rows
        all_costs.extend(rows["operating_cost_cny"].to_numpy(dtype=float))

    assert expected_days is not None
    baseline_analysis = hourly_dispatch.loc[
        (hourly_dispatch["case"] == "renewables_only")
        & (hourly_dispatch["period_role"] == "analysis")
    ].copy()
    if baseline_analysis.empty:
        raise ValueError(
            "hourly_dispatch missing renewables_only analysis rows"
        )
    if not pd.api.types.is_numeric_dtype(baseline_analysis["day"]):
        raise ValueError("hourly_dispatch numeric column day must be numeric")
    baseline_day_values = baseline_analysis["day"].to_numpy(dtype=float)
    if (
        not np.isfinite(baseline_day_values).all()
        or not np.equal(baseline_day_values, np.round(baseline_day_values)).all()
    ):
        raise ValueError("hourly_dispatch day values must be finite integers")
    timestamps = pd.to_datetime(
        baseline_analysis["timestamp_lst"],
        errors="coerce",
    )
    if timestamps.isna().any():
        raise ValueError("hourly_dispatch timestamp_lst contains invalid values")
    baseline_analysis["date"] = timestamps.dt.normalize()
    date_counts = baseline_analysis.groupby("day")["date"].nunique()
    if not date_counts.eq(1).all():
        raise ValueError(
            "hourly_dispatch analysis rows must map each day to one date"
        )
    date_by_day = (
        baseline_analysis.groupby("day", sort=True)["date"].first().to_dict()
    )
    missing_dates = [day for day in expected_days if day not in date_by_day]
    if missing_dates:
        raise ValueError(
            "hourly_dispatch missing analysis dates for days: "
            f"{missing_dates}"
        )
    dates = tuple(pd.Timestamp(date_by_day[day]) for day in expected_days)

    minimum_cost = float(min(all_costs))
    maximum_cost = float(max(all_costs))
    padding = max(
        (maximum_cost - minimum_cost) * 0.10,
        maximum_cost * 0.03,
        1.0,
    )
    y_min = max(0.0, minimum_cost - padding)
    y_max = maximum_cost + padding
    return rows_by_case, dates, y_min, y_max


def _draw_daily_case_cost_plot(
    rows: pd.DataFrame,
    dates: tuple[pd.Timestamp, ...],
    case_name: str,
    y_min: float,
    y_max: float,
    output_path: Path,
) -> None:
    costs = rows["operating_cost_cny"].to_numpy(dtype=float)
    x_values = np.arange(len(costs), dtype=float)
    image = Image.new("RGB", (1800, 900), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, f"Daily Operating Cost: {CASE_LABELS[case_name]}")

    panel = (18, 100, 1782, 890)
    draw.rounded_rectangle(panel, radius=12, fill=PANEL, outline=GRID)
    draw.text(
        (38, 116),
        "24-hour analysis cost | common vertical scale across all cases",
        font=_font(20, bold=True),
        fill=TEXT,
    )
    tail_rows = rows.loc[
        rows["settlement_tail_operating_cost_cny"] > NONNEGATIVE_TOLERANCE
    ]
    if not tail_rows.empty:
        tail_row = tail_rows.iloc[-1]
        tail_day = int(tail_row["day"])
        tail_index = rows.index[rows["day"].astype(int) == tail_day][0]
        tail_date = dates[int(tail_index)].strftime("%Y-%m-%d")
        tail_cost = float(tail_row["settlement_tail_operating_cost_cny"])
        tail_label = (
            f"3 h settlement tail after {tail_date}: "
            f"CNY {tail_cost:,.2f} (excluded from line)"
        )
        tail_width = draw.textlength(tail_label, font=_font(15))
        draw.text(
            (1740 - tail_width, 122),
            tail_label,
            font=_font(15),
            fill=MUTED,
        )

    plot = (175, 205, 1745, 735)
    plot_left, plot_top, plot_right, plot_bottom = plot
    draw.rectangle(plot, outline=MUTED, width=1)
    for index in range(6):
        fraction = index / 5.0
        y = round(plot_bottom - fraction * (plot_bottom - plot_top))
        value = y_min + fraction * (y_max - y_min)
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
        "Operating cost (CNY per 24 h)",
        35,
        (plot_top + plot_bottom) // 2,
    )

    slot_width = (plot_right - plot_left) / max(len(costs), 1)
    bar_centers = [
        round(plot_left + slot_width * (index + 0.5))
        for index in range(len(costs))
    ]
    tick_indices = sorted(
        set(
            np.linspace(0, len(dates) - 1, min(5, len(dates)))
            .round()
            .astype(int)
            .tolist()
        )
    )
    x_max = max(float(len(costs) - 1), 1.0)
    for index in tick_indices:
        x = bar_centers[index]
        draw.line((x, plot_bottom, x, plot_bottom + 5), fill=MUTED, width=1)
        label = dates[index].strftime("%Y-%m-%d")
        label_width = draw.textlength(label, font=_font(13))
        draw.text(
            (x - label_width / 2, plot_bottom + 11),
            label,
            font=_font(13),
            fill=MUTED,
        )
    date_width = draw.textlength("Date", font=_font(14))
    draw.text(
        ((plot_left + plot_right - date_width) / 2, plot_bottom + 42),
        "Date",
        font=_font(14),
        fill=MUTED,
    )

    value_points = _xy_points(
        x_values,
        costs,
        plot,
        y_min,
        y_max,
        x_min=0.0,
        x_max=x_max,
    )
    points = [
        (bar_centers[index], y)
        for index, (_, y) in enumerate(value_points)
    ]
    color = CASE_COLORS[case_name]
    bar_width = max(14, min(38, round(slot_width * 0.65)))
    for x, y in points:
        draw.rectangle(
            (
                x - bar_width // 2,
                y,
                x + bar_width // 2,
                plot_bottom,
            ),
            fill=color,
        )

    minimum_index = int(np.argmin(costs))
    maximum_index = int(np.argmax(costs))
    for role, index in (("Min", minimum_index), ("Max", maximum_index)):
        x, y = points[index]
        draw.ellipse(
            (x - 9, y - 9, x + 9, y + 9),
            outline=TEXT,
            width=2,
        )
        label = (
            f"{role} {dates[index].strftime('%Y-%m-%d')} | "
            f"CNY {costs[index]:,.2f}"
        )
        label_width = draw.textlength(label, font=_font(14, bold=True))
        label_y = y - 30 if y > plot_top + 45 else y + 14
        label_x = min(
            max(plot_left + 5, x - label_width / 2),
            plot_right - label_width - 5,
        )
        draw.text(
            (label_x, label_y),
            label,
            font=_font(14, bold=True),
            fill=TEXT,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def make_daily_case_cost_plots(
    daily_metrics: pd.DataFrame,
    hourly_dispatch: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    rows_by_case, dates, y_min, y_max = _prepare_daily_case_cost_inputs(
        daily_metrics,
        hourly_dispatch,
    )
    output_dir = Path(output_dir)
    output_paths = [
        output_dir / DAILY_COST_PLOT_FILENAMES[case_name]
        for case_name in CASE_ORDER
    ]
    for case_name, output_path in zip(
        CASE_ORDER,
        output_paths,
        strict=True,
    ):
        _draw_daily_case_cost_plot(
            rows_by_case[case_name],
            dates,
            case_name,
            y_min,
            y_max,
            output_path,
        )
    return output_paths


def _validated_task_delay_rows(
    daily_metrics: pd.DataFrame,
    day_number: int | None,
) -> dict[str, pd.DataFrame]:
    required_columns = [
        "case",
        "day",
        "primary_task_delay_cpu_hours",
        "secondary_task_delay_cpu_hours",
    ]
    missing_columns = [
        column for column in required_columns
        if column not in daily_metrics.columns
    ]
    if missing_columns:
        raise ValueError(
            "daily_metrics missing required columns: "
            f"{', '.join(missing_columns)}"
        )
    for column in required_columns[1:]:
        if not pd.api.types.is_numeric_dtype(daily_metrics[column]):
            raise ValueError(
                f"daily_metrics numeric column {column} must be numeric"
            )
        values = daily_metrics[column].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(
                f"daily_metrics numeric column {column} contains "
                "non-finite values"
            )
    day_values = daily_metrics["day"].to_numpy(dtype=float)
    if not np.equal(day_values, np.round(day_values)).all():
        raise ValueError("daily_metrics day values must be integers")
    for column in required_columns[2:]:
        if (
            daily_metrics[column].to_numpy(dtype=float)
            < -NONNEGATIVE_TOLERANCE
        ).any():
            raise ValueError(
                f"daily_metrics delay column {column} contains values "
                f"below -{NONNEGATIVE_TOLERANCE}"
            )
    if day_number is not None:
        if isinstance(day_number, bool) or not isinstance(day_number, int):
            raise TypeError("day_number 必须为整数。")
        daily_metrics = daily_metrics.loc[
            daily_metrics["day"] == day_number
        ]

    rows_by_case: dict[str, pd.DataFrame] = {}
    expected_days: tuple[int, ...] | None = None
    for case_name in TASK_DELAY_CASES:
        rows = (
            daily_metrics.loc[daily_metrics["case"] == case_name]
            .sort_values("day")
            .reset_index(drop=True)
        )
        if rows.empty:
            suffix = f" day {day_number}" if day_number is not None else ""
            raise ValueError(f"daily_metrics missing {case_name}{suffix}")
        if not rows["day"].is_unique:
            raise ValueError(
                f"daily_metrics case {case_name} day values must be unique"
            )
        case_days = tuple(rows["day"].astype(int).tolist())
        if expected_days is None:
            expected_days = case_days
        elif case_days != expected_days:
            raise ValueError(
                "daily_metrics task-delay cases must contain identical days"
            )
        rows_by_case[case_name] = rows
    return rows_by_case


def _draw_single_day_task_delay_objective_plot(
    rows_by_case: dict[str, pd.DataFrame],
    output_path: Path,
    day_number: int,
) -> Path:
    values = np.array(
        [
            float(rows_by_case[case_name].iloc[0][column])
            for case_name in TASK_DELAY_CASES
            for column in (
                "primary_task_delay_cpu_hours",
                "secondary_task_delay_cpu_hours",
            )
        ],
        dtype=float,
    )
    y_max = max(float(np.max(values)) * 1.18, 1.0)
    image = Image.new("RGB", (1800, 720), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(
        draw,
        f"Day {day_number:02d} Primary vs Secondary Weighted Task Delay",
    )

    panel = (18, 100, 1782, 710)
    draw.rounded_rectangle(panel, radius=12, fill=PANEL, outline=GRID)
    draw.text(
        (38, 116),
        "Task-shifting cases | lower is better",
        font=_font(21, bold=True),
        fill=TEXT,
    )
    _draw_legend(
        draw,
        730,
        120,
        [
            ("Primary cost-optimal", "#94A3B8"),
            ("Secondary: Renewables + shift", CASE_COLORS["renewables_shift"]),
            ("Secondary: Joint", CASE_COLORS["joint"]),
        ],
        max_x=1745,
    )

    plot = (155, 190, 1745, 555)
    plot_left, plot_top, plot_right, plot_bottom = plot
    draw.rectangle(plot, outline=MUTED, width=1)
    for index in range(5):
        fraction = index / 4.0
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
        "Weighted delay (p.u.·h)",
        38,
        (plot_top + plot_bottom) // 2,
    )

    centers = (600, 1300)
    bar_width = 145
    for center, case_name in zip(centers, TASK_DELAY_CASES, strict=True):
        row = rows_by_case[case_name].iloc[0]
        primary = float(row["primary_task_delay_cpu_hours"])
        secondary = float(row["secondary_task_delay_cpu_hours"])
        primary_top = round(
            plot_bottom - primary / y_max * (plot_bottom - plot_top)
        )
        secondary_top = round(
            plot_bottom - secondary / y_max * (plot_bottom - plot_top)
        )
        primary_bounds = (
            center - bar_width - 8,
            primary_top,
            center - 8,
            plot_bottom,
        )
        secondary_bounds = (
            center + 8,
            secondary_top,
            center + bar_width + 8,
            plot_bottom,
        )
        draw.rectangle(primary_bounds, fill="#94A3B8")
        draw.rectangle(secondary_bounds, fill=CASE_COLORS[case_name])
        for value, bounds in (
            (primary, primary_bounds),
            (secondary, secondary_bounds),
        ):
            label = f"{value:.4f}"
            label_width = draw.textlength(label, font=_font(16, bold=True))
            draw.text(
                (
                    (bounds[0] + bounds[2] - label_width) / 2,
                    max(plot_top + 3, bounds[1] - 27),
                ),
                label,
                font=_font(16, bold=True),
                fill=TEXT,
            )
        case_label = CASE_LABELS[case_name]
        case_label_width = draw.textlength(
            case_label,
            font=_font(17, bold=True),
        )
        draw.text(
            (center - case_label_width / 2, plot_bottom + 18),
            case_label,
            font=_font(17, bold=True),
            fill=TEXT,
        )
        reduction = primary - secondary
        reduction_pct = (
            reduction / primary * 100.0 if primary > 0.0 else 0.0
        )
        reduction_label = (
            f"Reduction {reduction:.4f} p.u.·h ({reduction_pct:.2f}%)"
        )
        reduction_width = draw.textlength(
            reduction_label,
            font=_font(15, bold=True),
        )
        draw.text(
            (center - reduction_width / 2, plot_bottom + 49),
            reduction_label,
            font=_font(15, bold=True),
            fill=CASE_COLORS[case_name],
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def make_task_delay_objective_plot(
    daily_metrics: pd.DataFrame,
    output_path: Path,
    *,
    day_number: int | None = None,
) -> Path:
    rows_by_case = _validated_task_delay_rows(daily_metrics, day_number)
    if day_number is not None:
        return _draw_single_day_task_delay_objective_plot(
            rows_by_case,
            output_path,
            day_number,
        )
    all_values = np.concatenate(
        [
            rows[
                [
                    "primary_task_delay_cpu_hours",
                    "secondary_task_delay_cpu_hours",
                ]
            ].to_numpy(dtype=float).reshape(-1)
            for rows in rows_by_case.values()
        ]
    )
    y_max = max(float(np.max(all_values)) * 1.15, 1.0)
    image = Image.new("RGB", (1800, 1050), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, "Primary vs Secondary Weighted Task Delay by Day")
    panel_bounds = ((18, 100, 1782, 565), (18, 580, 1782, 1045))

    for bounds, case_name in zip(
        panel_bounds,
        TASK_DELAY_CASES,
        strict=True,
    ):
        rows = rows_by_case[case_name]
        days = rows["day"].to_numpy(dtype=int)
        primary = rows["primary_task_delay_cpu_hours"].to_numpy(
            dtype=float
        )
        secondary = rows["secondary_task_delay_cpu_hours"].to_numpy(
            dtype=float
        )
        primary_total = float(primary.sum())
        secondary_total = float(secondary.sum())
        reduction = primary_total - secondary_total
        reduction_pct = (
            reduction / primary_total * 100.0
            if primary_total > 0.0
            else 0.0
        )
        panel_title = (
            f"{CASE_LABELS[case_name]} | reduction "
            f"{reduction:.4f} p.u.·h ({reduction_pct:.2f}%)"
        )
        if len(days) == 1:
            x_ticks = (int(days[0]),)
        else:
            preferred_ticks = (1, 7, 14, 21, 28)
            x_ticks = tuple(
                tick for tick in preferred_ticks
                if int(days[0]) <= tick <= int(days[-1])
            )
            if int(days[0]) not in x_ticks:
                x_ticks = (int(days[0]), *x_ticks)
            if int(days[-1]) not in x_ticks:
                x_ticks = (*x_ticks, int(days[-1]))
        x_min = float(days[0]) - 0.5
        x_max = float(days[-1]) + 0.5
        plot = _panel_axes(
            draw,
            bounds,
            panel_title,
            0.0,
            y_max,
            "Weighted delay (p.u.·h)",
            x_min=x_min,
            x_max=x_max,
            x_ticks=x_ticks,
            x_label="Day",
        )
        _draw_legend(
            draw,
            bounds[0] + 500,
            bounds[1] + 48,
            [
                ("Primary cost-optimal delay", "#94A3B8"),
                ("Secondary delay-minimized", CASE_COLORS[case_name]),
            ],
            max_x=bounds[2] - 24,
        )
        plot_left, plot_top, plot_right, plot_bottom = plot
        plot_width = plot_right - plot_left
        x_span = max(x_max - x_min, 1.0)
        slot_width = plot_width / max(len(days), 1)
        bar_width = max(4, min(120, round(slot_width * 0.32)))
        for day, primary_value, secondary_value in zip(
            days,
            primary,
            secondary,
            strict=True,
        ):
            center = round(
                plot_left
                + (float(day) - x_min) / x_span * plot_width
            )
            primary_top = round(
                plot_bottom
                - primary_value / y_max * (plot_bottom - plot_top)
            )
            secondary_top = round(
                plot_bottom
                - secondary_value / y_max * (plot_bottom - plot_top)
            )
            draw.rectangle(
                (
                    center - bar_width - 1,
                    primary_top,
                    center - 1,
                    plot_bottom,
                ),
                fill="#94A3B8",
            )
            draw.rectangle(
                (
                    center + 1,
                    secondary_top,
                    center + bar_width + 1,
                    plot_bottom,
                ),
                fill=CASE_COLORS[case_name],
            )
            if len(days) == 1:
                for value, x, top in (
                    (primary_value, center - bar_width // 2 - 1, primary_top),
                    (secondary_value, center + bar_width // 2 + 1, secondary_top),
                ):
                    label = f"{value:.4f}"
                    label_width = draw.textlength(label, font=_font(14))
                    draw.text(
                        (x - label_width / 2, max(plot_top + 2, top - 23)),
                        label,
                        font=_font(14, bold=True),
                        fill=TEXT,
                    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def _prepare_daily_plot_inputs(
    hourly_results: pd.DataFrame,
    day_number: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if isinstance(day_number, bool) or not isinstance(day_number, int):
        raise TypeError("day_number 必须为整数。")
    if not 1 <= day_number <= 28:
        raise ValueError("day_number 必须位于 1..28。")
    required_columns = [
        "case",
        "day",
        "period_role",
        *HOURLY_NUMERIC_COLUMNS,
    ]
    missing_columns = [
        column
        for column in required_columns
        if column not in hourly_results.columns
    ]
    if missing_columns:
        raise ValueError(
            "hourly_results missing required columns: "
            f"{', '.join(missing_columns)}"
        )
    if not pd.api.types.is_numeric_dtype(hourly_results["day"]):
        raise ValueError("hourly_results numeric column day must be numeric")
    day_values = hourly_results["day"].to_numpy(dtype=float)
    if (
        not np.isfinite(day_values).all()
        or not np.equal(day_values, np.round(day_values)).all()
    ):
        raise ValueError("hourly_results day values must be finite integers")

    selected = hourly_results.loc[
        hourly_results["day"] == day_number
    ].copy()
    actual_cases = selected["case"].drop_duplicates().tolist()
    if set(actual_cases) != set(CASE_ORDER):
        raise ValueError(
            "hourly_results case set invalid for selected day: "
            f"found={actual_cases}"
        )

    expected_hours = 27 if day_number == 28 else 24
    expected_roles = (
        ("analysis",) * 24 + ("settlement_tail",) * 3
        if day_number == 28
        else ("analysis",) * 24
    )
    daily_cases = []
    for case_name in CASE_ORDER:
        case_rows = (
            selected.loc[selected["case"] == case_name]
            .sort_values("hour", kind="stable")
            .reset_index(drop=True)
        )
        if len(case_rows) != expected_hours:
            raise ValueError(
                f"hourly_results case {case_name} day {day_number} must "
                f"have exactly {expected_hours} rows; found {len(case_rows)}"
            )
        if tuple(case_rows["period_role"].tolist()) != expected_roles:
            raise ValueError(
                f"hourly_results case {case_name} day {day_number} has "
                "invalid period_role sequence"
            )
        case_rows["hour"] = np.arange(expected_hours, dtype=int)
        daily_cases.append(case_rows)

    daily_results = pd.concat(daily_cases, ignore_index=True)
    daily_metrics = pd.DataFrame(
        [
            {
                "case": case_name,
                **summarize_costs(
                    daily_results.loc[daily_results["case"] == case_name]
                ),
            }
            for case_name in CASE_ORDER
        ]
    )
    _validate_plot_inputs(
        daily_results,
        daily_metrics,
        expected_period_roles=expected_roles,
    )
    return daily_results, daily_metrics


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
    daily_output_dir.mkdir(parents=True, exist_ok=True)
    scope = "24+3 h" if day_number == 28 else "24 h"

    _draw_day_ahead_power_results(
        daily_results,
        daily_output_dir / PLOT_FILENAMES[0],
        f"Day {day_number:02d} {scope} Day-Ahead Power Results",
    )
    _draw_compute_scheduling_results(
        daily_results,
        daily_output_dir / PLOT_FILENAMES[1],
        f"Day {day_number:02d} {scope} Day-Ahead Compute Scheduling",
    )
    _draw_battery_operation_results(
        daily_results,
        daily_output_dir / PLOT_FILENAMES[2],
        f"Day {day_number:02d} {scope} Day-Ahead Battery Operation",
    )
    _draw_renewable_dispatch_results(
        daily_results,
        daily_output_dir / PLOT_FILENAMES[3],
        f"Day {day_number:02d} {scope} Day-Ahead Renewable Dispatch",
    )
    _draw_cost_comparison(
        daily_metrics,
        daily_output_dir / PLOT_FILENAMES[4],
        f"Day {day_number:02d} Operating Cost",
        (
            "Operating cost (CNY; analysis + settlement tail)"
            if day_number == 28
            else "Operating cost (CNY; analysis)"
        ),
    )
    return daily_output_dir


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
