from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PendingFlexibleTask:
    origin_hour: int
    remaining_cpu_pu: float


@dataclass(frozen=True)
class WindowSolveState:
    stored_energy_mwh: float
    pending_flexible_tasks: tuple[PendingFlexibleTask, ...]
