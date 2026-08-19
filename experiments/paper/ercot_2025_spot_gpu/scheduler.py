from __future__ import annotations

import heapq
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from collections.abc import Callable
from typing import Any, Literal

import numpy as np
import pandas as pd
from pyscipopt import Model, quicksum

from .config import COST_GUARDRAIL_FRACTION, HP_RISK_QUANTILE
from .evaluation import evaluate_hourly_replay, normalized_renewable_index
from .power import PowerModel
from .types import Job, ScheduledRun


Policy = Literal["fifo", "reserve", "price", "proposed"]


@dataclass(frozen=True)
class ReplayCase:
    energy: pd.DataFrame
    capacities: dict[str, float]
    spot_jobs: tuple[Job, ...]
    hp_jobs: tuple[Job, ...]
    core_start_hour: int
    core_hours: int
    tail_hours: int
    power_model: PowerModel
    decision_block_hours: int = 24
    hp_calibration_hours: int = 336
    hp_risk_quantile: float = HP_RISK_QUANTILE
    solver_time_limit_seconds: float = 10.0

    def with_energy(self, energy: pd.DataFrame) -> ReplayCase:
        return replace(self, energy=energy)


@dataclass(frozen=True)
class ReplayResult:
    policy: Policy
    hourly: pd.DataFrame
    jobs: pd.DataFrame
    schedule: tuple[ScheduledRun, ...]
    cost_usd: float
    price_optimum_usd: float
    actual_renewable_alignment_index: float
    actual_co2_kg: float
    solver_status: str
    maximum_solve_seconds: float
    infeasibility_reasons: tuple[str, ...]


@dataclass(frozen=True)
class _BlockPlan:
    scheduled: tuple[tuple[str, int], ...]
    price_optimum_usd: float
    status: str
    solve_seconds: float
    reason: str = ""


@dataclass(frozen=True)
class _Cohort:
    cohort_id: int
    jobs: tuple[Job, ...]
    gpu_model: str
    gpu_count: float
    release_hour: int
    deadline_hour: int
    remaining_each: int


def _validate_case(case: ReplayCase) -> pd.DataFrame:
    if case.core_hours <= 0 or case.tail_hours < 0 or case.decision_block_hours <= 0:
        raise ValueError("replay horizon lengths must be positive")
    expected_hours = case.core_hours + case.tail_hours
    if len(case.energy) != expected_hours:
        raise ValueError(
            f"energy has {len(case.energy)} rows; expected {expected_hours} core/tail rows"
        )
    required = {
        "trace_hour",
        "period_role",
        "dam_lz_houston_usd_per_mwh",
        "forecast_erco_solar_generation_mwh",
        "forecast_erco_wind_generation_mwh",
        "forecast_consumed_co2_lbs_per_kwh",
        "erco_solar_generation_mwh",
        "erco_wind_generation_mwh",
        "erco_consumed_co2_intensity_lbs_per_kwh",
    }
    missing = sorted(required.difference(case.energy.columns))
    if missing:
        raise ValueError(f"energy is missing replay columns: {missing}")
    energy = case.energy.reset_index(drop=True).copy()
    expected_trace_hours = np.arange(
        case.core_start_hour, case.core_start_hour + expected_hours
    )
    if not np.array_equal(energy["trace_hour"].to_numpy(dtype=int), expected_trace_hours):
        raise ValueError("energy trace_hour must be continuous from core_start_hour")
    if energy[list(required - {"trace_hour", "period_role"})].isna().any().any():
        raise ValueError("replay energy signals cannot contain missing values")
    expected_roles = ["core"] * case.core_hours + ["settlement_tail"] * case.tail_hours
    if energy["period_role"].tolist() != expected_roles:
        raise ValueError("energy period_role does not match core/tail lengths")
    for model, capacity in case.capacities.items():
        if capacity <= 0.0:
            raise ValueError(f"capacity must be positive for {model!r}")
    for job in (*case.spot_jobs, *case.hp_jobs):
        if job.gpu_model not in case.capacities:
            raise ValueError(f"job {job.job_id!r} has no model capacity")
        if job.gpu_count > case.capacities[job.gpu_model] + 1e-9:
            raise ValueError(f"job {job.job_id!r} gang exceeds model capacity")
    return energy


