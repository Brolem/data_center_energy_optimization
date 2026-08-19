from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import CORE_HOURS, HP_CALIBRATION_HOURS, TAIL_HOURS
from .power import PowerModel
from .scheduler import Policy, ReplayCase, ReplayResult, run_replay
from .workload import build_selection_manifest


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_workload_paths() -> tuple[Path, Path]:
    project_root = _project_root()
    candidate_roots = [project_root]
    if project_root.parent.name == ".worktrees":
        candidate_roots.append(project_root.parent.parent)
    names = (
        "alibaba_2026_spot_gpu_job_info_df.csv",
        "alibaba_2026_spot_gpu_node_info_df.csv",
    )
    for root in candidate_roots:
        job_csv = root / "data" / "workload" / names[0]
        node_csv = root / "data" / "workload" / names[1]
        if job_csv.is_file() and node_csv.is_file():
            return job_csv, node_csv
    raise FileNotFoundError(
        "Alibaba workload CSV files are absent; see data/workload/README.md"
    )


def build_replay_case(
    energy_csv: Path,
    *,
    job_csv: Path | None = None,
    node_csv: Path | None = None,
    power_model: PowerModel | None = None,
) -> ReplayCase:
    if job_csv is None or node_csv is None:
        default_job_csv, default_node_csv = default_workload_paths()
        job_csv = default_job_csv if job_csv is None else job_csv
        node_csv = default_node_csv if node_csv is None else node_csv
    selection, manifest = build_selection_manifest(job_csv, node_csv)
    frame = pd.read_csv(energy_csv)
    frame = frame.loc[
        frame["period_role"].isin(["core", "settlement_tail"])
    ].reset_index(drop=True)
    if len(frame) != CORE_HOURS + TAIL_HOURS:
        raise ValueError(
            f"{energy_csv.name} has {len(frame)} replay rows; "
            f"expected {CORE_HOURS + TAIL_HOURS}"
        )
    frame["trace_hour"] = range(
        selection.core_start_hour,
        selection.core_start_hour + CORE_HOURS + TAIL_HOURS,
    )
    capacities = {
        model: float(capacity)
        for model, capacity in manifest["model_capacity_gpus"].items()
    }
    return ReplayCase(
        energy=frame,
        capacities=capacities,
        spot_jobs=selection.spot_jobs,
        hp_jobs=selection.hp_jobs,
        core_start_hour=selection.core_start_hour,
        core_hours=CORE_HOURS,
        tail_hours=TAIL_HOURS,
        decision_block_hours=24,
        hp_calibration_hours=HP_CALIBRATION_HOURS,
        power_model=power_model or PowerModel.baseline(),
    )


def summarize_replay(result: ReplayResult) -> dict[str, Any]:
    completed = result.jobs["completed"].astype(bool)
    completion_rate = float(completed.mean()) if len(completed) else 0.0
    completed_deadline_feasible = bool(
        result.jobs.loc[completed, "deadline_feasible"].all()
    )
    return {
        "policy": result.policy,
        "solver_status": result.solver_status,
        "maximum_solve_seconds": result.maximum_solve_seconds,
        "cost_usd": result.cost_usd,
        "price_optimum_usd": result.price_optimum_usd,
        "actual_renewable_alignment_index": result.actual_renewable_alignment_index,
        "actual_co2_kg": result.actual_co2_kg,
        "spot_completion_rate": completion_rate,
        "spot_completed_jobs": int(completed.sum()),
        "spot_total_jobs": int(len(completed)),
        "completed_job_recovery_valid": completed_deadline_feasible,
        "hp_capacity_invasion_gpus_max": float(
            result.hourly["hp_capacity_invasion_gpus"].max()
        ),
        "spot_capacity_excess_gpus_max": float(
            result.hourly["spot_capacity_excess_gpus"].max()
        ),
        "hp_queued_gpu_hours_max": float(
            result.hourly["hp_queued_gpu_hours"].max()
        ),
        "settlement_tail_unfinished_run_hours": int(
            result.jobs["remaining_run_hours"].sum()
        ),
        "infeasibility_reasons": list(result.infeasibility_reasons),
    }


def run_window(
    energy_csv: Path,
    *,
    policy: Policy,
    job_csv: Path | None = None,
    node_csv: Path | None = None,
) -> ReplayResult:
    case = build_replay_case(
        energy_csv, job_csv=job_csv, node_csv=node_csv
    )
    return run_replay(case, policy=policy)


def run_spot_gpu_pilot(
    *,
    input_dir: Path,
    output_dir: Path,
    job_csv: Path | None = None,
    node_csv: Path | None = None,
) -> dict[str, Any]:
    candidates = sorted(input_dir.glob("2025-01-01*_energy.csv"))
    if len(candidates) != 1:
        raise FileNotFoundError(
            f"expected one winter energy input in {input_dir}, found {len(candidates)}"
        )
    result = run_window(
        candidates[0],
        policy="proposed",
        job_csv=job_csv,
        node_csv=node_csv,
    )
    summary = summarize_replay(result)
    summary.update(
        {
            "schema_version": 1,
            "window": candidates[0].stem,
            "feasible_for_full_replay": bool(
                not result.infeasibility_reasons
                and summary["hp_capacity_invasion_gpus_max"] == 0.0
                and summary["spot_capacity_excess_gpus_max"] == 0.0
                and summary["completed_job_recovery_valid"]
                and summary["spot_completed_jobs"] == summary["spot_total_jobs"]
            ),
            "hp_replay_note": (
                "HP submit, gang, model and duration define active demand; "
                "whole gangs are admitted before Spot and capped by node capacity"
            ),
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pilot_feasibility.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary
