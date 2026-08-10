from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PIL import Image, ImageColor, ImageDraw

import dc_energy_opt.reporting.plots as plots
from dc_energy_opt.reporting.plots import (
    PLOT_FILENAMES,
    make_daily_plots,
    make_plots,
)


CASE_ORDER = [
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
]
PLOT_SIZES = {
    "power_dispatch.png": (1800, 1120),
    "compute_schedule.png": (1800, 820),
    "battery_dispatch.png": (1800, 1120),
    "renewable_dispatch.png": (1800, 820),
    "cost_breakdown.png": (1800, 1050),
}


def _zero_plot_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly_rows = []
    for case_name in CASE_ORDER:
        for hour in range(27):
            hourly_rows.append(
                {
                    "case": case_name,
                    "hour": hour,
                    "period_role": (
                        "analysis" if hour < 24 else "settlement_tail"
                    ),
                    "cpu_arrival_pu": 0.0,
                    "cpu_scheduled_pu": 0.0,
                    "it_power_mw": 0.0,
                    "dc_power_mw": 0.0,
                    "grid_power_mw": 0.0,
                    "solar_available_mw": 0.0,
                    "solar_used_mw": 0.0,
                    "solar_curtailed_mw": 0.0,
                    "wind_available_mw": 0.0,
                    "wind_used_mw": 0.0,
                    "wind_curtailed_mw": 0.0,
                    "charge_mw": 0.0,
                    "discharge_mw": 0.0,
                    "soc_start": 0.5,
                    "soc_end": 0.5,
                    "electricity_price_cny_per_kwh": 0.0,
                    "hourly_grid_purchase_cost_cny": 0.0,
                    "hourly_solar_om_cost_cny": 0.0,
                    "hourly_wind_om_cost_cny": 0.0,
                    "hourly_battery_om_cost_cny": 0.0,
                    "hourly_battery_degradation_cost_cny": 0.0,
                    "hourly_operating_cost_cny": 0.0,
                }
            )
    metrics = pd.DataFrame(
        {
            "case": CASE_ORDER,
            "grid_purchase_cost_cny": 0.0,
            "solar_om_cost_cny": 0.0,
            "wind_om_cost_cny": 0.0,
            "battery_om_cost_cny": 0.0,
            "battery_degradation_cost_cny": 0.0,
            "operating_cost_cny": 0.0,
        }
    )
    return pd.DataFrame(hourly_rows), metrics


def _daily_plot_inputs(day_number: int) -> pd.DataFrame:
    hourly_results, _ = _zero_plot_inputs()
    if day_number != 28:
        hourly_results = hourly_results.loc[
            hourly_results["hour"] < 24
        ].copy()
    hourly_results["day"] = day_number
    hourly_results["hour"] += (day_number - 1) * 24
    return hourly_results


