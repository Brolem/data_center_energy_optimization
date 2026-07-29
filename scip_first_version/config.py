from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Parameters:
    flex_ratio: float = 0.30
    max_delay_h: int = 3
    cpu_capacity_pu: float = 0.65
    idle_power_ratio: float = 0.60
    it_peak_power_mw: float = 100.0
    pue: float = 1.20
    battery_energy_mwh: float = 4.0
    battery_soc_min: float = 0.10
    battery_soc_max: float = 0.90
    battery_soc_initial: float = 0.50
    battery_power_mw: float = 1.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    time_step_h: float = 1.0
    time_limit_s: float = 60.0
    relative_gap: float = 1e-3
    throughput_tiebreaker: float = 1e-6
