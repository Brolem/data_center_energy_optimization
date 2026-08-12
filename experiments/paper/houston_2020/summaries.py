from __future__ import annotations

import pandas as pd

from experiments.paper.houston_2020.day_ahead import ExperimentResult


FORMAL_CASES = (
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
)


def format_experiment_objective_summary(result: ExperimentResult) -> str:
    baseline_dispatch = result.hourly_dispatch.loc[
        result.hourly_dispatch["case"] == "renewables_only"
    ]
    if baseline_dispatch.empty:
        raise ValueError("hourly_dispatch 缺少 renewables_only")

    grid_only_cost = float(
        (
            baseline_dispatch["dc_power_mw"]
            * baseline_dispatch["electricity_price_cny_per_kwh"]
            * 1000.0
        ).sum()
    )
    required_grid_peak = float(baseline_dispatch["dc_power_mw"].max())
    ordered_metrics = (
        result.case_metrics.set_index("case").loc[list(FORMAL_CASES)].reset_index()
    )
    renewables_only_cost = float(
        ordered_metrics.loc[
            ordered_metrics["case"] == "renewables_only",
            "operating_cost_cny",
        ].iloc[0]
    )
    renewable_contribution = grid_only_cost - renewables_only_cost
    renewable_contribution_pct = (
        renewable_contribution / grid_only_cost * 100.0
        if grid_only_cost > 0.0
        else 0.0
    )

    lines = [
        f"Grid-only accounting baseline: {grid_only_cost:.4f} CNY",
        f"Required grid peak: {required_grid_peak:.4f} MW",
        f"Renewables-only cost: {renewables_only_cost:.4f} CNY",
        (
            "Wind + solar contribution: "
            f"{renewable_contribution:.4f} CNY "
            f"({renewable_contribution_pct:.4f}%)"
        ),
        "",
        "Formal optimization objectives:",
        (
            f"{'case':<24} {'status':<10} {'operating_cost':>16} "
            f"{'saving':>12} {'total_delay':>14} {'max_delay':>10}"
        ),
    ]
    for row in ordered_metrics.itertuples(index=False):
        lines.append(
            f"{row.case:<24} {row.status:<10} "
            f"{float(row.operating_cost_cny):>16.4f} "
            f"{float(row.operating_cost_savings_vs_renewables_only_pct):>11.4f}% "
            f"{float(row.total_task_delay_cpu_hours):>14.4f} "
            f"{int(row.maximum_task_delay_h):>10d}"
        )
    return "\n".join(lines)


def format_sensitivity_summary(metrics: pd.DataFrame) -> str:
    lines = ["Flex-ratio sensitivity summary:"]
    for scenario in ("renewables_shift", "joint"):
        rows = metrics.loc[metrics["scenario"] == scenario].sort_values(
            "flex_ratio"
        )
        if rows.empty:
            raise ValueError(f"敏感性结果缺少场景 {scenario}。")
        baseline = rows.iloc[0]
        minimum = rows.loc[rows["operating_cost_cny"].idxmin()]
        onset = rows["saturation_onset"].dropna()
        onset_text = f"{float(onset.iloc[0]):.2f}" if not onset.empty else "not detected"
        lines.append(
            f"{scenario}: baseline={float(baseline['operating_cost_cny']):.4f} CNY; "
            f"minimum at flex_ratio={float(minimum['flex_ratio']):.2f}, "
            f"cost={float(minimum['operating_cost_cny']):.4f} CNY, "
            f"saving={float(minimum['cost_savings_pct']):.4f}%; "
            f"saturation={onset_text}"
        )
    return "\n".join(lines)


def format_storage_scale_sensitivity_summary(metrics: pd.DataFrame) -> str:
    required_columns = (
        "storage_scale",
        "storage_base_savings_cny",
        "storage_shift_savings_cny",
        "storage_effect_on_shift_cny",
    )
    missing_columns = [
        column for column in required_columns if column not in metrics
    ]
    if missing_columns:
        raise ValueError(
            "storage-scale sensitivity metrics missing columns: "
            f"{', '.join(missing_columns)}"
        )
    lines = ["Storage-scale sensitivity summary:"]
    for row in metrics.itertuples(index=False):
        lines.append(
            f"{row.storage_scale}: "
            f"storage base saving={float(row.storage_base_savings_cny):.4f} CNY; "
            f"shift saving with storage={float(row.storage_shift_savings_cny):.4f} CNY; "
            f"storage effect on shift={float(row.storage_effect_on_shift_cny):.4f} CNY"
        )
    return "\n".join(lines)


def format_storage_energy_power_sensitivity_summary(
    metrics: pd.DataFrame,
) -> str:
    required_columns = (
        "battery_energy_mwh",
        "battery_power_mw",
        "joint_cost_cny",
        "storage_effect_on_shift_cny",
    )
    missing_columns = [
        column for column in required_columns if column not in metrics
    ]
    if missing_columns:
        raise ValueError(
            "storage energy-power sensitivity metrics missing columns: "
            f"{', '.join(missing_columns)}"
        )
    best_joint = metrics.loc[metrics["joint_cost_cny"].idxmin()]
    effect = metrics["storage_effect_on_shift_cny"]
    return "\n".join(
        (
            "Storage energy-power sensitivity summary:",
            "Best joint cost: "
            f"{float(best_joint.joint_cost_cny):.4f} CNY "
            f"at {float(best_joint.battery_energy_mwh):g} MWh / "
            f"{float(best_joint.battery_power_mw):g} MW.",
            "Shift-value effect range: "
            f"{float(effect.min()):.4f} to {float(effect.max()):.4f} CNY.",
        )
    )
