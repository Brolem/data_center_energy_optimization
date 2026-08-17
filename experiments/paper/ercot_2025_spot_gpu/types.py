from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnergyInterval:
    """One hourly energy interval expressed by its UTC start and end instants."""

    interval_start_utc: str
    interval_end_utc: str
