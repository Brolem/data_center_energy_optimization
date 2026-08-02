from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import dc_energy_opt.reporting.plots as plots
from dc_energy_opt.reporting.plots import PLOT_FILENAMES, make_plots


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


class PlotTests(unittest.TestCase):
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