class PlotTests(unittest.TestCase):
    def test_battery_power_uses_hour_interval_centers(self) -> None:
        data = pd.DataFrame(
            {
                "hour": [0, 1, 2],
                "charge_mw": [0.5, 0.0, 0.0],
                "discharge_mw": [0.0, 0.0, 0.5],
            }
        )

        hours, charge, discharge = plots._battery_power_series(data)

        np.testing.assert_array_equal(hours, np.array([0.5, 1.5, 2.5]))
        np.testing.assert_array_equal(charge, np.array([0.5, 0.0, 0.0]))
        np.testing.assert_array_equal(discharge, np.array([0.0, 0.0, -0.5]))

    def test_soc_uses_one_continuous_hour_boundary_series(self) -> None:
        data = pd.DataFrame(
            {
                "hour": [0, 1, 2],
                "soc_start": [0.10, 0.3375, 0.3375],
                "soc_end": [0.3375, 0.3375, 0.10],
            }
        )

        hours, soc = plots._soc_boundary_series(data)

        np.testing.assert_array_equal(hours, np.array([0.0, 1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(soc, np.array([0.10, 0.3375, 0.3375, 0.10]))

    def test_make_daily_plots_writes_five_images_for_day_01_and_28(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "figures"
            for day_number, expected_hours in ((1, 24), (28, 27)):
                with self.subTest(day_number=day_number):
                    hourly_results = _daily_plot_inputs(day_number)
                    daily_output = make_daily_plots(
                        hourly_results,
                        day_number,
                        output_root,
                    )

                    self.assertEqual(
                        daily_output,
                        output_root / f"day_{day_number:02d}",
                    )
                    self.assertEqual(
                        sorted(path.name for path in daily_output.glob("*.png")),
                        sorted(PLOT_FILENAMES),
                    )
                    self.assertEqual(
                        hourly_results.groupby("case").size().unique().tolist(),
                        [expected_hours],
                    )

    def test_task_delay_objective_plot_writes_full_and_compact_daily_images(
        self,
    ) -> None:
        daily_metrics = pd.DataFrame(
            {
                "case": [
                    "renewables_shift",
                    "renewables_shift",
                    "joint",
                    "joint",
                ],
                "day": [1, 2, 1, 2],
                "primary_task_delay_cpu_hours": [5.0, 4.0, 6.0, 5.0],
                "secondary_task_delay_cpu_hours": [3.0, 2.0, 4.0, 3.0],
            }
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            full_path = root / "task_delay_objectives.png"
            day_path = root / "day_02" / "task_delay_objectives.png"

            plots.make_task_delay_objective_plot(daily_metrics, full_path)
            plots.make_task_delay_objective_plot(
                daily_metrics,
                day_path,
                day_number=2,
            )

            with Image.open(full_path) as image:
                self.assertEqual(image.size, (1800, 1050))
                self.assertEqual(image.mode, "RGB")
                image.verify()
            with Image.open(day_path) as image:
                self.assertEqual(image.size, (1800, 720))
                self.assertEqual(image.mode, "RGB")
                image.verify()

    def test_daily_case_cost_plots_write_four_images_with_real_dates(
        self,
    ) -> None:
        daily_metrics = pd.DataFrame(
            {
                "case": [
                    case_name
                    for case_name in CASE_ORDER
                    for _ in range(2)
                ],
                "day": [1, 2] * len(CASE_ORDER),
                "operating_cost_cny": [
                    100.0,
                    120.0,
                    90.0,
                    110.0,
                    95.0,
                    115.0,
                    85.0,
                    105.0,
                ],
                "settlement_tail_operating_cost_cny": [0.0, 5.0] * 4,
            }
        )
        hourly_dispatch = pd.DataFrame(
            {
                "case": [
                    case_name
                    for case_name in CASE_ORDER
                    for _ in range(2)
                ],
                "day": [1, 2] * len(CASE_ORDER),
                "timestamp_lst": [
                    "2020-05-01 00:00:00",
                    "2020-05-02 00:00:00",
                ]
                * len(CASE_ORDER),
                "period_role": ["analysis", "analysis"] * len(CASE_ORDER),
            }
        )
        expected_names = [
            f"daily_cost_{case_name}.png" for case_name in CASE_ORDER
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "figures"
            output_paths = plots.make_daily_case_cost_plots(
                daily_metrics,
                hourly_dispatch,
                output_dir,
            )

            self.assertEqual(
                [path.name for path in output_paths],
                expected_names,
            )
            self.assertEqual(
                sorted(path.name for path in output_dir.glob("*.png")),
                sorted(expected_names),
            )
            for output_path in output_paths:
                with Image.open(output_path) as image:
                    self.assertEqual(image.size, (1800, 900))
                    self.assertEqual(image.mode, "RGB")
                    image.verify()

    def test_daily_case_cost_plots_render_daily_costs_as_bars(self) -> None:
        daily_metrics = pd.DataFrame(
            {
                "case": [
                    case_name
                    for case_name in CASE_ORDER
                    for _ in range(3)
                ],
                "day": [1, 2, 3] * len(CASE_ORDER),
                "operating_cost_cny": [
                    100.0,
                    200.0,
                    300.0,
                    110.0,
                    210.0,
                    310.0,
                    120.0,
                    220.0,
                    320.0,
                    130.0,
                    230.0,
                    330.0,
                ],
                "settlement_tail_operating_cost_cny": 0.0,
            }
        )
        hourly_dispatch = pd.DataFrame(
            {
                "case": [
                    case_name
                    for case_name in CASE_ORDER
                    for _ in range(3)
                ],
                "day": [1, 2, 3] * len(CASE_ORDER),
                "timestamp_lst": [
                    "2020-05-01 00:00:00",
                    "2020-05-02 00:00:00",
                    "2020-05-03 00:00:00",
                ]
                * len(CASE_ORDER),
                "period_role": ["analysis", "analysis", "analysis"]
                * len(CASE_ORDER),
            }
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "figures"
            output_path = plots.make_daily_case_cost_plots(
                daily_metrics,
                hourly_dispatch,
                output_dir,
            )[0]

            with Image.open(output_path) as image:
                self.assertEqual(
                    image.getpixel((974, 540)),
                    ImageColor.getrgb(
                        plots.CASE_COLORS["renewables_only"]
                    ),
                )
                self.assertEqual(image.getpixel((160, 720)), (255, 255, 255))

    def test_flex_ratio_sensitivity_plots_write_three_images(self) -> None:
        sensitivity_metrics = pd.DataFrame(
            {
                "scenario": [
                    "renewables_shift",
                    "renewables_shift",
                    "renewables_shift",
                    "joint",
                    "joint",
                    "joint",
                ],
                "baseline_case": [
                    "renewables_only",
                    "renewables_only",
                    "renewables_only",
                    "renewables_storage",
                    "renewables_storage",
                    "renewables_storage",
                ],
                "flex_ratio": [0.0, 0.5, 1.0, 0.0, 0.5, 1.0],
                "status": ["optimal"] * 6,
                "analysis_operating_cost_cny": [90.0, 85.0, 80.0, 72.0, 68.0, 64.0],
                "settlement_tail_operating_cost_cny": [10.0, 9.0, 8.0, 8.0, 7.0, 6.0],
                "operating_cost_cny": [100.0, 94.0, 88.0, 80.0, 75.0, 70.0],
                "baseline_operating_cost_cny": [100.0] * 3 + [80.0] * 3,
                "cost_savings_cny": [0.0, 6.0, 12.0, 0.0, 5.0, 10.0],
                "cost_savings_pct": [0.0, 6.0, 12.0, 0.0, 6.25, 12.5],
                "marginal_cost_savings_cny_per_flex_ratio": [
                    np.nan,
                    60.0,
                    60.0,
                    np.nan,
                    50.0,
                    50.0,
                ],
                "total_task_delay_cpu_hours": [0.0, 3.0, 6.0, 0.0, 2.0, 4.0],
                "average_flexible_task_delay_h": [0.0, 1.0, 1.5, 0.0, 0.8, 1.2],
                "maximum_task_delay_h": [0, 3, 3, 0, 2, 3],
                "saturation_onset": [np.nan] * 6,
            }
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "figures"
            output_paths = plots.make_flex_ratio_sensitivity_plots(
                sensitivity_metrics,
                output_dir,
            )

            self.assertEqual(
                [path.name for path in output_paths],
                [
                    "flex_ratio_total_cost.png",
                    "flex_ratio_cost_savings.png",
                    "flex_ratio_marginal_savings.png",
                ],
            )
            for output_path in output_paths:
                with Image.open(output_path) as image:
                    self.assertEqual(image.size, (1800, 900))
                    self.assertEqual(image.mode, "RGB")
                    image.verify()

            with Image.open(output_paths[2]) as marginal_image:
                self.assertEqual(
                    marginal_image.getpixel((1780, 500)),
                    ImageColor.getrgb(plots.PANEL),
                )

            accepted_gaplimit_metrics = sensitivity_metrics.copy()
            accepted_gaplimit_metrics["status"] = "gaplimit"
            with tempfile.TemporaryDirectory() as gaplimit_directory:
                gaplimit_paths = plots.make_flex_ratio_sensitivity_plots(
                    accepted_gaplimit_metrics,
                    Path(gaplimit_directory),
                )
                self.assertEqual(len(gaplimit_paths), 3)

    def test_settlement_tail_uses_gray_shading_without_purple_line(
        self,
    ) -> None:
        data = pd.DataFrame(
            {
                "hour": np.arange(27, dtype=int),
                "period_role": ["analysis"] * 24
                + ["settlement_tail"] * 3,
            }
        )
        image = Image.new("RGB", (140, 110), "#FFFFFF")
        draw = ImageDraw.Draw(image)

        plots._mark_settlement_tail(
            draw,
            data,
            (10, 10, 130, 100),
            0.0,
            26.0,
        )

        pixels = list(image.get_flattened_data())
        self.assertIn(ImageColor.getrgb("#E2E8F0"), pixels)
        self.assertNotIn(ImageColor.getrgb("#7C3AED"), pixels)

    def test_plot_filenames_are_the_formal_five_outputs(self) -> None:
        self.assertEqual(
            PLOT_FILENAMES,
            [
                "power_dispatch.png",
                "compute_schedule.png",
                "battery_dispatch.png",
                "renewable_dispatch.png",
                "cost_breakdown.png",
            ],
        )
        self.assertFalse(hasattr(plots, "LEGACY_PLOT_FILENAMES"))

    def test_make_plots_handles_complete_all_zero_inputs(self) -> None:
        hourly_results, metrics = _zero_plot_inputs()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "plots"

            make_plots(hourly_results, metrics, output_dir)

            self.assertEqual(
                sorted(path.name for path in output_dir.glob("*.png")),
                sorted(PLOT_FILENAMES),
            )
            for filename in PLOT_FILENAMES:
                with Image.open(output_dir / filename) as image:
                    self.assertEqual(image.size, PLOT_SIZES[filename])
                    self.assertEqual(image.mode, "RGB")
                    image.verify()

    def test_make_plots_rejects_empty_inputs_before_writing_png(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "plots"

            with self.assertRaises(ValueError):
                make_plots(pd.DataFrame(), pd.DataFrame(), output_dir)

            self.assertFalse(output_dir.exists())

    def test_make_plots_validates_cases_hours_and_numeric_columns(
        self,
    ) -> None:
        hourly_results, metrics = _zero_plot_inputs()
        duplicate_hour = hourly_results.copy()
        duplicate_hour.loc[
            (duplicate_hour["case"] == "joint")
            & (duplicate_hour["hour"] == 23),
            "hour",
        ] = 22
        nonfinite = hourly_results.copy()
        nonfinite.loc[0, "dc_power_mw"] = np.nan
        malformed_inputs = [
            (
                "hourly_results case",
                hourly_results[hourly_results["case"] != "joint"],
                metrics,
            ),
            ("hour", duplicate_hour, metrics),
            (
                "metrics case",
                hourly_results,
                pd.concat([metrics, metrics.iloc[[0]]], ignore_index=True),
            ),
            (
                "dc_power_mw",
                hourly_results.drop(columns="dc_power_mw"),
                metrics,
            ),
            ("dc_power_mw", nonfinite, metrics),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for index, (
                message_fragment,
                invalid_hourly,
                invalid_metrics,
            ) in enumerate(malformed_inputs):
                output_dir = root / str(index)
                with self.subTest(message_fragment=message_fragment):
                    with self.assertRaisesRegex(
                        ValueError, message_fragment
                    ):
                        make_plots(
                            invalid_hourly,
                            invalid_metrics,
                            output_dir,
                        )
                    self.assertFalse(output_dir.exists())

    def test_make_plots_rejects_invalid_physical_semantics_before_writing(
        self,
    ) -> None:
        hourly_results, metrics = _zero_plot_inputs()
        invalid_inputs = []
        for column, value in (
            ("dc_power_mw", -1e-6),
            ("hourly_operating_cost_cny", -1e-6),
        ):
            invalid = hourly_results.copy()
            invalid.loc[0, column] = value
            invalid_inputs.append((column, invalid, metrics))

        invalid_metric_cost = metrics.copy()
        invalid_metric_cost.loc[0, "operating_cost_cny"] = -1e-6
        invalid_inputs.append(
            ("operating_cost_cny", hourly_results, invalid_metric_cost)
        )

        invalid_soc = hourly_results.copy()
        invalid_soc.loc[0, "soc_end"] = 0.900001
        invalid_inputs.append(("soc_end", invalid_soc, metrics))

        fractional_hour = hourly_results.copy()
        fractional_hour["hour"] = fractional_hour["hour"].astype(float)
        fractional_hour.loc[0, "hour"] = 0.5
        invalid_inputs.append(("integer", fractional_hour, metrics))

        inconsistent_arrival = hourly_results.copy()
        inconsistent_arrival.loc[
            (inconsistent_arrival["case"] == "joint")
            & (inconsistent_arrival["hour"] == 0),
            "cpu_arrival_pu",
        ] = 0.01
        invalid_inputs.append(
            ("joint.*cpu_arrival_pu", inconsistent_arrival, metrics)
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for index, (
                message_pattern,
                invalid_hourly,
                invalid_metrics,
            ) in enumerate(invalid_inputs):
                output_dir = root / str(index)
                with self.subTest(message_pattern=message_pattern):
                    with self.assertRaisesRegex(ValueError, message_pattern):
                        make_plots(
                            invalid_hourly,
                            invalid_metrics,
                            output_dir,
                        )
                    self.assertFalse(output_dir.exists())

    def test_normalized_nonnegative_cost_obeys_exact_tolerance(self) -> None:
        for value in (-1e-10, -5e-11, -1e-20, -0.0):
            with self.subTest(value=value):
                self.assertEqual(
                    plots._normalized_nonnegative_cost(value),
                    0.0,
                )

        self.assertEqual(plots._normalized_nonnegative_cost(12.5), 12.5)
        with self.assertRaises(ValueError):
            plots._normalized_nonnegative_cost(-1.000001e-10)

    def test_boundary_negative_costs_render_as_zero_without_negative_zero(
        self,
    ) -> None:
        hourly_results, metrics = _zero_plot_inputs()
        component_columns = [
            "grid_purchase_cost_cny",
            "solar_om_cost_cny",
            "wind_om_cost_cny",
            "battery_om_cost_cny",
            "battery_degradation_cost_cny",
        ]
        metrics.loc[:, component_columns] = -1e-10
        metrics.loc[:, "operating_cost_cny"] = 0.0
        drawn_text: list[str] = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(
            image_draw: ImageDraw.ImageDraw,
            xy: tuple[float, float] | tuple[int, int],
            text: str,
            *args: object,
            **kwargs: object,
        ) -> None:
            drawn_text.append(str(text))
            original_text(image_draw, xy, text, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "plots"
            with patch.object(
                ImageDraw.ImageDraw,
                "text",
                new=record_text,
            ):
                make_plots(hourly_results, metrics, output_dir)

            self.assertEqual(drawn_text.count("CNY 0"), len(CASE_ORDER))
            self.assertNotIn("CNY -0", drawn_text)
            for filename in PLOT_FILENAMES:
                with Image.open(output_dir / filename) as image:
                    image.verify()


if __name__ == "__main__":
    unittest.main()
