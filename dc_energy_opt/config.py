from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Parameters:
    flex_ratio: float = 0.30
    max_delay_h: int = 3
    cpu_capacity_pu: float = 0.90
    server_count: int = 12_500
    server_max_power_kw: float = 0.55
    server_idle_power_ratio: float = 0.60
    pue: float = 1.10
    grid_capacity_mw: float = 6.60
    solar_panel_area_m2: float = 20_000.0
    solar_base_efficiency: float = 0.15
    solar_dc_ac_ratio: float = 1.15
    solar_om_cost_cny_per_kwh: float = 0.03
    wind_turbine_count: int = 33
    wind_turbine_rated_power_kw: float = 200.0
    wind_cut_in_speed_m_s: float = 3.0
    wind_rated_speed_m_s: float = 11.4
    wind_cut_out_speed_m_s: float = 25.0
    wind_om_cost_cny_per_kwh: float = 0.09
    battery_energy_mwh: float = 2.0
    battery_charge_power_mw: float = 0.50
    battery_discharge_power_mw: float = 0.50
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.90
    battery_soc_min: float = 0.10
    battery_soc_max: float = 0.90
    battery_soc_initial: float = 0.50
    battery_om_cost_cny_per_kwh: float = 0.015
    battery_degradation_cost_cny_per_kwh: float = 0.15
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
    def solar_inverter_capacity_mw(self) -> float:
        return self.solar_capacity_mw / self.solar_dc_ac_ratio

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


@dataclass(frozen=True)
class ScenarioConfig:
    workload_data: Path
    energy_data: Path
    main_output_dir: Path
    flex_ratio_sensitivity_output_dir: Path
    storage_scale_sensitivity_output_dir: Path
    storage_energy_power_sensitivity_output_dir: Path


HOUSTON_2020 = ScenarioConfig(
    workload_data=Path("data/workload/google_2019_28d_5min.csv"),
    energy_data=Path("data/energy/houston_2020_may_hourly.csv"),
    main_output_dir=Path("outputs/houston_2020_main"),
    flex_ratio_sensitivity_output_dir=Path(
        "outputs/houston_2020_flex_ratio_sensitivity"
    ),
    storage_scale_sensitivity_output_dir=Path(
        "outputs/houston_2020_storage_scale_sensitivity"
    ),
    storage_energy_power_sensitivity_output_dir=Path(
        "outputs/houston_2020_storage_energy_power_sensitivity"
    ),
)
