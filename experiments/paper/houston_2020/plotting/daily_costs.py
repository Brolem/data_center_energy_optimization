from __future__ import annotations

from pathlib import Path

import pandas as pd

from dc_energy_opt.reporting import make_daily_case_cost_plots


def plot_daily_cost_results(
    *,
    daily_metrics: Path,
    hourly_dispatch: Path,
    output_dir: Path,
) -> None:
    if not daily_metrics.is_file():
        raise FileNotFoundError(
            f"daily_metrics.csv 不存在: {daily_metrics}"
        )
    if not hourly_dispatch.is_file():
        raise FileNotFoundError(
            f"hourly_dispatch.csv 不存在: {hourly_dispatch}"
        )
    daily_metrics_frame = pd.read_csv(daily_metrics)
    hourly_dispatch_frame = pd.read_csv(hourly_dispatch)
    make_daily_case_cost_plots(
        daily_metrics_frame,
        hourly_dispatch_frame,
        output_dir,
    )
