from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .config import COMPLETION_SLACK_HOURS, CORE_HOURS, MAX_SPOT_DURATION_HOURS
from .power import PowerModel, power_scenarios
from .types import Job, ReplaySelection


ALIBABA_SOURCE_COMMIT = "0d0f3f1efdbf1add6a7bcc63676eafbd1eb11f71"
ALIBABA_UPSTREAM_JOB_SHA256 = (
    "113CCEE4C28F5C3BBAACA974CD164B9280B7D4C39E53B745443B28EEA05E03DD"
)
ALIBABA_UPSTREAM_NODE_SHA256 = (
    "1ABA161961A5A4A1A61AA581383C5E5ABE3400B59F8597BA8C4EEF7597BC9D18"
)
ALIBABA_LOCAL_NORMALIZED_JOB_SHA256 = (
    "5A0C828A1C9CAE9D9AE73677371D59B4F3F0C55F25FE2E7CD06BC12DAF79648D"
)


def _field(record: Mapping[str, Any], official: str, alias: str) -> Any:
    if official in record:
        return record[official]
    if alias in record:
        return record[alias]
    raise ValueError(f"missing required field {official!r}")


def _finite_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def normalize_job(
    record: Mapping[str, Any],
    *,
    completion_slack_hours: int = COMPLETION_SLACK_HOURS,
) -> Job:
    """Normalize one official trace record without changing its GPU model or gang."""

    raw_priority = str(_field(record, "job_type", "priority")).strip().lower()
    if raw_priority not in {"hp", "spot"}:
        raise ValueError(f"unknown job priority {raw_priority!r}")
    priority = "HP" if raw_priority == "hp" else "Spot"
    gpu_request = _finite_number(record.get("gpu_request"), "gpu_request")
    worker_num = _finite_number(record.get("worker_num"), "worker_num")
    submit_time = _finite_number(
        _field(record, "submit_time", "submit_time_s"), "submit_time"
    )
    duration = _finite_number(_field(record, "duration", "duration_s"), "duration")
    if gpu_request <= 0.0 or worker_num <= 0.0:
        raise ValueError("gpu_request and worker_num must be positive")
    if submit_time < 0.0 or duration <= 0.0:
        raise ValueError("submit_time must be nonnegative and duration must be positive")
    if not worker_num.is_integer() or not submit_time.is_integer() or not duration.is_integer():
        raise ValueError("worker_num, submit_time, and duration must be integral")

    release_hour = int(submit_time) // 3_600
    required_run_hours = math.ceil(int(duration) / 3_600)
    deadline_hour = (
        release_hour + required_run_hours + completion_slack_hours
        if priority == "Spot"
        else None
    )
    return Job(
        job_id=str(_field(record, "job_name", "job_id")),
        organization=str(record.get("organization", "")),
        priority=priority,
        gpu_model=str(record.get("gpu_model", "")).strip(),
        gpu_count=gpu_request * worker_num,
        submit_time_seconds=int(submit_time),
        release_hour=release_hour,
        duration_seconds=int(duration),
        required_run_hours=required_run_hours,
        deadline_hour=deadline_hour,
    )


def aggregate_model_capacities(
    node_records: Iterable[Mapping[str, Any]],
) -> dict[str, float]:
    capacities: defaultdict[str, float] = defaultdict(float)
    for record in node_records:
        model = str(record.get("gpu_model", "")).strip()
        capacity = _finite_number(record.get("gpu_capacity_num"), "gpu_capacity_num")
        if not model or capacity <= 0.0:
            raise ValueError("node rows require a model and positive GPU capacity")
        capacities[model] += capacity
    return dict(sorted(capacities.items()))


