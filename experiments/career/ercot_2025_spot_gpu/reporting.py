from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


_WIDTH = 1_600
_HEIGHT = 1_100
_MARGIN_LEFT = 110
_MARGIN_RIGHT = 60
_FONT = ImageFont.load_default()
_ACTUAL_COLOR = "#1f2937"
_BASELINE_COLOR = "#2563eb"
_FEATURE_COLOR = "#dc2626"

_TARGETS = (
    ("dam_lz_houston_usd_per_mwh", "DAM price (USD/MWh)"),
    ("erco_solar_generation_mwh", "ERCO solar signal (MWh)"),
    ("erco_wind_generation_mwh", "ERCO wind signal (MWh)"),
)


def _line_points(
    values: np.ndarray,
    *,
    left: int,
    right: int,
    top: int,
    bottom: int,
    lower: float,
    upper: float,
) -> list[tuple[float, float]]:
    if len(values) == 1:
        x_values = np.array([(left + right) / 2.0])
    else:
        x_values = np.linspace(left, right, len(values))
    normalized = (values - lower) / (upper - lower)
    y_values = bottom - normalized * (bottom - top)
    return list(zip(x_values.tolist(), y_values.tolist(), strict=True))


def _numeric_column(frame: pd.DataFrame, column: str) -> np.ndarray:
    if column not in frame:
        raise ValueError(f"绘图输入缺少字段: {column}")
    values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
    if len(values) == 0 or not np.isfinite(values).all():
        raise ValueError(f"绘图字段必须为非空有限数值: {column}")
    return values


def _draw_disclaimer(draw: ImageDraw.ImageDraw, *, y: int) -> None:
    lines = (
        "Counterfactual replay only: this is not an Alibaba operation in ERCOT or Houston.",
        "ERCO generation is a system-level scenario signal, not local data-center generation.",
        "GPU-hour workload mapped to utilization is a proxy, not measured power.",
    )
    for index, line in enumerate(lines):
        draw.text((_MARGIN_LEFT, y + index * 18), line, fill="#4b5563", font=_FONT)


