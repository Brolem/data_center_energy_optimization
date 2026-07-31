from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Parameters:
    flex_ratio: float = 0.30
    max_delay_h: int = 3
    cpu_capacity_pu: float = 0.90
    server_count: int = 12_500
    server_max_power_kw: float = 0.55
    server_idle_power_ratio: float = 0.60
    pue: float = 1.10
    grid_capacity_mw: float = 7.66
    solar_panel_area_m2: float = 20_000.0
    solar_base_efficiency: float = 0.15
    solar_om_cost_cny_per_kw: float = 0.016
    wind_turbine_count: int = 33
    wind_turbine_rated_power_kw: float = 200.0
    wind_cut_in_speed_m_s: float = 3.0
    wind_rated_speed_m_s: float = 11.4
    wind_cut_out_speed_m_s: float = 25.0
    wind_om_cost_cny_per_kw: float = 0.018
    battery_energy_mwh: float = 1.0
    battery_charge_power_mw: float = 0.40
    battery_discharge_power_mw: float = 0.25
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.90
    battery_soc_min: float = 0.10
    battery_soc_max: float = 0.90
    battery_soc_initial: float = 0.50
    battery_om_cost_cny_per_kw: float = 0.18
    battery_max_active_periods: int = 16
    primary_cost_tolerance_cny: float = 0.01
    time_step_h: float = 1.0
    time_limit_s: float = 60.0
    relative_gap: float = 1e-6

    @property
    def server_idle_power_kw(self) -> float:
        return self.server_max_power_kw * self.server_idle_power_ratio

    @property
    def solar_capacity_mw(self) -> float:
        return self.solar_panel_area_m2 * self.solar_base_efficiency / 1000.0

    @property
    def wind_capacity_mw(self) -> float:
        return (
            self.wind_turbine_count
            * self.wind_turbine_rated_power_kw
            / 1000.0
        )

    def it_power_mw(self, cpu_utilization_pu: float) -> float:
        server_power_kw = self.server_idle_power_kw + (
            self.server_max_power_kw - self.server_idle_power_kw
        ) * cpu_utilization_pu
        return self.server_count * server_power_kw / 1000.0

    def dc_power_mw(self, cpu_utilization_pu: float) -> float:
        return self.pue * self.it_power_mw(cpu_utilization_pu)