def _realize_hp_priority_queue(
    case: ReplayCase,
    simulation_end_hour: int,
) -> tuple[dict[int, dict[str, float]], dict[int, dict[str, float]]]:
    """Run a capacity-limited HP queue using exact whole-gang cohort service."""

    arrivals: dict[
        str, dict[int, Counter[tuple[float, float]]]
    ] = {model: defaultdict(Counter) for model in case.capacities}
    earliest = min(case.core_start_hour, simulation_end_hour)
    for job in case.hp_jobs:
        if job.release_hour >= simulation_end_hour:
            continue
        arrivals[job.gpu_model][job.release_hour][
            (job.gpu_count, job.duration_seconds / 3_600.0)
        ] += 1
        earliest = min(earliest, job.release_hour)

    occupancy: dict[int, dict[str, float]] = {}
    queued_gpu_hours: dict[int, dict[str, float]] = {}
    for model, capacity in case.capacities.items():
        queues: dict[float, list[tuple[int, int, float, int]]] = defaultdict(list)
        sequence = 0
        remaining_gpu_hours = 0.0
        for trace_hour in range(earliest, simulation_end_hour):
            for (gang, run_hours), count in sorted(
                arrivals[model].get(trace_hour, {}).items()
            ):
                heapq.heappush(
                    queues[gang],
                    (trace_hour, sequence, run_hours, count),
                )
                remaining_gpu_hours += gang * run_hours * count
                sequence += 1

            available = float(capacity)
            used = 0.0
            for gang in sorted(queues, reverse=True):
                queue = queues[gang]
                service_capacity = available / gang
                if service_capacity <= 1e-12 or not queue:
                    continue
                deferred: Counter[tuple[int, float]] = Counter()
                while service_capacity > 1e-12 and queue:
                    release_hour, _, remaining_hours, count = heapq.heappop(queue)
                    service_per_job = min(1.0, remaining_hours)
                    full_jobs = min(
                        count,
                        int(math.floor((service_capacity + 1e-12) / service_per_job)),
                    )
                    served_hours = full_jobs * service_per_job
                    if full_jobs > 0 and remaining_hours > service_per_job + 1e-12:
                        deferred[
                            (
                                release_hour,
                                round(remaining_hours - service_per_job, 12),
                            )
                        ] += full_jobs
                    unserved_jobs = count - full_jobs
                    service_capacity -= served_hours
                    if unserved_jobs > 0 and service_capacity > 1e-12:
                        partial_service = min(service_per_job, service_capacity)
                        served_hours += partial_service
                        service_capacity -= partial_service
                        new_remaining = remaining_hours - partial_service
                        if new_remaining > 1e-12:
                            deferred[
                                (release_hour, round(new_remaining, 12))
                            ] += 1
                        unserved_jobs -= 1
                    if unserved_jobs > 0:
                        deferred[(release_hour, remaining_hours)] += unserved_jobs
                    available -= served_hours * gang
                    used += served_hours * gang
                    remaining_gpu_hours -= served_hours * gang
                for (release_hour, remaining_hours), count in sorted(
                    deferred.items()
                ):
                    heapq.heappush(
                        queue,
                        (release_hour, sequence, remaining_hours, count),
                    )
                    sequence += 1
            occupancy.setdefault(trace_hour, {})[model] = max(0.0, used)
            queued_gpu_hours.setdefault(trace_hour, {})[model] = max(
                0.0, remaining_gpu_hours
            )
    return occupancy, queued_gpu_hours