def select_replay_core(
    jobs: Iterable[Job],
    *,
    core_hours: int = CORE_HOURS,
    max_duration_hours: int = MAX_SPOT_DURATION_HOURS,
) -> ReplaySelection:
    """Select the complete core closest to median eligible Spot GPU-hours."""

    ordered = tuple(sorted(jobs, key=lambda job: (job.release_hour, job.job_id)))
    if not ordered:
        raise ValueError("at least one trace job is required")
    if core_hours <= 0 or max_duration_hours <= 0:
        raise ValueError("core_hours and max_duration_hours must be positive")

    trace_start = ordered[0].release_hour
    # The final release hour is only partially observed.  A candidate core may
    # end at the start of that hour, but must not treat the partial hour as a
    # complete arrival interval.
    trace_end = max(job.submit_time_seconds for job in ordered) // 3_600
    if trace_end - trace_start < core_hours:
        raise ValueError("trace does not contain one complete replay core")

    eligible_spot = tuple(
        job
        for job in ordered
        if job.priority == "Spot" and job.required_run_hours <= max_duration_hours
    )
    hourly_gpu_hours: Counter[int] = Counter()
    for job in eligible_spot:
        hourly_gpu_hours[job.release_hour] += (
            job.gpu_count * job.duration_seconds / 3_600.0
        )

    running_sum = sum(
        hourly_gpu_hours[hour]
        for hour in range(trace_start, trace_start + core_hours)
    )
    candidate_scores = [(trace_start, float(running_sum))]
    for start in range(trace_start + 1, trace_end - core_hours + 1):
        running_sum -= hourly_gpu_hours[start - 1]
        running_sum += hourly_gpu_hours[start + core_hours - 1]
        candidate_scores.append((start, float(running_sum)))

    median_gpu_hours = float(statistics.median(score for _, score in candidate_scores))
    core_start, selected_gpu_hours = min(
        candidate_scores,
        key=lambda item: (abs(item[1] - median_gpu_hours), item[0]),
    )
    core_end = core_start + core_hours
    selected_spot = tuple(
        job
        for job in eligible_spot
        if core_start <= job.release_hour < core_end
    )
    excluded_long = sum(
        1
        for job in ordered
        if job.priority == "Spot"
        and core_start <= job.release_hour < core_end
        and job.required_run_hours > max_duration_hours
    )
    hp_jobs = tuple(job for job in ordered if job.priority == "HP")
    return ReplaySelection(
        core_start_hour=core_start,
        core_end_hour=core_end,
        core_hours=core_hours,
        max_spot_duration_hours=max_duration_hours,
        median_eligible_spot_gpu_hours=median_gpu_hours,
        selected_eligible_spot_gpu_hours=selected_gpu_hours,
        excluded_spot_over_max_duration_count=excluded_long,
        spot_jobs=selected_spot,
        hp_jobs=hp_jobs,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_csv(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def load_trace_jobs(
    job_csv: Path,
    node_csv: Path,
) -> tuple[tuple[Job, ...], dict[str, float], dict[str, int]]:
    capacities = aggregate_model_capacities(_read_csv(node_csv))
    supported_models = PowerModel.baseline().supported_models
    exclusions: Counter[str] = Counter()
    jobs: list[Job] = []
    for record in _read_csv(job_csv):
        model = str(record.get("gpu_model", "")).strip()
        if model not in capacities:
            exclusions["missing_capacity_mapping"] += 1
            continue
        if model not in supported_models:
            exclusions["missing_power_mapping"] += 1
            continue
        job = normalize_job(record)
        if job.gpu_count > capacities[model] + 1e-9:
            exclusions["gang_exceeds_model_capacity"] += 1
            continue
        jobs.append(job)
    return tuple(jobs), capacities, dict(sorted(exclusions.items()))


def build_selection_manifest(
    job_csv: Path,
    node_csv: Path,
) -> tuple[ReplaySelection, dict[str, Any]]:
    jobs, capacities, exclusions = load_trace_jobs(job_csv, node_csv)
    selection = select_replay_core(jobs)
    input_job_hash = sha256_file(job_csv)
    input_node_hash = sha256_file(node_csv)
    if input_job_hash == ALIBABA_LOCAL_NORMALIZED_JOB_SHA256:
        serialization_note = (
            "field values were audited against the pinned upstream CSV; "
            "submit_time and duration are serialized as integers locally"
        )
    elif input_job_hash == ALIBABA_UPSTREAM_JOB_SHA256:
        serialization_note = "input bytes match the pinned upstream CSV"
    else:
        serialization_note = "input serialization has not been matched to the pinned upstream CSV"
    selected_all = tuple(
        job
        for job in jobs
        if selection.core_start_hour <= job.release_hour < selection.core_end_hour
    )
    by_priority = Counter(job.priority for job in selected_all)
    by_model = Counter(job.gpu_model for job in selection.spot_jobs)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "source": {
            "dataset": "Alibaba cluster-trace-v2026-spot-gpu",
            "url": "https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2026-spot-gpu",
            "commit": ALIBABA_SOURCE_COMMIT,
            "input_job_csv_sha256": input_job_hash,
            "input_node_csv_sha256": input_node_hash,
            "upstream_job_csv_sha256_at_commit": ALIBABA_UPSTREAM_JOB_SHA256,
            "upstream_node_csv_sha256_at_commit": ALIBABA_UPSTREAM_NODE_SHA256,
            "input_job_serialization_note": serialization_note,
        },
        "normalization": {
            "gpu_count": "gpu_request * worker_num",
            "release_hour": "floor(submit_time / 3600)",
            "required_run_hours": "ceil(duration / 3600)",
            "spot_deadline": "release_hour + required_run_hours + 3",
            "hp_deadline": None,
        },
        "selection": {
            "rule": "minimum absolute distance to median eligible Spot GPU-hours; earliest start breaks ties",
            "core_hours": selection.core_hours,
            "max_spot_duration_hours": selection.max_spot_duration_hours,
            "core_start_hour": selection.core_start_hour,
            "core_end_hour_exclusive": selection.core_end_hour,
            "core_start_seconds": selection.core_start_hour * 3_600,
            "core_end_seconds_exclusive": selection.core_end_hour * 3_600,
            "median_eligible_spot_gpu_hours": round(
                selection.median_eligible_spot_gpu_hours, 6
            ),
            "selected_eligible_spot_gpu_hours": round(
                selection.selected_eligible_spot_gpu_hours, 6
            ),
            "selected_eligible_spot_gpu_hours_hourly_ceiling": round(
                sum(job.gpu_count * job.required_run_hours for job in selection.spot_jobs),
                6,
            ),
        },
        "counts": {
            "normalized_jobs": len(jobs),
            "selected_core_jobs": len(selected_all),
            "selected_core_hp_jobs": by_priority["HP"],
            "selected_core_spot_jobs_before_duration_filter": by_priority["Spot"],
            "selected_eligible_spot_jobs": len(selection.spot_jobs),
            "selected_spot_over_max_duration_excluded": selection.excluded_spot_over_max_duration_count,
            "selected_eligible_spot_jobs_by_model": dict(sorted(by_model.items())),
            "mapping_exclusions": exclusions,
        },
        "model_capacity_gpus": capacities,
        "power_scenarios": [
            {
                "name": scenario.name,
                "pue": scenario.pue,
                "it_overhead_multiplier": scenario.it_overhead_multiplier,
                "active_power_fraction": scenario.active_power_fraction,
                "model_tdp_or_assumed_watts": dict(scenario.model_tdp_watts),
            }
            for scenario in power_scenarios()
        ],
    }
    return selection, manifest


def write_selection_manifest(
    job_csv: Path,
    node_csv: Path,
    output_path: Path,
) -> ReplaySelection:
    selection, manifest = build_selection_manifest(job_csv, node_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return selection
