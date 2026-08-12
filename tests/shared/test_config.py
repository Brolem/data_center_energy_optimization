from __future__ import annotations

import unittest
from dataclasses import fields, replace

from dc_energy_opt.config import Parameters


class ParameterScaleTests(unittest.TestCase):
    def test_compute_and_grid_parameters_match_approved_scale(self) -> None:
        params = Parameters()

        self.assertEqual(params.flex_ratio, 0.30)
        self.assertEqual(params.max_delay_h, 3)
        self.assertEqual(params.cpu_capacity_pu, 0.90)
        self.assertEqual(params.server_count, 12_500)
        self.assertEqual(params.server_max_power_kw, 0.55)
        self.assertEqual(params.server_idle_power_ratio, 0.60)
        self.assertAlmostEqual(params.server_idle_power_kw, 0.33)
        self.assertEqual(params.pue, 1.10)
        self.assertAlmostEqual(params.it_power_mw(0.0), 4.125)
        self.assertAlmostEqual(params.it_power_mw(0.90), 6.60)
        self.assertAlmostEqual(params.dc_power_mw(0.90), 7.26)
        self.assertEqual(params.grid_capacity_mw, 6.60)

    def test_renewable_parameters_match_approved_scale(self) -> None:
        params = Parameters()

        self.assertEqual(params.solar_panel_area_m2, 20_000.0)
        self.assertEqual(params.solar_base_efficiency, 0.15)
        self.assertAlmostEqual(params.solar_capacity_mw, 3.0)
        self.assertEqual(params.solar_dc_ac_ratio, 1.15)
        self.assertAlmostEqual(
            params.solar_inverter_capacity_mw,
            3.0 / 1.15,
        )
        self.assertEqual(params.solar_om_cost_cny_per_kwh, 0.03)
        self.assertEqual(params.wind_turbine_count, 33)
        self.assertEqual(params.wind_turbine_rated_power_kw, 200.0)
        self.assertAlmostEqual(params.wind_capacity_mw, 6.6)
        self.assertEqual(params.wind_cut_in_speed_m_s, 3.0)
        self.assertEqual(params.wind_rated_speed_m_s, 11.4)
        self.assertEqual(params.wind_cut_out_speed_m_s, 25.0)
        self.assertEqual(params.wind_om_cost_cny_per_kwh, 0.09)

    def test_battery_parameters_match_approved_scale(self) -> None:
        params = Parameters()

        self.assertEqual(params.battery_energy_mwh, 2.0)
        self.assertEqual(params.battery_charge_power_mw, 0.5)
        self.assertEqual(params.battery_discharge_power_mw, 0.5)
        self.assertEqual(params.charge_efficiency, 0.95)
        self.assertEqual(params.discharge_efficiency, 0.90)
        self.assertEqual(params.battery_soc_min, 0.10)
        self.assertEqual(params.battery_soc_max, 0.90)
        self.assertEqual(params.battery_soc_initial, 0.50)
        self.assertEqual(params.battery_om_cost_cny_per_kwh, 0.015)
        self.assertEqual(
            params.battery_degradation_cost_cny_per_kwh,
            0.15,
        )

    def test_solver_parameters_match_approved_scale(self) -> None:
        params = Parameters()

        self.assertEqual(params.primary_cost_tolerance_cny, 0.01)
        self.assertEqual(params.time_step_h, 1.0)
        self.assertEqual(params.time_limit_s, 60.0)
        self.assertEqual(params.relative_gap, 1e-6)

    def test_only_approved_values_are_stored_as_parameter_fields(self) -> None:
        self.assertEqual(
            {field.name for field in fields(Parameters)},
            {
                "flex_ratio",
                "max_delay_h",
                "cpu_capacity_pu",
                "server_count",
                "server_max_power_kw",
                "server_idle_power_ratio",
                "pue",
                "grid_capacity_mw",
                "solar_panel_area_m2",
                "solar_base_efficiency",
                "solar_dc_ac_ratio",
                "solar_om_cost_cny_per_kwh",
                "wind_turbine_count",
                "wind_turbine_rated_power_kw",
                "wind_cut_in_speed_m_s",
                "wind_rated_speed_m_s",
                "wind_cut_out_speed_m_s",
                "wind_om_cost_cny_per_kwh",
                "battery_energy_mwh",
                "battery_charge_power_mw",
                "battery_discharge_power_mw",
                "charge_efficiency",
                "discharge_efficiency",
                "battery_soc_min",
                "battery_soc_max",
                "battery_soc_initial",
                "battery_om_cost_cny_per_kwh",
                "battery_degradation_cost_cny_per_kwh",
                "primary_cost_tolerance_cny",
                "time_step_h",
                "time_limit_s",
                "relative_gap",
            },
        )

    def test_compute_power_derivations_follow_replaced_base_fields(self) -> None:
        server_max_power_kw = 0.72
        server_idle_power_ratio = 0.25
        server_count = 4_321
        pue = 1.37
        cpu_utilization_pu = 0.68
        params = replace(
            Parameters(),
            server_max_power_kw=server_max_power_kw,
            server_idle_power_ratio=server_idle_power_ratio,
            server_count=server_count,
            pue=pue,
        )

        expected_idle_power_kw = (
            server_max_power_kw * server_idle_power_ratio
        )
        expected_server_power_kw = expected_idle_power_kw + (
            server_max_power_kw - expected_idle_power_kw
        ) * cpu_utilization_pu
        expected_it_power_mw = (
            server_count * expected_server_power_kw / 1000.0
        )
        expected_dc_power_mw = pue * expected_it_power_mw

        self.assertAlmostEqual(
            params.server_idle_power_kw,
            expected_idle_power_kw,
        )
        self.assertAlmostEqual(
            params.it_power_mw(cpu_utilization_pu),
            expected_it_power_mw,
        )
        self.assertAlmostEqual(
            params.dc_power_mw(cpu_utilization_pu),
            expected_dc_power_mw,
        )

    def test_solar_capacity_follows_replaced_base_fields(self) -> None:
        solar_panel_area_m2 = 13_579.0
        solar_base_efficiency = 0.21
        params = replace(
            Parameters(),
            solar_panel_area_m2=solar_panel_area_m2,
            solar_base_efficiency=solar_base_efficiency,
        )
        expected_capacity_mw = (
            solar_panel_area_m2 * solar_base_efficiency / 1000.0
        )

        self.assertAlmostEqual(
            params.solar_capacity_mw,
            expected_capacity_mw,
        )

    def test_wind_capacity_follows_replaced_base_fields(self) -> None:
        wind_turbine_count = 47
        wind_turbine_rated_power_kw = 315.0
        params = replace(
            Parameters(),
            wind_turbine_count=wind_turbine_count,
            wind_turbine_rated_power_kw=wind_turbine_rated_power_kw,
        )
        expected_capacity_mw = (
            wind_turbine_count * wind_turbine_rated_power_kw / 1000.0
        )

        self.assertAlmostEqual(
            params.wind_capacity_mw,
            expected_capacity_mw,
        )


if __name__ == "__main__":
    unittest.main()