def _hp_risk_quantile(
    case: ReplayCase,
    hp_occupancy: dict[int, dict[str, float]],
    block_start: int,
) -> dict[str, float]:
    history_start = block_start - case.hp_calibration_hours
    quantiles: dict[str, float] = {}
    for model in case.capacities:
        history = [
            hp_occupancy.get(hour, {}).get(model, 0.0)
            for hour in range(history_start, block_start)
            if hour in hp_occupancy
        ]
        quantiles[model] = (
            float(np.quantile(history, case.hp_risk_quantile)) if history else 0.0
        )
    return quantiles


def _known_running_hp_profile(
    case: ReplayCase,
    block_start: int,
    block_end: int,
) -> dict[str, dict[int, float]]:
    profile: dict[str, dict[int, float]] = {
        model: {trace_hour: 0.0 for trace_hour in range(block_start, block_end)}
        for model in case.capacities
    }
    for job in case.hp_jobs:
        if job.release_hour > block_start:
            continue
        end_hour = job.release_hour + job.duration_seconds / 3_600.0
        if end_hour <= block_start:
            continue
        last_hour = min(block_end, math.ceil(end_hour))
        for trace_hour in range(block_start, last_hour):
            profile[job.gpu_model][trace_hour] += job.gpu_count
    return profile


def _reserve_by_model(
    case: ReplayCase,
    hp_occupancy: dict[int, dict[str, float]],
    block_start: int,
    block_end: int,
    policy: Policy,
) -> tuple[dict[str, dict[int, float]], dict[str, float]]:
    quantiles = _hp_risk_quantile(case, hp_occupancy, block_start)
    if policy == "fifo":
        reserves = {
            model: {
                trace_hour: 0.0
                for trace_hour in range(block_start, block_end)
            }
            for model in case.capacities
        }
        return reserves, {model: 0.0 for model in case.capacities}

    known = _known_running_hp_profile(case, block_start, block_end)
    reserves: dict[str, dict[int, float]] = {}
    for model, capacity in case.capacities.items():
        reserves[model] = {
            trace_hour: min(
                capacity, max(known[model][trace_hour], quantiles[model])
            )
            for trace_hour in range(block_start, block_end)
        }
    return reserves, quantiles


def _infeasibility_reason(
    case: ReplayCase,
    cohorts: dict[int, _Cohort],
    required_now_by_cohort: dict[int, int],
    reserves: dict[str, dict[int, float]],
    block_start: int,
    block_end: int,
) -> str:
    per_model_required: dict[str, float] = defaultdict(float)
    for cohort in cohorts.values():
        per_model_required[cohort.gpu_model] += (
            cohort.gpu_count * required_now_by_cohort.get(cohort.cohort_id, 0)
        )
    over: list[tuple[str, float, float]] = []
    for model, capacity in case.capacities.items():
        available = sum(
            max(0.0, capacity - reserves[model].get(trace_hour, 0.0))
            for trace_hour in range(block_start, block_end)
        )
        needed = per_model_required[model]
        if needed > available + 1e-9:
            over.append((model, needed, available))
    if over:
        model, needed, available = over[0]
        return (
            f"block {block_start}-{block_end}: {model} must schedule "
            f"{needed:.1f} gang-hours in-block but planning capacity is "
            f"{available:.1f} ({len(over)} model(s) over-subscribed)"
        )
    return (
        f"block {block_start}-{block_end}: integer deadline/capacity "
        f"infeasible for {len(cohorts)} cohort(s); no single-model aggregate "
        f"violation was detected"
    )


