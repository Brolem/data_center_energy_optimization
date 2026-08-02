from __future__ import annotations

import hashlib
import unittest
from dataclasses import fields, replace
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

import dc_energy_opt.data as energy_data
from scripts.build_houston_2020_energy_scenario import (
    _load_ge_turbine,
    _sha256_normalized_text,
)
from dc_energy_opt.config import Parameters
from dc_energy_opt.model import (
    PendingFlexibleTask,
    _solve_status_is_accepted,
    build_and_solve,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEATHER_SOURCE_PATH = (
    PROJECT_ROOT / "data" / "phoenix_nasa_power_20190501_20190528_hourly.csv"
)
SCENARIO_PATH = (
    PROJECT_ROOT
    / "data"
    / "provisional_phoenix_weather_qinghai_tou_scenario.csv"
)
HOUSTON_SCENARIO_PATH = (
    PROJECT_ROOT / "data" / "houston_2020_main_experiment_energy_scenario.csv"
)


class HoustonEnergyScenarioTests(unittest.TestCase):
    def test_source_hash_normalizes_only_crlf_line_endings(self) -> None:
        content_lf = b"first line\nsecond line\n"
        expected = hashlib.sha256(content_lf).hexdigest().upper()
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            lf_path = root / "lf.txt"
            crlf_path = root / "crlf.txt"
            lf_path.write_bytes(content_lf)
            crlf_path.write_bytes(content_lf.replace(b"\n", b"\r\n"))

            self.assertEqual(_sha256_normalized_text(lf_path), expected)
            self.assertEqual(_sha256_normalized_text(crlf_path), expected)

    def _valid_scenario(self) -> pd.DataFrame:
        timestamps = pd.date_range(
            "2020-04-30 00:00:00",
            "2020-05-29 02:00:00",
            freq="h",
        )
        periods, prices = energy_data._qinghai_tou(timestamps.hour.to_numpy())
        return pd.DataFrame(
            {
                "timestamp_lst": timestamps.strftime("%Y-%m-%dT%H:%M:%S"),
                "solar_available_mw": np.zeros(len(timestamps)),
                "wind_available_mw": np.zeros(len(timestamps)),
                "tou_period": periods,
                "electricity_price_cny_per_kwh": prices,
            }
        )

    def test_loader_accepts_exact_main_window_schema_and_tariff(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            scenario_path = Path(temporary_directory) / "houston.csv"
            self._valid_scenario().to_csv(scenario_path, index=False)

            scenario = energy_data.load_houston_energy_scenario(
                scenario_path,
                Parameters(),
            )

        self.assertEqual(len(scenario), 699)
        self.assertEqual(
            list(scenario.columns),
            [
                "timestamp_lst",
                "solar_available_mw",
                "wind_available_mw",
                "tou_period",
                "electricity_price_cny_per_kwh",
            ],
        )
        self.assertEqual(scenario.loc[0, "tou_period"], "valley")
        self.assertEqual(
            scenario.loc[0, "electricity_price_cny_per_kwh"],
            0.1804,
        )

    def test_loader_rejects_capacity_and_timestamp_violations(self) -> None:
        invalid_scenarios = {}
        solar_over_capacity = self._valid_scenario()
        solar_over_capacity.loc[0, "solar_available_mw"] = (
            Parameters().solar_inverter_capacity_mw + 0.001
        )
        invalid_scenarios["solar"] = solar_over_capacity

        wind_over_capacity = self._valid_scenario()
        wind_over_capacity.loc[0, "wind_available_mw"] = 6.601
        invalid_scenarios["wind"] = wind_over_capacity

        missing_hour = self._valid_scenario().drop(index=1)
        invalid_scenarios["timestamp"] = missing_hour

        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            for label, invalid_scenario in invalid_scenarios.items():
                with self.subTest(label=label):
                    scenario_path = temporary_path / f"{label}.csv"
                    invalid_scenario.to_csv(scenario_path, index=False)
                    with self.assertRaises(ValueError):
                        energy_data.load_houston_energy_scenario(
                            scenario_path,
                            Parameters(),
                        )

    def test_committed_houston_scenario_is_complete(self) -> None:
        scenario = energy_data.load_houston_energy_scenario(
            HOUSTON_SCENARIO_PATH,
            Parameters(),
        )

        self.assertEqual(len(scenario), 699)
        self.assertGreater(scenario["solar_available_mw"].sum(), 0.0)
        self.assertGreater(scenario["wind_available_mw"].sum(), 0.0)

    def test_turbine_loader_skips_unrelated_malformed_rows(self) -> None:
        catalog = "\n".join(
            [
                "Name,kW Rating,Rotor Diameter,IEC Wind Speed Class,Wind Speed Array,Power Curve Array",
                "units,units,units,units,units,units",
                "metadata,metadata,metadata,metadata,metadata,metadata",
                "Broken,row,with,too,many,fields,ignored",
                "GE 1.5sle,1500,77,IIa,0|1|2,0|0|1500",
            ]
        )
        with TemporaryDirectory() as temporary_directory:
            catalog_path = Path(temporary_directory) / "Wind_Turbines.csv"
            catalog_path.write_text(catalog, encoding="utf-8")

            turbine = _load_ge_turbine(catalog_path)

        self.assertEqual(turbine["Name"], "GE 1.5sle")
        self.assertEqual(turbine["kW Rating"], 1500)
        self.assertEqual(turbine["Rotor Diameter"], 77)


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


class CostOptimizationModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workload_path = (
            PROJECT_ROOT
            / "data"
            / "instance_usage_grouped_300_seconds_month.csv"
        )
        _, hourly, representative_day, _ = energy_data.load_and_prepare(
            workload_path
        )
        if representative_day != 8:
            raise AssertionError(
                f"代表日应为 8，实际为 {representative_day}。"
            )
        cls.cpu_arrival = (
            hourly[hourly["day"] == representative_day]
            .sort_values("hour")["avg_cpu"]
            .to_numpy(dtype=float)
        )
        cls.params = Parameters()
        cls.scenario = energy_data.load_energy_scenario(
            SCENARIO_PATH,
            cls.params,
            weather_source_path=WEATHER_SOURCE_PATH,
        )
        cls.temporary_directory = TemporaryDirectory()
        cls.output_dir = Path(cls.temporary_directory.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def solve(
        self,
        *,
        cpu_arrival: np.ndarray | None = None,
        solar_available_mw: np.ndarray | None = None,
        wind_available_mw: np.ndarray | None = None,
        electricity_price_cny_per_kwh: np.ndarray | None = None,
        params: Parameters | None = None,
        enable_shift: bool = False,
        enable_storage: bool = False,
        enable_renewables: bool = True,
        case_name: str,
    ) -> tuple[pd.DataFrame, dict]:
        return build_and_solve(
            cpu_arrival=(
                self.cpu_arrival if cpu_arrival is None else cpu_arrival
            ),
            solar_available_mw=(
                self.scenario["solar_available_mw"].to_numpy(dtype=float)
                if solar_available_mw is None
                else solar_available_mw
            ),
            wind_available_mw=(
                self.scenario["wind_available_mw"].to_numpy(dtype=float)
                if wind_available_mw is None
                else wind_available_mw
            ),
            electricity_price_cny_per_kwh=(
                self.scenario[
                    "electricity_price_cny_per_kwh"
                ].to_numpy(dtype=float)
                if electricity_price_cny_per_kwh is None
                else electricity_price_cny_per_kwh
            ),
            params=self.params if params is None else params,
            enable_shift=enable_shift,
            enable_storage=enable_storage,
            enable_renewables=enable_renewables,
            case_name=case_name,
            output_dir=self.output_dir,
            show_log=False,
        )

    def test_primary_costs_are_independently_recomputed_in_cny(self) -> None:
        result, metrics = self.solve(case_name="primary_cost_recompute")
        time_step_h = self.params.time_step_h
        expected_grid = float(
            (
                result["electricity_price_cny_per_kwh"]
                * result["grid_power_mw"]
                * time_step_h
                * 1000.0
            ).sum()
        )
        expected_solar = float(
            (
                self.params.solar_om_cost_cny_per_kwh
                * result["solar_used_mw"]
                * time_step_h
                * 1000.0
            ).sum()
        )
        expected_wind = float(
            (
                self.params.wind_om_cost_cny_per_kwh
                * result["wind_used_mw"]
                * time_step_h
                * 1000.0
            ).sum()
        )
        expected_hourly_battery = (
            self.params.battery_om_cost_cny_per_kwh
            * (result["charge_mw"] + result["discharge_mw"])
            * time_step_h
            * 1000.0
        )
        expected_battery = float(expected_hourly_battery.sum())
        expected_hourly_battery_degradation = (
            self.params.battery_degradation_cost_cny_per_kwh
            * result["discharge_mw"]
            * time_step_h
            * 1000.0
        )
        expected_battery_degradation = float(
            expected_hourly_battery_degradation.sum()
        )
        expected_operating = (
            expected_grid
            + expected_solar
            + expected_wind
            + expected_battery
            + expected_battery_degradation
        )

        self.assertAlmostEqual(
            metrics["grid_purchase_cost_cny"], expected_grid, places=7
        )
        self.assertAlmostEqual(
            metrics["solar_om_cost_cny"], expected_solar, places=7
        )
        self.assertAlmostEqual(
            metrics["wind_om_cost_cny"], expected_wind, places=7
        )
        self.assertEqual(metrics["battery_om_cost_cny"], expected_battery)
        np.testing.assert_allclose(
            result["hourly_battery_om_cost_cny"],
            expected_hourly_battery,
            rtol=0.0,
            atol=1e-12,
        )
        self.assertEqual(
            metrics["battery_degradation_cost_cny"],
            expected_battery_degradation,
        )
        np.testing.assert_allclose(
            result["hourly_battery_degradation_cost_cny"],
            expected_hourly_battery_degradation,
            rtol=0.0,
            atol=1e-12,
        )
        self.assertAlmostEqual(
            metrics["operating_cost_cny"], expected_operating, places=7
        )
        self.assertAlmostEqual(
            metrics["primary_operating_cost_cny"],
            expected_operating,
            places=7,
        )
        self.assertTrue(
            np.allclose(
                result["hourly_operating_cost_cny"],
                result[
                    [
                        "hourly_grid_purchase_cost_cny",
                        "hourly_solar_om_cost_cny",
                        "hourly_wind_om_cost_cny",
                        "hourly_battery_om_cost_cny",
                        "hourly_battery_degradation_cost_cny",
                    ]
                ].sum(axis=1),
                rtol=0.0,
                atol=1e-9,
            )
        )
        self.assertTrue(
            (self.output_dir / "primary_cost_recompute_primary.lp").is_file()
        )
        self.assertIn(
            "battery_om_cost_expr", build_and_solve.__code__.co_varnames
        )
        self.assertIn(
            "battery_degradation_cost_expr",
            build_and_solve.__code__.co_varnames,
        )
        self.assertIn(
            "primary_cost_expr", build_and_solve.__code__.co_varnames
        )
        self.assertEqual(metrics["status"], "optimal")
        self.assertAlmostEqual(
            metrics["solve_time_s"],
            metrics["primary_solve_time_s"]
            + metrics["secondary_solve_time_s"],
        )
        self.assertEqual(
            metrics["mip_gap"],
            max(metrics["primary_gap"], metrics["secondary_gap"]),
        )

    def test_full_cpu_grid_only_is_infeasible_under_fixed_grid_limit(self) -> None:
        cpu_arrival = np.full(24, 0.90)
        zeros = np.zeros(24)
        self.assertAlmostEqual(self.params.it_power_mw(0.90), 6.60)
        self.assertAlmostEqual(self.params.dc_power_mw(0.90), 7.26)
        with self.assertRaisesRegex(RuntimeError, "status=infeasible"):
            self.solve(
                cpu_arrival=cpu_arrival,
                solar_available_mw=zeros,
                wind_available_mw=zeros,
                enable_renewables=False,
                case_name="full_cpu_grid_only",
            )

    def test_renewable_allocation_and_power_balance_hold_hourly(self) -> None:
        result, _ = self.solve(case_name="renewable_balance")

        np.testing.assert_allclose(
            result["solar_used_mw"] + result["solar_curtailed_mw"],
            result["solar_available_mw"],
            rtol=0.0,
            atol=1e-9,
        )
        np.testing.assert_allclose(
            result["wind_used_mw"] + result["wind_curtailed_mw"],
            result["wind_available_mw"],
            rtol=0.0,
            atol=1e-9,
        )
        np.testing.assert_allclose(
            result["grid_power_mw"]
            + result["solar_used_mw"]
            + result["wind_used_mw"],
            result["dc_power_mw"],
            rtol=0.0,
            atol=1e-9,
        )

    def test_high_renewables_cause_positive_curtailment(self) -> None:
        renewable_power = np.full(24, 10.0)
        result, metrics = self.solve(
            solar_available_mw=renewable_power,
            wind_available_mw=renewable_power,
            case_name="high_renewable_curtailment",
        )

        self.assertGreater(
            metrics["renewable_curtailment_energy_mwh"], 0.0
        )
        self.assertGreater(
            float(
                (
                    result["solar_curtailed_mw"]
                    + result["wind_curtailed_mw"]
                ).sum()
            ),
            0.0,
        )
        self.assertGreaterEqual(float(result["grid_power_mw"].min()), 0.0)

    def test_infeasible_cpu_capacity_raises_explicit_error(self) -> None:
        params = replace(self.params, cpu_capacity_pu=0.01)

        with self.assertRaisesRegex(
            RuntimeError,
            r"stage=primary.*case=infeasible_cpu_capacity"
            r".*status=infeasible.*gap=.*primal_bound=.*dual_bound="
            r".*未找到可行解",
        ):
            self.solve(
                params=params,
                enable_renewables=False,
                case_name="infeasible_cpu_capacity",
            )

    def test_solve_status_acceptance_rejects_invalid_results(self) -> None:
        relative_gap = self.params.relative_gap
        scip_infinity = 1e20

        self.assertTrue(
            _solve_status_is_accepted(
                "optimal", 0.0, relative_gap, scip_infinity
            )
        )
        self.assertTrue(
            _solve_status_is_accepted(
                "gaplimit",
                relative_gap + 1e-12,
                relative_gap,
                scip_infinity,
            )
        )
        for status, gap in (
            ("timelimit", 0.0),
            ("gaplimit", relative_gap + 1e-9),
            ("gaplimit", float("nan")),
            ("gaplimit", float("inf")),
            ("gaplimit", scip_infinity),
            ("optimal", scip_infinity),
        ):
            with self.subTest(status=status, gap=gap):
                self.assertFalse(
                    _solve_status_is_accepted(
                        status, gap, relative_gap, scip_infinity
                    )
                )

    def test_storage_rejects_zero_energy_capacity(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            r"battery_energy_mwh 必须大于 0",
        ):
            self.solve(
                params=replace(self.params, battery_energy_mwh=0.0),
                enable_storage=True,
                case_name="zero_storage_energy_capacity",
            )

    def test_explicit_storage_boundaries_return_committed_state(self) -> None:
        horizon = 6
        result, _, state = build_and_solve(
            cpu_arrival=np.full(horizon, 0.50),
            solar_available_mw=np.zeros(horizon),
            wind_available_mw=np.zeros(horizon),
            electricity_price_cny_per_kwh=np.full(horizon, 0.4489),
            params=self.params,
            enable_shift=False,
            enable_storage=True,
            enable_renewables=False,
            case_name="explicit_storage_boundaries",
            output_dir=self.output_dir,
            show_log=False,
            initial_stored_energy_mwh=0.8,
            terminal_stored_energy_mwh=1.2,
            committed_stored_energy_mwh=0.9,
            commit_hours=3,
            return_state=True,
        )

        self.assertAlmostEqual(result.loc[0, "soc_start"], 0.4)
        self.assertAlmostEqual(result.loc[horizon - 1, "soc_end"], 0.6)
        self.assertAlmostEqual(state.stored_energy_mwh, 0.9)
        self.assertEqual(state.pending_flexible_tasks, ())

    def test_late_flexible_task_is_carried_and_completed_next_day(self) -> None:
        horizon = 27
        cpu_arrival = np.zeros(horizon)
        cpu_arrival[23] = 0.90
        nonflex_cpu = (1.0 - self.params.flex_ratio) * 0.90
        params = replace(
            self.params,
            grid_capacity_mw=self.params.dc_power_mw(nonflex_cpu),
        )
        common = {
            "solar_available_mw": np.zeros(horizon),
            "wind_available_mw": np.zeros(horizon),
            "electricity_price_cny_per_kwh": np.full(horizon, 0.4489),
            "params": params,
            "enable_shift": True,
            "enable_storage": False,
            "enable_renewables": False,
            "output_dir": self.output_dir,
            "show_log": False,
            "flex_arrival_hours": 24,
            "commit_hours": 24,
            "return_state": True,
        }

        first_result, _, first_state = build_and_solve(
            cpu_arrival=cpu_arrival,
            case_name="cross_day_carry_out",
            **common,
        )

        self.assertAlmostEqual(first_result.loc[23, "cpu_scheduled_pu"], nonflex_cpu)
        self.assertEqual(len(first_state.pending_flexible_tasks), 1)
        carried = first_state.pending_flexible_tasks[0]
        self.assertEqual(carried.origin_hour, 23)
        self.assertAlmostEqual(carried.remaining_cpu_pu, 0.27)

        second_result, _, second_state = build_and_solve(
            cpu_arrival=np.zeros(horizon),
            case_name="cross_day_carry_in",
            carry_in_tasks=(
                PendingFlexibleTask(
                    origin_hour=-1,
                    remaining_cpu_pu=carried.remaining_cpu_pu,
                ),
            ),
            **common,
        )

        self.assertAlmostEqual(second_result.loc[0, "cpu_scheduled_pu"], 0.27)
        self.assertAlmostEqual(second_result["cpu_scheduled_pu"].sum(), 0.27)
        self.assertEqual(second_state.pending_flexible_tasks, ())

    def test_disabled_storage_zero_capacity_preserves_finite_soc(self) -> None:
        params = replace(self.params, battery_energy_mwh=0.0)

        result, metrics = self.solve(
            params=params,
            enable_storage=False,
            case_name="disabled_zero_storage_energy_capacity",
        )

        self.assertTrue(
            np.isfinite(result[["soc_start", "soc_end"]]).all().all()
        )
        np.testing.assert_allclose(
            result[["soc_start", "soc_end"]],
            params.battery_soc_initial,
            rtol=0.0,
            atol=0.0,
        )
        self.assertTrue(np.isfinite(metrics["soc_cycle_error"]))
        self.assertEqual(metrics["soc_cycle_error"], 0.0)

    def test_shift_respects_three_hour_deadline_and_conserves_cpu(self) -> None:
        cpu_arrival = np.zeros(6)
        cpu_arrival[0] = 0.5
        prices = np.array([1.0, 1.0, 1.0, 0.5, 0.01, 0.01])
        zeros = np.zeros(6)
        params = replace(self.params, flex_ratio=1.0)

        result, metrics = self.solve(
            cpu_arrival=cpu_arrival,
            solar_available_mw=zeros,
            wind_available_mw=zeros,
            electricity_price_cny_per_kwh=prices,
            params=params,
            enable_shift=True,
            enable_renewables=False,
            case_name="three_hour_shift_deadline",
        )

        self.assertAlmostEqual(result.loc[4, "cpu_scheduled_pu"], 0.0)
        self.assertAlmostEqual(result.loc[5, "cpu_scheduled_pu"], 0.0)
        self.assertAlmostEqual(result["cpu_scheduled_pu"].sum(), 0.5)
        self.assertAlmostEqual(metrics["cpu_conservation_error"], 0.0)

    def test_peak_valley_storage_obeys_physical_limits_and_recomputes_om(
        self,
    ) -> None:
        prices = np.array([0.1804] * 8 + [0.7174] * 16)
        zeros = np.zeros(24)
        result, metrics = self.solve(
            cpu_arrival=np.full(24, 0.50),
            solar_available_mw=zeros,
            wind_available_mw=zeros,
            electricity_price_cny_per_kwh=prices,
            enable_storage=True,
            enable_renewables=False,
            case_name="peak_valley_storage",
        )

        self.assertGreater(float(result["charge_mw"].sum()), 1e-8)
        self.assertGreater(float(result["discharge_mw"].sum()), 1e-8)
        self.assertLessEqual(
            float(result["charge_mw"].max()),
            self.params.battery_charge_power_mw + 1e-8,
        )
        self.assertLessEqual(
            float(result["discharge_mw"].max()),
            self.params.battery_discharge_power_mw + 1e-8,
        )
        self.assertGreaterEqual(float(result["soc_start"].min()), 0.10 - 1e-8)
        self.assertLessEqual(float(result["soc_end"].max()), 0.90 + 1e-8)
        self.assertAlmostEqual(float(result.loc[0, "soc_start"]), 0.50)
        self.assertAlmostEqual(float(result.loc[23, "soc_end"]), 0.50)
        expected_soc_end = result["soc_start"] + (
            self.params.charge_efficiency * result["charge_mw"]
            - result["discharge_mw"] / self.params.discharge_efficiency
        ) * self.params.time_step_h / self.params.battery_energy_mwh
        np.testing.assert_allclose(
            result["soc_end"], expected_soc_end, rtol=0.0, atol=1e-8
        )
        np.testing.assert_allclose(
            result["soc_start"].iloc[1:].to_numpy(),
            result["soc_end"].iloc[:-1].to_numpy(),
            rtol=0.0,
            atol=1e-8,
        )
        for activity_column in ("charge_active", "discharge_active"):
            activity = result[activity_column]
            self.assertTrue(
                ((activity >= -1e-9) & (activity <= 1.0 + 1e-9)).all()
            )
            np.testing.assert_allclose(
                activity,
                np.round(activity),
                rtol=0.0,
                atol=1e-9,
            )
        self.assertTrue(
            (
                result["charge_mw"]
                <= self.params.battery_charge_power_mw
                * result["charge_active"]
                + 1e-9
            ).all()
        )
        self.assertTrue(
            (
                result["discharge_mw"]
                <= self.params.battery_discharge_power_mw
                * result["discharge_active"]
                + 1e-9
            ).all()
        )
        self.assertTrue(
            (
                result["charge_active"] + result["discharge_active"]
                <= 1.0 + 1e-8
            ).all()
        )
        for stage in ("primary", "secondary"):
            lp_text = (
                self.output_dir / f"peak_valley_storage_{stage}.lp"
            ).read_text(encoding="utf-8")
            self.assertNotIn("storage_active_period_limit", lp_text)
        expected_hourly_om = (
            self.params.battery_om_cost_cny_per_kwh
            * (result["charge_mw"] + result["discharge_mw"])
            * self.params.time_step_h
            * 1000.0
        )
        np.testing.assert_allclose(
            result["hourly_battery_om_cost_cny"],
            expected_hourly_om,
            rtol=0.0,
            atol=1e-9,
        )
        self.assertAlmostEqual(
            metrics["battery_om_cost_cny"], float(expected_hourly_om.sum())
        )

    def test_flat_price_storage_can_remain_idle(self) -> None:
        zeros = np.zeros(24)
        result, metrics = self.solve(
            cpu_arrival=np.full(24, 0.50),
            solar_available_mw=zeros,
            wind_available_mw=zeros,
            electricity_price_cny_per_kwh=np.full(24, 0.4489),
            enable_storage=True,
            enable_renewables=False,
            case_name="flat_price_storage",
        )

        np.testing.assert_allclose(result["charge_mw"], 0.0, atol=1e-8)
        np.testing.assert_allclose(result["discharge_mw"], 0.0, atol=1e-8)
        self.assertEqual(metrics["battery_active_periods"], 0)

    def test_lexicographic_solves_cost_then_flexible_task_delay(self) -> None:
        cpu_arrival = np.zeros(24)
        cpu_arrival[0] = 0.50
        zeros = np.zeros(24)
        prices = np.full(24, 0.448900)
        prices[1] = 0.448894
        result, metrics = self.solve(
            cpu_arrival=cpu_arrival,
            solar_available_mw=zeros,
            wind_available_mw=zeros,
            electricity_price_cny_per_kwh=prices,
            params=replace(self.params, flex_ratio=1.0),
            enable_shift=True,
            enable_renewables=False,
            case_name="lexicographic_delay",
        )

        self.assertTrue(
            (self.output_dir / "lexicographic_delay_primary.lp").is_file()
        )
        self.assertTrue(
            (self.output_dir / "lexicographic_delay_secondary.lp").is_file()
        )
        self.assertEqual(metrics["primary_solve_status"], "optimal")
        self.assertEqual(metrics["secondary_solve_status"], "optimal")
        self.assertLessEqual(
            metrics["operating_cost_cny"],
            metrics["primary_operating_cost_cny"] + 0.010001,
        )
        self.assertGreater(
            metrics["primary_total_task_delay_cpu_hours"],
            metrics["total_task_delay_cpu_hours"],
        )
        self.assertAlmostEqual(
            metrics["total_task_delay_cpu_hours"], 0.0, places=8
        )
        self.assertAlmostEqual(float(result.loc[0, "cpu_scheduled_pu"]), 0.50)

    def test_storage_never_costs_more_than_no_storage_beyond_tolerance(
        self,
    ) -> None:
        no_storage_result, no_storage_metrics = self.solve(
            case_name="renewables_no_storage"
        )
        storage_result, storage_metrics = self.solve(
            enable_storage=True,
            case_name="renewables_with_storage",
        )

        self.assertEqual(len(storage_result), len(no_storage_result))
        self.assertLessEqual(
            storage_metrics["operating_cost_cny"],
            no_storage_metrics["operating_cost_cny"] + 0.010001,
        )

    def test_storage_power_balance_and_cycle_metrics_match_hourly_results(
        self,
    ) -> None:
        prices = np.array([0.1804] * 8 + [0.7174] * 16)
        result, metrics = self.solve(
            electricity_price_cny_per_kwh=prices,
            enable_storage=True,
            case_name="storage_power_balance",
        )

        np.testing.assert_allclose(
            result["grid_power_mw"]
            + result["solar_used_mw"]
            + result["wind_used_mw"]
            + result["discharge_mw"],
            result["dc_power_mw"] + result["charge_mw"],
            rtol=0.0,
            atol=1e-8,
        )
        self.assertAlmostEqual(
            metrics["soc_cycle_error"],
            abs(float(result.loc[23, "soc_end"] - result.loc[0, "soc_start"])),
        )
        self.assertAlmostEqual(
            metrics["max_simultaneous_charge_discharge_mw2"],
            float((result["charge_mw"] * result["discharge_mw"]).max()),
        )
        self.assertAlmostEqual(metrics["soc_cycle_error"], 0.0, places=8)
        self.assertAlmostEqual(
            metrics["max_simultaneous_charge_discharge_mw2"], 0.0, places=8
        )


if __name__ == "__main__":
    unittest.main()
