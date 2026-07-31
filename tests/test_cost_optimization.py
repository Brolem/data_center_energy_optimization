from __future__ import annotations

import unittest
from dataclasses import fields, replace
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

import scip_first_version.data as energy_data
from scip_first_version.config import Parameters


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEATHER_SOURCE_PATH = (
    PROJECT_ROOT / "data" / "phoenix_nasa_power_20190501_20190528_hourly.csv"
)
SCENARIO_PATH = (
    PROJECT_ROOT
    / "data"
    / "provisional_phoenix_weather_qinghai_tou_scenario.csv"
)


class ProvisionalEnergyScenarioTests(unittest.TestCase):
    def test_solar_power_uses_base_efficiency_without_performance_factor(self) -> None:
        irradiance = np.array([0.0, 1000.0, 1200.0])

        actual = energy_data.solar_available_power_mw(
            irradiance,
            Parameters(),
        )

        np.testing.assert_array_equal(actual, np.array([0.0, 3.0, 3.0]))

    def test_wind_power_follows_exact_piecewise_curve(self) -> None:
        wind_speeds = np.array([0.0, 3.0, 7.2, 11.4, 24.999, 25.0])
        expected_middle = 6.6 * (
            (7.2 ** 3 - 3.0 ** 3) / (11.4 ** 3 - 3.0 ** 3)
        )
        expected = np.array(
            [0.0, 0.0, expected_middle, 6.6, 6.6, 0.0]
        )

        actual = energy_data.wind_available_power_mw(
            wind_speeds,
            Parameters(),
        )

        np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-12)

    def test_weather_source_has_exact_fields_and_continuous_672_hours(self) -> None:
        source = energy_data.load_phoenix_weather_source(WEATHER_SOURCE_PATH)

        self.assertEqual(
            list(source.columns),
            [
                "timestamp_lst",
                "solar_irradiance_wh_m2",
                "wind_speed_50m_m_s",
            ],
        )
        self.assertEqual(len(source), 672)
        self.assertFalse(source.isna().any().any())
        self.assertFalse(source["timestamp_lst"].duplicated().any())
        pd.testing.assert_series_equal(
            source["timestamp_lst"],
            pd.Series(
                pd.date_range(
                    "2019-05-01 00:00:00",
                    "2019-05-28 23:00:00",
                    freq="h",
                ),
                name="timestamp_lst",
            ),
        )
        weather = source[
            ["solar_irradiance_wh_m2", "wind_speed_50m_m_s"]
        ].to_numpy(dtype=float)
        self.assertTrue(np.isfinite(weather).all())
        self.assertTrue((weather >= 0.0).all())

    def test_weather_source_rejects_missing_value_and_missing_hour(self) -> None:
        raw = pd.read_csv(WEATHER_SOURCE_PATH)
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            missing_value_path = temporary_path / "missing_value.csv"
            raw_with_missing_value = raw.copy()
            raw_with_missing_value.loc[0, "wind_speed_50m_m_s"] = np.nan
            raw_with_missing_value.to_csv(missing_value_path, index=False)
            with self.assertRaises(ValueError):
                energy_data.load_phoenix_weather_source(missing_value_path)

            missing_hour_path = temporary_path / "missing_hour.csv"
            raw.iloc[1:].to_csv(missing_hour_path, index=False)
            with self.assertRaises(ValueError):
                energy_data.load_phoenix_weather_source(missing_hour_path)

    def test_weather_source_rejects_strict_timestamp_errors(self) -> None:
        raw = pd.read_csv(WEATHER_SOURCE_PATH)

        duplicate = raw.copy()
        duplicate.loc[1, "timestamp_lst"] = duplicate.loc[0, "timestamp_lst"]

        out_of_order = raw.copy()
        first_timestamp = out_of_order.loc[0, "timestamp_lst"]
        second_timestamp = out_of_order.loc[1, "timestamp_lst"]
        out_of_order.loc[0, "timestamp_lst"] = second_timestamp
        out_of_order.loc[1, "timestamp_lst"] = first_timestamp

        wrong_start_date = raw.copy()
        wrong_start_date.loc[0, "timestamp_lst"] = "2019-04-30T00:00:00"

        unparseable = raw.copy()
        unparseable.loc[0, "timestamp_lst"] = "not-a-timestamp"

        invalid_sources = {
            "duplicate": duplicate,
            "out_of_order": out_of_order,
            "wrong_start_date": wrong_start_date,
            "unparseable": unparseable,
        }
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            for label, invalid_source in invalid_sources.items():
                with self.subTest(label=label):
                    self.assertEqual(len(invalid_source), 672)
                    source_path = temporary_path / f"{label}.csv"
                    invalid_source.to_csv(source_path, index=False)
                    with self.assertRaises(ValueError):
                        energy_data.load_phoenix_weather_source(source_path)

    def test_builder_averages_hourly_power_calculated_for_each_source_row(self) -> None:
        params = Parameters()
        source = energy_data.load_phoenix_weather_source(WEATHER_SOURCE_PATH)
        expected_rows = source.copy()
        expected_rows["hour"] = expected_rows["timestamp_lst"].dt.hour
        expected_rows["solar_available_mw"] = (
            energy_data.solar_available_power_mw(
                expected_rows["solar_irradiance_wh_m2"].to_numpy(dtype=float),
                params,
            )
        )
        expected_rows["wind_available_mw"] = (
            energy_data.wind_available_power_mw(
                expected_rows["wind_speed_50m_m_s"].to_numpy(dtype=float),
                params,
            )
        )
        expected = (
            expected_rows.groupby("hour", as_index=False)[
                [
                    "solar_irradiance_wh_m2",
                    "wind_speed_50m_m_s",
                    "solar_available_mw",
                    "wind_available_mw",
                ]
            ]
            .mean()
        )

        scenario = energy_data.build_provisional_energy_scenario(
            WEATHER_SOURCE_PATH,
            params,
        )

        for column in expected.columns:
            np.testing.assert_allclose(
                scenario[column].to_numpy(dtype=float),
                expected[column].to_numpy(dtype=float),
                rtol=0.0,
                atol=1e-12,
            )

        mean_wind_recalculation = energy_data.wind_available_power_mw(
            scenario["wind_speed_50m_m_s"].to_numpy(dtype=float),
            params,
        )
        self.assertFalse(
            np.allclose(
                scenario["wind_available_mw"].to_numpy(dtype=float),
                mean_wind_recalculation,
                rtol=0.0,
                atol=1e-10,
            )
        )

    def test_builder_assigns_exact_qinghai_tou(self) -> None:
        scenario = energy_data.build_provisional_energy_scenario(
            WEATHER_SOURCE_PATH,
            Parameters(),
        )
        expected_periods = [
            "valley" if 0 <= hour < 8 else
            "peak" if (9 <= hour < 13 or 18 <= hour < 23) else
            "flat"
            for hour in range(24)
        ]
        expected_prices = [
            0.1804 if period == "valley" else
            0.7174 if period == "peak" else
            0.4489
            for period in expected_periods
        ]

        self.assertEqual(scenario["tou_period"].tolist(), expected_periods)
        np.testing.assert_array_equal(
            scenario["electricity_price_cny_per_kwh"].to_numpy(dtype=float),
            np.array(expected_prices),
        )

    def test_builder_has_exact_columns_and_capacity_bounds(self) -> None:
        scenario = energy_data.build_provisional_energy_scenario(
            WEATHER_SOURCE_PATH,
            Parameters(),
        )

        self.assertEqual(
            list(scenario.columns),
            [
                "hour",
                "solar_irradiance_wh_m2",
                "wind_speed_50m_m_s",
                "solar_available_mw",
                "wind_available_mw",
                "tou_period",
                "electricity_price_cny_per_kwh",
            ],
        )
        self.assertNotIn("electricity_price_usd_per_kwh", scenario.columns)
        self.assertLessEqual(scenario["solar_available_mw"].max(), 3.0)
        self.assertLessEqual(scenario["wind_available_mw"].max(), 6.6)

    def test_committed_scenario_exactly_matches_builder(self) -> None:
        expected = energy_data.build_provisional_energy_scenario(
            WEATHER_SOURCE_PATH,
            Parameters(),
        )
        actual = energy_data.load_energy_scenario(
            SCENARIO_PATH,
            Parameters(),
            weather_source_path=WEATHER_SOURCE_PATH,
        )

        self.assertTrue(actual["tou_period"].equals(expected["tou_period"]))
        for column in actual.columns:
            if column != "tou_period":
                np.testing.assert_allclose(
                    actual[column].to_numpy(dtype=float),
                    expected[column].to_numpy(dtype=float),
                    rtol=0.0,
                    atol=1e-10,
                )

    def test_source_validation_names_each_changed_weather_or_power_column(
        self,
    ) -> None:
        checked_columns = [
            "solar_irradiance_wh_m2",
            "wind_speed_50m_m_s",
            "solar_available_mw",
            "wind_available_mw",
        ]
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            for column in checked_columns:
                with self.subTest(column=column):
                    scenario = energy_data.build_provisional_energy_scenario(
                        WEATHER_SOURCE_PATH,
                        Parameters(),
                    )
                    scenario.loc[0, column] += 0.01
                    scenario_path = temporary_path / f"{column}.csv"
                    scenario.to_csv(scenario_path, index=False)

                    with self.assertRaisesRegex(ValueError, column):
                        energy_data.load_energy_scenario(
                            scenario_path,
                            Parameters(),
                            weather_source_path=WEATHER_SOURCE_PATH,
                        )

    def test_scenario_rejects_missing_hour(self) -> None:
        scenario = energy_data.build_provisional_energy_scenario(
            WEATHER_SOURCE_PATH,
            Parameters(),
        ).iloc[:-1]
        with TemporaryDirectory() as temporary_directory:
            scenario_path = Path(temporary_directory) / "scenario.csv"
            scenario.to_csv(scenario_path, index=False)

            with self.assertRaises(ValueError):
                energy_data.load_energy_scenario(
                    scenario_path,
                    Parameters(),
                )


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
        self.assertEqual(params.grid_capacity_mw, 7.66)

    def test_renewable_parameters_match_approved_scale(self) -> None:
        params = Parameters()

        self.assertEqual(params.solar_panel_area_m2, 20_000.0)
        self.assertEqual(params.solar_base_efficiency, 0.15)
        self.assertAlmostEqual(params.solar_capacity_mw, 3.0)
        self.assertEqual(params.solar_om_cost_cny_per_kw, 0.016)
        self.assertEqual(params.wind_turbine_count, 33)
        self.assertEqual(params.wind_turbine_rated_power_kw, 200.0)
        self.assertAlmostEqual(params.wind_capacity_mw, 6.6)
        self.assertEqual(params.wind_cut_in_speed_m_s, 3.0)
        self.assertEqual(params.wind_rated_speed_m_s, 11.4)
        self.assertEqual(params.wind_cut_out_speed_m_s, 25.0)
        self.assertEqual(params.wind_om_cost_cny_per_kw, 0.018)

    def test_battery_parameters_match_approved_scale(self) -> None:
        params = Parameters()

        self.assertEqual(params.battery_energy_mwh, 1.0)
        self.assertEqual(params.battery_charge_power_mw, 0.4)
        self.assertEqual(params.battery_discharge_power_mw, 0.25)
        self.assertEqual(params.charge_efficiency, 0.95)
        self.assertEqual(params.discharge_efficiency, 0.90)
        self.assertEqual(params.battery_soc_min, 0.10)
        self.assertEqual(params.battery_soc_max, 0.90)
        self.assertEqual(params.battery_soc_initial, 0.50)
        self.assertEqual(params.battery_om_cost_cny_per_kw, 0.18)
        self.assertEqual(params.battery_max_active_periods, 16)

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
                "solar_om_cost_cny_per_kw",
                "wind_turbine_count",
                "wind_turbine_rated_power_kw",
                "wind_cut_in_speed_m_s",
                "wind_rated_speed_m_s",
                "wind_cut_out_speed_m_s",
                "wind_om_cost_cny_per_kw",
                "battery_energy_mwh",
                "battery_charge_power_mw",
                "battery_discharge_power_mw",
                "charge_efficiency",
                "discharge_efficiency",
                "battery_soc_min",
                "battery_soc_max",
                "battery_soc_initial",
                "battery_om_cost_cny_per_kw",
                "battery_max_active_periods",
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