def _solve_block(
    case: ReplayCase,
    energy: pd.DataFrame,
    remaining: dict[str, int],
    block_start: int,
    block_end: int,
    reserves: dict[str, dict[int, float]],
    future_reserve: dict[str, float],
    policy: Policy,
) -> _BlockPlan:
    relevant = tuple(
        job
        for job in case.spot_jobs
        if remaining[job.job_id] > 0
        and job.release_hour < block_end
        and job.deadline_hour is not None
        and job.deadline_hour > block_start
    )
    if not relevant:
        return _BlockPlan((), 0.0, "optimal", 0.0, 0.0)

    grouped: dict[
        tuple[str, float, int, int, int], list[Job]
    ] = defaultdict(list)
    for job in relevant:
        assert job.deadline_hour is not None
        grouped[
            (
                job.gpu_model,
                job.gpu_count,
                job.release_hour,
                job.deadline_hour,
                remaining[job.job_id],
            )
        ].append(job)
    cohorts: dict[int, _Cohort] = {}
    for cohort_id, (key, members) in enumerate(sorted(grouped.items())):
        gpu_model, gpu_count, release_hour, deadline_hour, remaining_each = key
        cohorts[cohort_id] = _Cohort(
            cohort_id=cohort_id,
            jobs=tuple(sorted(members, key=lambda job: job.job_id)),
            gpu_model=gpu_model,
            gpu_count=gpu_count,
            release_hour=release_hour,
            deadline_hour=deadline_hour,
            remaining_each=remaining_each,
        )

    model = Model(f"spot_gpu_{policy}_{block_start}")
    model.hideOutput()
    model.setParam("limits/time", case.solver_time_limit_seconds)
    variables: dict[tuple[int, int], object] = {}
    variables_by_cohort: dict[int, list[object]] = defaultdict(list)
    variables_by_model_hour: dict[tuple[str, int], list[tuple[float, object]]] = (
        defaultdict(list)
    )
    for cohort in cohorts.values():
        for trace_hour in range(
            max(block_start, cohort.release_hour),
            min(block_end, cohort.deadline_hour),
        ):
            variable = model.addVar(
                lb=0.0,
                ub=float(len(cohort.jobs)),
                vtype="I",
                name=f"x_c{cohort.cohort_id}_{trace_hour}",
            )
            variables[(cohort.cohort_id, trace_hour)] = variable
            variables_by_cohort[cohort.cohort_id].append(variable)
            variables_by_model_hour[(cohort.gpu_model, trace_hour)].append(
                (cohort.gpu_count, variable)
            )

    required_now_by_cohort: dict[int, int] = {}
    for cohort in cohorts.values():
        cohort_variables = variables_by_cohort[cohort.cohort_id]
        member_count = len(cohort.jobs)
        total_remaining = cohort.remaining_each * member_count
        future_slots = max(0, cohort.deadline_hour - block_end)
        required_now = max(0, total_remaining - future_slots * member_count)
        required_now_by_cohort[cohort.cohort_id] = required_now
        if required_now > 0:
            model.addCons(quicksum(cohort_variables) >= required_now)
        model.addCons(quicksum(cohort_variables) <= total_remaining)

    for gpu_model, capacity in case.capacities.items():
        for trace_hour in range(block_start, block_end):
            planning_capacity = max(
                0.0, capacity - reserves[gpu_model][trace_hour]
            )
            model.addCons(
                quicksum(
                    gpu_count * variable
                    for gpu_count, variable in variables_by_model_hour[
                        (gpu_model, trace_hour)
                    ]
                )
                <= planning_capacity
            )

    for gpu_model, capacity in case.capacities.items():
        model_cohorts = [
            cohort
            for cohort in cohorts.values()
            if cohort.gpu_model == gpu_model
        ]
        if not model_cohorts:
            continue
        future_capacity_per_hour = max(
            0.0, capacity - future_reserve[gpu_model]
        )
        for deadline in sorted(
            {cohort.deadline_hour for cohort in model_cohorts}
        ):
            total_up_to_deadline = sum(
                cohort.gpu_count * cohort.remaining_each * len(cohort.jobs)
                for cohort in model_cohorts
                if cohort.deadline_hour <= deadline
            )
            future_capacity_up_to_deadline = (
                future_capacity_per_hour * max(0, deadline - block_end)
            )
            required_now = max(
                0.0, total_up_to_deadline - future_capacity_up_to_deadline
            )
            if required_now <= 1e-9:
                continue
            model.addCons(
                quicksum(
                    cohort.gpu_count * variable
                    for cohort in model_cohorts
                    if cohort.deadline_hour <= deadline
                    for variable in variables_by_cohort[cohort.cohort_id]
                )
                >= required_now
            )

    forecast_index = normalized_renewable_index(
        energy["forecast_erco_solar_generation_mwh"].to_numpy(dtype=float),
        energy["forecast_erco_wind_generation_mwh"].to_numpy(dtype=float),
    )
    row_by_hour = {
        int(row.trace_hour): index for index, row in energy.iterrows()
    }
    marginal_mw = {
        cohort_id: case.power_model.facility_mw(
            {cohort.gpu_model: cohort.gpu_count}
        )
        for cohort_id, cohort in cohorts.items()
    }
    cost_expression = quicksum(
        marginal_mw[cohort_id]
        * float(energy.iloc[row_by_hour[trace_hour]]["dam_lz_houston_usd_per_mwh"])
        * variable
        for (cohort_id, trace_hour), variable in variables.items()
    )
    alignment_expression = quicksum(
        marginal_mw[cohort_id]
        * float(forecast_index[row_by_hour[trace_hour]])
        * variable
        for (cohort_id, trace_hour), variable in variables.items()
    )
    carbon_expression = quicksum(
        marginal_mw[cohort_id]
        * float(
            energy.iloc[row_by_hour[trace_hour]][
                "forecast_consumed_co2_lbs_per_kwh"
            ]
        )
        * variable
        for (cohort_id, trace_hour), variable in variables.items()
    )
    started = time.perf_counter()
    if policy in {"fifo", "reserve"}:
        fifo_expression = quicksum(
            (trace_hour + cohorts[cohort_id].deadline_hour * 1e-6)
            * variable
            for (cohort_id, trace_hour), variable in variables.items()
        )
        model.setObjective(fifo_expression, sense="minimize")
        model.optimize()
        if model.getNSols() == 0:
            return _BlockPlan(
                (),
                math.inf,
                str(model.getStatus()),
                time.perf_counter() - started,
                _infeasibility_reason(
                    case, cohorts, required_now_by_cohort, reserves,
                    block_start, block_end,
                ),
            )
        price_optimum = float(model.getVal(cost_expression))
    else:
        model.setObjective(cost_expression, sense="minimize")
        model.optimize()
        if model.getNSols() == 0:
            return _BlockPlan(
                (),
                math.inf,
                str(model.getStatus()),
                time.perf_counter() - started,
                _infeasibility_reason(
                    case, cohorts, required_now_by_cohort, reserves,
                    block_start, block_end,
                ),
            )
        price_optimum = float(model.getVal(cost_expression))
        if policy == "proposed":
            guard = COST_GUARDRAIL_FRACTION * max(abs(price_optimum), 1.0)
            model.freeTransform()
            model.addCons(cost_expression <= price_optimum + guard)
            model.setObjective(alignment_expression, sense="maximize")
            model.optimize()
            if model.getNSols() == 0:
                return _BlockPlan(
                    (),
                    math.inf,
                    str(model.getStatus()),
                    time.perf_counter() - started,
                    f"block {block_start}-{block_end}: proposed alignment "
                    f"step became infeasible after the cost guard",
                )
            alignment_star = float(model.getVal(alignment_expression))
            model.freeTransform()
            model.addCons(alignment_expression >= alignment_star - 1e-7)
            model.setObjective(carbon_expression, sense="minimize")
            model.optimize()
            if model.getNSols() == 0:
                return _BlockPlan(
                    (),
                    math.inf,
                    str(model.getStatus()),
                    time.perf_counter() - started,
                    f"block {block_start}-{block_end}: proposed carbon step "
                    f"became infeasible after alignment fixing",
                )

    status = str(model.getStatus())
    planned_remaining = {
        job.job_id: remaining[job.job_id] for job in relevant
    }
    scheduled_jobs: list[tuple[str, int]] = []
    for trace_hour in range(block_start, block_end):
        for cohort_id, cohort in cohorts.items():
            variable = variables.get((cohort_id, trace_hour))
            if variable is None:
                continue
            planned_count = int(round(model.getVal(variable)))
            if planned_count <= 0:
                continue
            candidates = sorted(
                (
                    job
                    for job in cohort.jobs
                    if planned_remaining[job.job_id] > 0
                ),
                key=lambda job: (-planned_remaining[job.job_id], job.job_id),
            )
            if len(candidates) < planned_count:
                raise RuntimeError(
                    f"cohort {cohort_id} cannot recover {planned_count} whole gangs"
                )
            for job in candidates[:planned_count]:
                planned_remaining[job.job_id] -= 1
                scheduled_jobs.append((job.job_id, trace_hour))
    return _BlockPlan(
        scheduled=tuple(
            sorted(scheduled_jobs, key=lambda item: (item[1], item[0]))
        ),
        price_optimum_usd=price_optimum,
        status=status,
        solve_seconds=time.perf_counter() - started,
    )


