from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib-cache")
)

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyscipopt import Model


def configure_plot_fonts() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC",
        "Microsoft YaHei",
        "SimHei",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


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
    }


def make_plots(
    all_results: pd.DataFrame,
    metrics: pd.DataFrame,
    output_dir: Path,
) -> None:
    colors = {
        "baseline": "#6B7280",
        "shift_only": "#2563EB",
        "storage_only": "#F59E0B",
        "joint": "#DC2626",
    }
    labels = {
        "baseline": "Baseline",
        "shift_only": "Workload shift",
        "storage_only": "Battery",
        "joint": "Shift + battery",
    }
    hours = np.arange(24)
    configure_plot_fonts()

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)

    baseline = all_results[all_results["case"] == "baseline"]
    joint = all_results[all_results["case"] == "joint"]
    axes[0, 0].plot(
        hours,
        baseline["cpu_arrival_pu"],
        color=colors["baseline"],
        marker="o",
        markersize=3,
        label="Original CPU",
    )
    axes[0, 0].plot(
        hours,
        joint["cpu_scheduled_pu"],
        color=colors["joint"],
        marker="o",
        markersize=3,
        label="Jointly scheduled CPU",
    )
    axes[0, 0].set_title("Aggregated CPU load")
    axes[0, 0].set_ylabel("CPU utilization (p.u.)")
    axes[0, 0].legend()

    for case_name in ["baseline", "shift_only", "storage_only", "joint"]:
        data = all_results[all_results["case"] == case_name]
        axes[0, 1].plot(
            hours,
            data["grid_power_mw"],
            color=colors[case_name],
            linewidth=2 if case_name == "joint" else 1.5,
            label=labels[case_name],
        )
    axes[0, 1].set_title("Grid power in four cases")
    axes[0, 1].set_ylabel("Grid power (MW)")
    axes[0, 1].legend(fontsize=9)

    axes[1, 0].bar(
        hours,
        joint["charge_mw"],
        width=0.36,
        color="#3B82F6",
        label="Charge",
    )
    axes[1, 0].bar(
        hours,
        -joint["discharge_mw"],
        width=0.36,
        color="#F97316",
        label="Discharge",
    )
    axes[1, 0].axhline(0, color="#374151", linewidth=0.8)
    axes[1, 0].set_title("Joint case: battery operation")
    axes[1, 0].set_ylabel("Power (MW)")
    axes[1, 0].legend()

    axes[1, 1].step(
        np.arange(25),
        np.r_[joint["soc_start"].iloc[0], joint["soc_end"].to_numpy()],
        where="post",
        color="#059669",
        linewidth=2,
    )
    axes[1, 1].axhline(0.1, color="#9CA3AF", linestyle="--", linewidth=1)
    axes[1, 1].axhline(0.9, color="#9CA3AF", linestyle="--", linewidth=1)
    axes[1, 1].set_ylim(0, 1)
    axes[1, 1].set_title("Joint case: battery SOC")
    axes[1, 1].set_ylabel("SOC")

    for ax in axes.flat:
        ax.set_xlabel("Hour")
        ax.set_xticks(np.arange(0, 24, 3))
        ax.grid(True, alpha=0.2)

    fig.suptitle("Google 2019 aggregated trace: first SCIP results", fontsize=16)
    fig.savefig(output_dir / "first_version_results.png", dpi=180)
    plt.close(fig)

    ordered = metrics.set_index("case").loc[
        ["baseline", "shift_only", "storage_only", "joint"]
    ]
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    bars = ax.bar(
        [labels[x] for x in ordered.index],
        ordered["total_variation_mw"],
        color=[colors[x] for x in ordered.index],
    )
    ax.bar_label(bars, fmt="%.2f", padding=3)
    ax.set_ylabel("Total variation (MW)")
    ax.set_title("Grid-power variation (lower is better)")
    ax.grid(axis="y", alpha=0.2)
    fig.savefig(output_dir / "total_variation_comparison.png", dpi=180)
    plt.close(fig)
