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