def run_replay(
    case: ReplayCase,
    *,
    policy: Policy,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> ReplayResult:
    if policy not in {"fifo", "reserve", "price", "proposed"}:
        raise ValueError(f"unknown replay policy {policy!r}")
    energy = _validate_case(case)
    simulation_end = case.core_start_hour + case.core_hours + case.tail_hours
    hp_occupancy, hp_queue = _realize_hp_priority_queue(case, simulation_end)
    jobs_by_id = {job.job_id: job for job in case.spot_jobs}
    remaining = {job.job_id: job.required_run_hours for job in case.spot_jobs}
    execution_hours: dict[str, list[int]] = {job.job_id: [] for job in case.spot_jobs}
    actual_runs: list[ScheduledRun] = []
    hourly_spot_by_model: dict[int, dict[str, float]] = {}
    statuses: list[str] = []
    infeasibility_reasons: list[str] = []
    maximum_solve_seconds = 0.0
    price_optimum_spot = 0.0

    horizon_end = case.core_start_hour + case.core_hours + case.tail_hours
    for block_start in range(
        case.core_start_hour, horizon_end, case.decision_block_hours
    ):
        block_end = min(block_start + case.decision_block_hours, horizon_end)
        reserves, future_reserve = _reserve_by_model(
            case, hp_occupancy, block_start, block_end, policy
        )
        plan = _solve_block(
            case,
            energy,
            remaining,
            block_start,
            block_end,
            reserves,
            future_reserve,
            policy,
        )
        statuses.append(plan.status)
        if plan.reason:
            infeasibility_reasons.append(plan.reason)
        maximum_solve_seconds = max(maximum_solve_seconds, plan.solve_seconds)
        price_optimum_spot += plan.price_optimum_usd
        if progress_callback is not None:
            progress_callback(
                {
                    "block_start": block_start,
                    "block_end": block_end,
                    "status": plan.status,
                    "solve_seconds": plan.solve_seconds,
                    "scheduled_job_hours": len(plan.scheduled),
                    "reason": plan.reason,
                }
            )
        planned_by_hour: dict[int, list[Job]] = {}
        for job_id, trace_hour in plan.scheduled:
            planned_by_hour.setdefault(trace_hour, []).append(jobs_by_id[job_id])

        for trace_hour in range(block_start, block_end):
            actual_available = {
                model: max(
                    0.0,
                    capacity
                    - hp_occupancy.get(trace_hour, {}).get(model, 0.0),
                )
                for model, capacity in case.capacities.items()
            }
            for job in sorted(
                planned_by_hour.get(trace_hour, []),
                key=lambda item: (
                    item.deadline_hour if item.deadline_hour is not None else math.inf,
                    item.release_hour,
                    item.job_id,
                ),
            ):
                if remaining[job.job_id] <= 0:
                    continue
                if not (
                    job.release_hour <= trace_hour
                    and job.deadline_hour is not None
                    and trace_hour < job.deadline_hour
                ):
                    continue
                if job.gpu_count > actual_available[job.gpu_model] + 1e-9:
                    continue
                actual_available[job.gpu_model] -= job.gpu_count
                remaining[job.job_id] -= 1
                execution_hours[job.job_id].append(trace_hour)
                hourly_spot_by_model.setdefault(trace_hour, {}).setdefault(
                    job.gpu_model, 0.0
                )
                hourly_spot_by_model[trace_hour][job.gpu_model] += job.gpu_count
                actual_runs.append(
                    ScheduledRun(
                        job_id=job.job_id,
                        trace_hour=trace_hour,
                        gpu_model=job.gpu_model,
                        gpu_count=job.gpu_count,
                    )
                )

    hourly_rows: list[dict[str, object]] = []
    for _, row in energy.iterrows():
        trace_hour = int(row["trace_hour"])
        hp_by_model = hp_occupancy.get(trace_hour, {})
        spot_by_model = hourly_spot_by_model.get(trace_hour, {})
        total_by_model = {
            model: hp_by_model.get(model, 0.0) + spot_by_model.get(model, 0.0)
            for model in case.capacities
        }
        hp_invasion = sum(
            max(0.0, hp_by_model.get(model, 0.0) - capacity)
            for model, capacity in case.capacities.items()
        )
        total_excess = sum(
            max(0.0, total_by_model[model] - capacity)
            for model, capacity in case.capacities.items()
        )
        hourly_rows.append(
            {
                **row.to_dict(),
                "new_spot_arrivals": sum(
                    1 for job in case.spot_jobs if job.release_hour == trace_hour
                ),
                "hp_active_gpus": sum(hp_by_model.values()),
                "spot_active_gpus": sum(spot_by_model.values()),
                "hp_queued_gpu_hours": sum(hp_queue.get(trace_hour, {}).values()),
                "hp_capacity_invasion_gpus": hp_invasion,
                "spot_capacity_excess_gpus": total_excess,
                "facility_mw": case.power_model.facility_mw(total_by_model),
            }
        )
    hourly = pd.DataFrame(hourly_rows)
    evaluation = evaluate_hourly_replay(hourly)
    fixed_hp_cost = 0.0
    for _, row in energy.iterrows():
        trace_hour = int(row["trace_hour"])
        fixed_hp_cost += case.power_model.facility_mw(
            hp_occupancy.get(trace_hour, {})
        ) * float(row["dam_lz_houston_usd_per_mwh"])

    job_rows: list[dict[str, object]] = []
    for job in case.spot_jobs:
        hours = execution_hours[job.job_id]
        completed = remaining[job.job_id] == 0
        completion_hour = max(hours) + 1 if completed and hours else None
        deadline_feasible = bool(
            completed
            and completion_hour is not None
            and job.deadline_hour is not None
            and completion_hour <= job.deadline_hour
            and all(job.release_hour <= hour < job.deadline_hour for hour in hours)
        )
        job_rows.append(
            {
                "job_id": job.job_id,
                "gpu_model": job.gpu_model,
                "gpu_count": job.gpu_count,
                "release_hour": job.release_hour,
                "deadline_hour": job.deadline_hour,
                "required_run_hours": job.required_run_hours,
                "executed_run_hours": len(hours),
                "remaining_run_hours": remaining[job.job_id],
                "completed": completed,
                "completion_hour": completion_hour,
                "deadline_feasible": deadline_feasible,
                "delay_hours": (
                    max(
                        0,
                        completion_hour
                        - (job.release_hour + job.required_run_hours),
                    )
                    if completion_hour is not None
                    else None
                ),
            }
        )
    jobs = pd.DataFrame(job_rows)
    solver_status = "optimal" if statuses and all(s == "optimal" for s in statuses) else ",".join(statuses)
    return ReplayResult(
        policy=policy,
        hourly=hourly,
        jobs=jobs,
        schedule=tuple(actual_runs),
        cost_usd=evaluation.cost_usd,
        price_optimum_usd=fixed_hp_cost + price_optimum_spot,
        actual_renewable_alignment_index=evaluation.actual_renewable_alignment_index,
        actual_co2_kg=evaluation.actual_co2_kg,
        solver_status=solver_status,
        maximum_solve_seconds=maximum_solve_seconds,
        infeasibility_reasons=tuple(infeasibility_reasons),
    )
