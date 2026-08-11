from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from .metrics import summarize_costs
from .plot_main import (
    _draw_battery_operation_results,
    _draw_compute_scheduling_results,
    _draw_cost_comparison,
    _draw_day_ahead_power_results,
    _draw_renewable_dispatch_results,
)
from .plot_shared import (
    BACKGROUND,
    CASE_COLORS,
    CASE_LABELS,
    CASE_ORDER,
    DAILY_COST_PLOT_FILENAMES,
    GRID,
    HOURLY_NUMERIC_COLUMNS,
    MUTED,
    NONNEGATIVE_TOLERANCE,
    PANEL,
    PLOT_FILENAMES,
    TASK_DELAY_CASES,
    TEXT,
    _draw_header,
    _draw_legend,
    _draw_vertical_text,
    _font,
    _panel_axes,
    _tick_label,
    _validate_plot_inputs,
    _xy_points,
)

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