def write_forecast_comparison_figure(
    forecast_table: pd.DataFrame,
    output_path: Path,
) -> None:
    """Write one three-panel forecast comparison PNG from generated test forecasts."""
    image = Image.new("RGB", (_WIDTH, _HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (_MARGIN_LEFT, 28),
        "Test forecasts: actual vs. previous-day baseline vs. ridge feature model",
        fill="#111827",
        font=_FONT,
    )
    draw.text(
        (_MARGIN_LEFT, 48),
        "Forecast decisions use predicted signals; actual signals are retained for evaluation.",
        fill="#4b5563",
        font=_FONT,
    )
    draw.text(
        (_MARGIN_LEFT, 72),
        "Actual", fill=_ACTUAL_COLOR, font=_FONT
    )
    draw.text(
        (_MARGIN_LEFT + 70, 72), "Baseline", fill=_BASELINE_COLOR, font=_FONT)
    draw.text(
        (_MARGIN_LEFT + 170, 72), "Feature model", fill=_FEATURE_COLOR, font=_FONT)

    panel_top = 120
    panel_height = 250
    chart_left = _MARGIN_LEFT
    chart_right = _WIDTH - _MARGIN_RIGHT
    for target_index, (target, label) in enumerate(_TARGETS):
        top = panel_top + target_index * panel_height
        bottom = top + 180
        actual = _numeric_column(forecast_table, f"actual_{target}")
        baseline = _numeric_column(forecast_table, f"baseline_{target}")
        feature = _numeric_column(forecast_table, f"feature_model_{target}")
        lower = float(min(actual.min(), baseline.min(), feature.min()))
        upper = float(max(actual.max(), baseline.max(), feature.max()))
        if upper - lower < 1e-12:
            lower -= 0.5
            upper += 0.5
        padding = (upper - lower) * 0.05
        lower -= padding
        upper += padding
        draw.rectangle(
            (chart_left, top, chart_right, bottom), outline="#9ca3af", width=1
        )
        draw.text((chart_left, top - 16), label, fill="#111827", font=_FONT)
        draw.text((8, top), f"{upper:.1f}", fill="#4b5563", font=_FONT)
        draw.text((8, bottom - 10), f"{lower:.1f}", fill="#4b5563", font=_FONT)
        for values, color in (
            (actual, _ACTUAL_COLOR),
            (baseline, _BASELINE_COLOR),
            (feature, _FEATURE_COLOR),
        ):
            draw.line(
                _line_points(
                    values,
                    left=chart_left,
                    right=chart_right,
                    top=top,
                    bottom=bottom,
                    lower=lower,
                    upper=upper,
                ),
                fill=color,
                width=2,
            )
    _draw_disclaimer(draw, y=920)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def _bar_geometry(
    values: np.ndarray,
    *,
    left: int,
    right: int,
    top: int,
    bottom: int,
) -> tuple[float, float, float]:
    lower = min(0.0, float(values.min()))
    upper = max(0.0, float(values.max()))
    if upper - lower < 1e-12:
        upper = lower + 1.0
    zero = bottom - (0.0 - lower) / (upper - lower) * (bottom - top)
    return lower, upper, zero


def _draw_bars(
    draw: ImageDraw.ImageDraw,
    *,
    values: np.ndarray,
    labels: list[str],
    title: str,
    top: int,
    bottom: int,
    color: str,
) -> None:
    left = _MARGIN_LEFT
    right = _WIDTH - _MARGIN_RIGHT
    lower, upper, zero = _bar_geometry(
        values, left=left, right=right, top=top, bottom=bottom
    )
    draw.rectangle((left, top, right, bottom), outline="#9ca3af", width=1)
    draw.line((left, zero, right, zero), fill="#6b7280", width=1)
    draw.text((left, top - 16), title, fill="#111827", font=_FONT)
    draw.text((12, top), f"{upper:.2f}", fill="#4b5563", font=_FONT)
    draw.text((12, bottom - 10), f"{lower:.2f}", fill="#4b5563", font=_FONT)
    step = (right - left) / len(values)
    bar_width = min(150, step * 0.55)
    for index, value in enumerate(values):
        center = left + step * (index + 0.5)
        value_y = bottom - (value - lower) / (upper - lower) * (bottom - top)
        draw.rectangle(
            (center - bar_width / 2, min(zero, value_y), center + bar_width / 2, max(zero, value_y)),
            fill=color,
        )
        draw.text(
            (center - bar_width / 2, bottom + 8), labels[index], fill="#374151", font=_FONT
        )
        draw.text(
            (center - bar_width / 2, min(zero, value_y) - 14),
            f"{value:.2f}",
            fill="#374151",
            font=_FONT,
        )


def write_settlement_comparison_figure(
    decision_metrics: pd.DataFrame,
    output_path: Path,
) -> None:
    """Write one actual-settlement and decision-regret comparison PNG."""
    required_columns = (
        "case",
        "actual_grid_settlement_usd",
        "decision_regret_usd",
    )
    if any(column not in decision_metrics for column in required_columns):
        raise ValueError("决策指标表缺少绘图字段。")
    labels = decision_metrics["case"].astype(str).tolist()
    settlement = _numeric_column(decision_metrics, "actual_grid_settlement_usd")
    regret = _numeric_column(decision_metrics, "decision_regret_usd")
    image = Image.new("RGB", (_WIDTH, _HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (_MARGIN_LEFT, 28),
        "Actual settlement and decision regret by energy-information case",
        fill="#111827",
        font=_FONT,
    )
    _draw_bars(
        draw,
        values=settlement,
        labels=labels,
        title="Actual grid settlement (USD)",
        top=100,
        bottom=390,
        color="#2563eb",
    )
    _draw_bars(
        draw,
        values=regret,
        labels=labels,
        title="Decision regret relative to oracle actual (USD)",
        top=520,
        bottom=810,
        color="#dc2626",
    )
    _draw_disclaimer(draw, y=900)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
