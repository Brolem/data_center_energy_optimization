# Deterministic Day-Ahead Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 Google 2019 SCIP 模型改造成已确认的 24 小时确定性日前优化模型，使用菲尼克斯临时风光形状与青海分时电价，按人民币最小化电网购电、光伏运维、风电运维和储能运维四项成本，并用第二次求解最小化任务总延迟。

**Architecture:** 数据层从 672 小时原始气象逐时计算风光功率，再构造 24 小时临时场景；配置层统一服务器、风光、储能和电网尺度；模型层构建一个 SCIP 模型，先求一级运行成本，再增加成本容差约束并求二级任务延迟；入口层运行五组算例，报告层输出 CNY 成本、物理量、求解状态、LP 文件和图表。

**Tech Stack:** Python 3.13、NumPy、pandas、PySCIPOpt/SCIP、Pillow、`unittest`、Conda 环境 `scip_env`

---

## File Structure

本次实施涉及以下文件：

- `scip_first_version/config.py`：保存统一尺度参数及只读派生属性。
- `scip_first_version/data.py`：验证 672 小时气象源、逐时计算风光功率、构造并加载 24 小时临时场景。
- `scip_first_version/model.py`：建立五类算例共用的确定性日前 MILP，并执行一级、二级顺序求解。
- `scip_first_version/reporting.py`：绘制五类算例的功率、算力、储能、新能源和四项成本图。
- `scip_first_version/__init__.py`：导出稳定公共接口。
- `run_first_version.py`：设置默认输入输出、执行五类算例、写入 CSV/JSON/LP/图片。
- `data/provisional_phoenix_weather_qinghai_tou_scenario.csv`：由 672 小时气象源确定性生成的 24 小时临时场景。
- `tests/test_cost_optimization.py`：数据、参数、物理约束、成本和两层目标测试。
- `tests/test_runner_outputs.py`：默认入口与交付文件测试。
- `tests/test_refactor_regression.py`：代表日、压力日和五组算例回归测试。
- `FIRST_VERSION_GUIDE.md`：记录模型范围、公式、数据边界、运行方法和结果解释原则。

实施期间保留并不暂存：

- `data/phoenix_typical_may_workday_energy_scenario.csv`
- `tmp/`

除非用户另行明确要求，不删除上述旧场景和临时目录。

## Task 1: Lock the Unified Parameter Scale

**Files:**

- Modify: `tests/test_cost_optimization.py`
- Modify: `scip_first_version/config.py`

- [ ] **Step 1: Replace the old parameter assertions with the approved scale**

在 `EnergyScenarioInterfaceTests` 前新增 `ParameterScaleTests`，使用以下精确测试：

```python
class ParameterScaleTests(unittest.TestCase):
    def test_parameters_match_the_approved_day_ahead_scale(self) -> None:
        params = Parameters()

        self.assertEqual(params.flex_ratio, 0.30)
        self.assertEqual(params.max_delay_h, 3)
        self.assertEqual(params.cpu_capacity_pu, 0.90)
        self.assertEqual(params.server_count, 12_500)
        self.assertEqual(params.server_max_power_kw, 0.55)
        self.assertEqual(params.server_idle_power_ratio, 0.60)
        self.assertEqual(params.server_idle_power_kw, 0.33)
        self.assertEqual(params.pue, 1.10)
        self.assertAlmostEqual(params.it_power_mw(0.0), 4.125)
        self.assertAlmostEqual(params.it_power_mw(0.90), 6.60)
        self.assertAlmostEqual(params.dc_power_mw(0.90), 7.26)
        self.assertEqual(params.grid_capacity_mw, 7.66)

        self.assertEqual(params.solar_panel_area_m2, 20_000.0)
        self.assertEqual(params.solar_base_efficiency, 0.15)
        self.assertEqual(params.solar_capacity_mw, 3.0)
        self.assertEqual(params.wind_turbine_count, 33)
        self.assertEqual(params.wind_turbine_rated_power_kw, 200.0)
        self.assertEqual(params.wind_capacity_mw, 6.6)

        self.assertEqual(params.battery_energy_mwh, 1.0)
        self.assertEqual(params.battery_charge_power_mw, 0.4)
        self.assertEqual(params.battery_discharge_power_mw, 0.25)
        self.assertEqual(params.charge_efficiency, 0.95)
        self.assertEqual(params.discharge_efficiency, 0.90)
        self.assertEqual(params.battery_soc_min, 0.10)
        self.assertEqual(params.battery_soc_max, 0.90)
        self.assertEqual(params.battery_soc_initial, 0.50)
        self.assertEqual(params.battery_max_active_periods, 16)

        self.assertEqual(params.solar_om_cost_cny_per_kw, 0.016)
        self.assertEqual(params.wind_om_cost_cny_per_kw, 0.018)
        self.assertEqual(params.battery_om_cost_cny_per_kw, 0.18)
        self.assertEqual(params.primary_cost_tolerance_cny, 0.01)
        self.assertEqual(params.relative_gap, 1e-6)
```

- [ ] **Step 2: Run the new test and confirm that the old configuration fails**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_cost_optimization.ParameterScaleTests -v
```

Expected: `FAILED`; the first failure reports a missing approved field or an old value such as `cpu_capacity_pu=0.65`.

- [ ] **Step 3: Replace `Parameters` with the approved parameter contract**

将 `scip_first_version/config.py` 的 `Parameters` 精确改为：

```python
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
    battery_soc_min: float = 0.10
    battery_soc_max: float = 0.90
    battery_soc_initial: float = 0.50
    battery_charge_power_mw: float = 0.40
    battery_discharge_power_mw: float = 0.25
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.90
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
        return (
            self.solar_panel_area_m2
            * self.solar_base_efficiency
            * 1000.0
            / 1_000_000.0
        )

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
```

- [ ] **Step 4: Run the parameter tests**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_cost_optimization.ParameterScaleTests -v
```

Expected: `OK`.

- [ ] **Step 5: Commit only the parameter contract and its test**

```powershell
git add -- scip_first_version/config.py tests/test_cost_optimization.py
git diff --cached --check
git commit -m "统一确定性日前模型参数尺度"
```

## Task 2: Build and Validate the Provisional Energy Scenario

**Files:**

- Modify: `tests/test_cost_optimization.py`
- Modify: `scip_first_version/data.py`
- Create: `data/provisional_phoenix_weather_qinghai_tou_scenario.csv`
- Modify: `scip_first_version/__init__.py`

- [ ] **Step 1: Define the exact scenario interface in tests**

在 `tests/test_cost_optimization.py` 中把场景路径改为：

```python
cls.nasa_source_path = Path(
    "data/phoenix_nasa_power_20190501_20190528_hourly.csv"
)
cls.bundled_scenario_path = Path(
    "data/provisional_phoenix_weather_qinghai_tou_scenario.csv"
)
```

把预期列固定为：

```python
EXPECTED_SCENARIO_COLUMNS = [
    "hour",
    "solar_irradiance_wh_m2",
    "wind_speed_50m_m_s",
    "solar_available_mw",
    "wind_available_mw",
    "tou_period",
    "electricity_price_cny_per_kwh",
]
```

新增或替换为以下测试：

```python
def test_build_scenario_applies_power_models_before_hourly_average(
    self,
) -> None:
    params = Parameters()
    source = data_module.load_phoenix_weather_source(
        self.nasa_source_path
    )
    built = data_module.build_provisional_energy_scenario(
        self.nasa_source_path,
        params,
    )

    row_solar = data_module.solar_available_power_mw(
        source["solar_irradiance_wh_m2"].to_numpy(dtype=float),
        params,
    )
    row_wind = data_module.wind_available_power_mw(
        source["wind_speed_50m_m_s"].to_numpy(dtype=float),
        params,
    )
    hours = pd.to_datetime(source["timestamp_lst"]).dt.hour
    expected_solar = pd.Series(row_solar).groupby(hours).mean()
    expected_wind = pd.Series(row_wind).groupby(hours).mean()

    self.assertEqual(list(built.columns), EXPECTED_SCENARIO_COLUMNS)
    self.assertEqual(built["hour"].tolist(), list(range(24)))
    np.testing.assert_allclose(
        built["solar_available_mw"],
        expected_solar.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-10,
    )
    np.testing.assert_allclose(
        built["wind_available_mw"],
        expected_wind.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-10,
    )


def test_qinghai_tariff_uses_exact_periods_and_cny_values(self) -> None:
    scenario = data_module.build_provisional_energy_scenario(
        self.nasa_source_path,
        Parameters(),
    )
    expected_periods = (
        ["valley"] * 8
        + ["flat"]
        + ["peak"] * 4
        + ["flat"] * 5
        + ["peak"] * 5
        + ["flat"]
    )
    expected_prices = (
        [0.1804] * 8
        + [0.4489]
        + [0.7174] * 4
        + [0.4489] * 5
        + [0.7174] * 5
        + [0.4489]
    )

    self.assertEqual(scenario["tou_period"].tolist(), expected_periods)
    self.assertEqual(
        scenario["electricity_price_cny_per_kwh"].tolist(),
        expected_prices,
    )
    self.assertNotIn(
        "electricity_price_usd_per_kwh",
        scenario.columns,
    )
    self.assertLessEqual(
        float(scenario["solar_available_mw"].max()),
        3.0,
    )
    self.assertLessEqual(
        float(scenario["wind_available_mw"].max()),
        6.6,
    )


def test_bundled_scenario_exactly_matches_rebuilt_source(self) -> None:
    params = Parameters()
    expected = data_module.build_provisional_energy_scenario(
        self.nasa_source_path,
        params,
    )
    actual = data_module.load_energy_scenario(
        self.bundled_scenario_path,
        params,
        weather_source_path=self.nasa_source_path,
    )

    pd.testing.assert_frame_equal(actual, expected)
```

保留并加强 672 小时连续性、无重复和无缺失测试。新增一个损坏场景测试，确保加载器不是只看列名：

```python
def test_loader_rejects_power_that_differs_from_weather_source(self) -> None:
    params = Parameters()
    scenario = data_module.build_provisional_energy_scenario(
        self.nasa_source_path,
        params,
    )
    scenario.loc[12, "wind_available_mw"] += 0.01

    with tempfile.TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "scenario.csv"
        scenario.to_csv(path, index=False)
        with self.assertRaisesRegex(ValueError, "wind_available_mw"):
            data_module.load_energy_scenario(
                path,
                params,
                weather_source_path=self.nasa_source_path,
            )
```

- [ ] **Step 2: Run the scenario tests and confirm failure**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_cost_optimization.EnergyScenarioInterfaceTests -v
```

Expected: `FAILED`; missing source-loader/builder functions and CNY field are reported.

- [ ] **Step 3: Implement strict source validation and row-wise power conversion**

在 `scip_first_version/data.py` 中定义以下 constants and functions，保留现有 Google 轨迹的 `load_and_prepare`：

```python
PHOENIX_WEATHER_COLUMNS = [
    "timestamp_lst",
    "solar_irradiance_wh_m2",
    "wind_speed_50m_m_s",
]

ENERGY_SCENARIO_COLUMNS = [
    "hour",
    "solar_irradiance_wh_m2",
    "wind_speed_50m_m_s",
    "solar_available_mw",
    "wind_available_mw",
    "tou_period",
    "electricity_price_cny_per_kwh",
]


def load_phoenix_weather_source(csv_path: Path) -> pd.DataFrame:
    weather = pd.read_csv(csv_path)
    if list(weather.columns) != PHOENIX_WEATHER_COLUMNS:
        raise ValueError(
            f"气象源字段必须精确为 {PHOENIX_WEATHER_COLUMNS}"
        )
    if len(weather) != 28 * 24:
        raise ValueError("气象源必须包含连续 672 小时")
    if weather.isna().any().any():
        raise ValueError("气象源不得包含缺失值")

    timestamps = pd.to_datetime(
        weather["timestamp_lst"],
        errors="raise",
    )
    expected = pd.date_range(
        "2019-05-01 00:00:00",
        periods=28 * 24,
        freq="h",
    )
    if not timestamps.equals(pd.Series(expected)):
        raise ValueError("气象源时间戳必须按地方太阳时连续且有序")
    if timestamps.duplicated().any():
        raise ValueError("气象源时间戳不得重复")

    numeric = weather[
        ["solar_irradiance_wh_m2", "wind_speed_50m_m_s"]
    ].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("气象源数值必须为有限值")
    if (numeric.to_numpy(dtype=float) < 0.0).any():
        raise ValueError("太阳辐射和风速不得为负")
    weather = weather.copy()
    weather[
        ["solar_irradiance_wh_m2", "wind_speed_50m_m_s"]
    ] = numeric
    return weather


def solar_available_power_mw(
    irradiance_wh_m2: np.ndarray,
    params: Parameters,
) -> np.ndarray:
    raw_power = (
        params.solar_panel_area_m2
        * params.solar_base_efficiency
        * np.asarray(irradiance_wh_m2, dtype=float)
        / 1_000_000.0
    )
    return np.clip(raw_power, 0.0, params.solar_capacity_mw)


def _wind_capacity_factor(
    wind_speed_m_s: np.ndarray,
    params: Parameters,
) -> np.ndarray:
    speeds = np.asarray(wind_speed_m_s, dtype=float)
    factor = np.zeros_like(speeds)
    ramp = (
        (speeds >= params.wind_cut_in_speed_m_s)
        & (speeds < params.wind_rated_speed_m_s)
    )
    rated = (
        (speeds >= params.wind_rated_speed_m_s)
        & (speeds < params.wind_cut_out_speed_m_s)
    )
    factor[ramp] = (
        (
            speeds[ramp] ** 3
            - params.wind_cut_in_speed_m_s**3
        )
        / (
            params.wind_rated_speed_m_s**3
            - params.wind_cut_in_speed_m_s**3
        )
    )
    factor[rated] = 1.0
    return factor


def wind_available_power_mw(
    wind_speed_m_s: np.ndarray,
    params: Parameters,
) -> np.ndarray:
    return params.wind_capacity_mw * _wind_capacity_factor(
        wind_speed_m_s,
        params,
    )
```

- [ ] **Step 4: Implement the fixed Qinghai tariff and 24-hour builder**

继续在 `scip_first_version/data.py` 中加入：

```python
def _qinghai_tou_period_and_price(hour: int) -> tuple[str, float]:
    if 0 <= hour < 8:
        return "valley", 0.1804
    if 9 <= hour < 13 or 18 <= hour < 23:
        return "peak", 0.7174
    return "flat", 0.4489


def build_provisional_energy_scenario(
    source_csv_path: Path,
    params: Parameters,
) -> pd.DataFrame:
    weather = load_phoenix_weather_source(source_csv_path).copy()
    weather["hour"] = pd.to_datetime(
        weather["timestamp_lst"]
    ).dt.hour
    weather["solar_available_mw"] = solar_available_power_mw(
        weather["solar_irradiance_wh_m2"].to_numpy(dtype=float),
        params,
    )
    weather["wind_available_mw"] = wind_available_power_mw(
        weather["wind_speed_50m_m_s"].to_numpy(dtype=float),
        params,
    )

    scenario = (
        weather.groupby("hour", as_index=False)
        .agg(
            solar_irradiance_wh_m2=(
                "solar_irradiance_wh_m2",
                "mean",
            ),
            wind_speed_50m_m_s=("wind_speed_50m_m_s", "mean"),
            solar_available_mw=("solar_available_mw", "mean"),
            wind_available_mw=("wind_available_mw", "mean"),
        )
        .sort_values("hour")
        .reset_index(drop=True)
    )
    period_and_price = [
        _qinghai_tou_period_and_price(int(hour))
        for hour in scenario["hour"]
    ]
    scenario["tou_period"] = [item[0] for item in period_and_price]
    scenario["electricity_price_cny_per_kwh"] = [
        item[1] for item in period_and_price
    ]
    return scenario[ENERGY_SCENARIO_COLUMNS]
```

重写 `load_energy_scenario` 的精确签名和验证行为：

```python
def load_energy_scenario(
    csv_path: Path,
    params: Parameters,
    weather_source_path: Path | None = None,
) -> pd.DataFrame:
```

它必须：

1. 精确验证七个字段和小时 `0..23`；
2. 验证 `tou_period` 和 `electricity_price_cny_per_kwh` 与 `_qinghai_tou_period_and_price` 一致；
3. 验证光伏功率在 `[0, 3.0]`，风电功率在 `[0, 6.6]`；
4. 当 `weather_source_path` 非空时，调用 `build_provisional_energy_scenario`，按下面的精确逻辑验证每一列并报告首个不一致字段：

```python
if weather_source_path is not None:
    expected = build_provisional_energy_scenario(
        weather_source_path,
        params,
    )
    for column in ENERGY_SCENARIO_COLUMNS:
        if column in {"tou_period"}:
            matches = scenario[column].equals(expected[column])
        else:
            matches = np.allclose(
                scenario[column].to_numpy(dtype=float),
                expected[column].to_numpy(dtype=float),
                rtol=0.0,
                atol=1e-10,
            )
        if not matches:
            raise ValueError(
                f"{column} 与气象源及已确认参数不一致"
            )
```

导出接口：

```python
from .data import (
    build_provisional_energy_scenario,
    load_and_prepare,
    load_energy_scenario,
    load_phoenix_weather_source,
)
```

- [ ] **Step 5: Generate the committed provisional scenario**

Run:

```powershell
conda run -n scip_env python -c "from pathlib import Path; from scip_first_version import Parameters, build_provisional_energy_scenario; frame = build_provisional_energy_scenario(Path('data/phoenix_nasa_power_20190501_20190528_hourly.csv'), Parameters()); frame.to_csv(Path('data/provisional_phoenix_weather_qinghai_tou_scenario.csv'), index=False)"
```

Expected: the file has 24 data rows and the exact seven-column header.

- [ ] **Step 6: Run all parameter and scenario tests**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_cost_optimization.ParameterScaleTests tests.test_cost_optimization.EnergyScenarioInterfaceTests -v
```

Expected: `OK`.

- [ ] **Step 7: Commit only the scenario implementation and generated file**

```powershell
git add -- scip_first_version/data.py scip_first_version/__init__.py tests/test_cost_optimization.py data/phoenix_nasa_power_20190501_20190528_hourly.csv data/provisional_phoenix_weather_qinghai_tou_scenario.csv
git diff --cached --check
git commit -m "构建临时风光与青海电价场景"
```

## Task 3: Implement the Primary Day-Ahead Cost Model

**Files:**

- Modify: `tests/test_cost_optimization.py`
- Modify: `scip_first_version/model.py`

- [ ] **Step 1: Replace USD and degradation tests with four CNY cost tests**

把所有 `electricity_price_usd_per_kwh` 调用和断言改为精确标识符 `electricity_price_cny_per_kwh`。把一级成本测试改为：

```python
def test_primary_cost_equals_four_recomputed_components(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        result, metrics = build_and_solve(
            cpu_arrival=self.cpu_arrival,
            solar_available_mw=self.scenario[
                "solar_available_mw"
            ].to_numpy(dtype=float),
            wind_available_mw=self.scenario[
                "wind_available_mw"
            ].to_numpy(dtype=float),
            electricity_price_cny_per_kwh=self.scenario[
                "electricity_price_cny_per_kwh"
            ].to_numpy(dtype=float),
            params=self.params,
            enable_shift=False,
            enable_storage=False,
            enable_renewables=True,
            case_name="primary_cost_test",
            output_dir=Path(temporary_directory),
            show_log=False,
        )

    dt = self.params.time_step_h
    expected_grid = float(
        (
            result["electricity_price_cny_per_kwh"]
            * result["grid_power_mw"]
            * dt
            * 1000.0
        ).sum()
    )
    expected_solar = float(
        (
            result["solar_used_mw"]
            * self.params.solar_om_cost_cny_per_kw
            * dt
            * 1000.0
        ).sum()
    )
    expected_wind = float(
        (
            result["wind_used_mw"]
            * self.params.wind_om_cost_cny_per_kw
            * dt
            * 1000.0
        ).sum()
    )
    expected_storage = float(
        (
            (result["charge_mw"] + result["discharge_mw"])
            * self.params.battery_om_cost_cny_per_kw
            * dt
            * 1000.0
        ).sum()
    )
    expected_total = (
        expected_grid
        + expected_solar
        + expected_wind
        + expected_storage
    )

    self.assertAlmostEqual(
        metrics["grid_purchase_cost_cny"],
        expected_grid,
        delta=1e-6,
    )
    self.assertAlmostEqual(
        metrics["solar_om_cost_cny"],
        expected_solar,
        delta=1e-6,
    )
    self.assertAlmostEqual(
        metrics["wind_om_cost_cny"],
        expected_wind,
        delta=1e-6,
    )
    self.assertAlmostEqual(
        metrics["battery_om_cost_cny"],
        expected_storage,
        delta=1e-6,
    )
    self.assertAlmostEqual(
        metrics["operating_cost_cny"],
        expected_total,
        delta=1e-6,
    )
```

新增精确功率尺度和电网容量测试：

```python
def test_grid_only_uses_server_power_formula_and_grid_limit(self) -> None:
    cpu = np.full(24, 0.90, dtype=float)
    with tempfile.TemporaryDirectory() as temporary_directory:
        result, _ = build_and_solve(
            cpu_arrival=cpu,
            solar_available_mw=np.zeros(24),
            wind_available_mw=np.zeros(24),
            electricity_price_cny_per_kwh=np.full(24, 0.4489),
            params=self.params,
            enable_shift=False,
            enable_storage=False,
            enable_renewables=False,
            case_name="grid_capacity_test",
            output_dir=Path(temporary_directory),
            show_log=False,
        )

    np.testing.assert_allclose(result["it_power_mw"], 6.60, atol=1e-9)
    np.testing.assert_allclose(result["dc_power_mw"], 7.26, atol=1e-9)
    np.testing.assert_allclose(result["grid_power_mw"], 7.26, atol=1e-9)
    self.assertLessEqual(
        float(result["grid_power_mw"].max()),
        self.params.grid_capacity_mw + 1e-9,
    )
```

保留并更新以下测试：

- 风光“利用 + 弃电 = 可用”；
- 电网 + 风光利用 + 放电 = 数据中心负荷 + 充电；
- CPU 总量守恒、容量 0.90、最大延迟 3 小时；
- 高风光合成场景产生弃电；
- CPU 容量不足明确报错；
- 电网功率在 `[0, 7.66]`。

- [ ] **Step 2: Run the updated model tests and confirm failure**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_cost_optimization.CostOptimizationModelTests.test_primary_cost_equals_four_recomputed_components tests.test_cost_optimization.CostOptimizationModelTests.test_grid_only_uses_server_power_formula_and_grid_limit -v
```

Expected: `FAILED`; old function signature, old IT power scale, or missing CNY metrics are reported.

- [ ] **Step 3: Update the public solver signature and input validation**

把 `build_and_solve` 的签名精确改为：

```python
def build_and_solve(
    cpu_arrival: np.ndarray,
    solar_available_mw: np.ndarray,
    wind_available_mw: np.ndarray,
    electricity_price_cny_per_kwh: np.ndarray,
    params: Parameters,
    enable_shift: bool,
    enable_storage: bool,
    enable_renewables: bool,
    case_name: str,
    output_dir: Path,
    show_log: bool,
) -> tuple[pd.DataFrame, dict]:
```

在建模前将四个时间序列转换为一维浮点数组并验证长度相同、有限、非负。CPU 超过 `cpu_capacity_pu` 且不能通过允许的时移恢复时，不新增缺口变量。

- [ ] **Step 4: Replace the physical model with the approved equations**

模型变量和约束使用以下精确结构：

```python
grid_power = {
    t: model.addVar(
        lb=0.0,
        ub=params.grid_capacity_mw,
        name=f"grid_power_{t}",
    )
    for t in hours
}
solar_used = {
    t: model.addVar(lb=0.0, name=f"solar_used_{t}")
    for t in hours
}
solar_curtailed = {
    t: model.addVar(lb=0.0, name=f"solar_curtailed_{t}")
    for t in hours
}
wind_used = {
    t: model.addVar(lb=0.0, name=f"wind_used_{t}")
    for t in hours
}
wind_curtailed = {
    t: model.addVar(lb=0.0, name=f"wind_curtailed_{t}")
    for t in hours
}
```

算力与功率映射：

```python
it_idle_mw = params.it_power_mw(0.0)
it_slope_mw = (
    params.it_power_mw(1.0) - params.it_power_mw(0.0)
)
it_power_expr = {
    t: it_idle_mw + it_slope_mw * cpu_scheduled[t]
    for t in hours
}
dc_power_expr = {
    t: params.pue * it_power_expr[t]
    for t in hours
}
```

当 `enable_renewables=False` 时，将传入模型的光伏和风电可用量统一置零；否则保留传入值。每小时加入：

```python
model.addCons(
    solar_used[t] + solar_curtailed[t]
    == effective_solar_available[t],
    name=f"solar_balance_{t}",
)
model.addCons(
    wind_used[t] + wind_curtailed[t]
    == effective_wind_available[t],
    name=f"wind_balance_{t}",
)
model.addCons(
    grid_power[t]
    + solar_used[t]
    + wind_used[t]
    + discharge_power[t]
    == dc_power_expr[t] + charge_power[t],
    name=f"power_balance_{t}",
)
```

当储能关闭时，`charge_power[t]` 和 `discharge_power[t]` 使用数值 `0.0`；储能详细约束在 Task 4 加入。

- [ ] **Step 5: Define the four primary cost expressions**

```python
grid_cost_expr = quicksum(
    electricity_price_cny_per_kwh[t]
    * grid_power[t]
    * params.time_step_h
    * 1000.0
    for t in hours
)
solar_om_cost_expr = quicksum(
    params.solar_om_cost_cny_per_kw
    * solar_used[t]
    * params.time_step_h
    * 1000.0
    for t in hours
)
wind_om_cost_expr = quicksum(
    params.wind_om_cost_cny_per_kw
    * wind_used[t]
    * params.time_step_h
    * 1000.0
    for t in hours
)
battery_om_cost_expr = quicksum(
    params.battery_om_cost_cny_per_kw
    * (charge_power[t] + discharge_power[t])
    * params.time_step_h
    * 1000.0
    for t in hours
)
primary_cost_expr = (
    grid_cost_expr
    + solar_om_cost_expr
    + wind_om_cost_expr
    + battery_om_cost_expr
)
model.setObjective(primary_cost_expr, "minimize")
```

设置：

```python
model.setRealParam("limits/time", params.time_limit_s)
model.setRealParam("limits/gap", params.relative_gap)
```

一级求解前写出：

```python
model.writeProblem(str(output_dir / f"{case_name}_primary.lp"))
```

若 `model.getNSols() == 0`，抛出 `RuntimeError`，信息包含算例名和 SCIP 状态。

- [ ] **Step 6: Extract exact hourly cost fields and primary metrics**

小时结果写入：

```python
"electricity_price_cny_per_kwh"
"hourly_grid_purchase_cost_cny"
"hourly_solar_om_cost_cny"
"hourly_wind_om_cost_cny"
"hourly_battery_om_cost_cny"
"hourly_operating_cost_cny"
```

汇总结果写入：

```python
"grid_purchase_cost_cny"
"solar_om_cost_cny"
"wind_om_cost_cny"
"battery_om_cost_cny"
"operating_cost_cny"
```

`operating_cost_cny` 必须由最终小时表的四项成本重算，不使用二级目标值代替。

- [ ] **Step 7: Run primary-model tests**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_cost_optimization.CostOptimizationModelTests.test_primary_cost_equals_four_recomputed_components tests.test_cost_optimization.CostOptimizationModelTests.test_grid_only_uses_server_power_formula_and_grid_limit tests.test_cost_optimization.CostOptimizationModelTests.test_renewable_dispatch_preserves_power_and_resource_balances tests.test_cost_optimization.CostOptimizationModelTests.test_high_renewable_supply_reports_positive_curtailment tests.test_cost_optimization.CostOptimizationModelTests.test_insufficient_cpu_capacity_is_infeasible tests.test_cost_optimization.CostOptimizationModelTests.test_shifted_compute_cannot_exceed_maximum_delay -v
```

Expected: all six primary-model tests pass. Storage-specific and two-level tests are introduced and run in Task 4.

- [ ] **Step 8: Commit the primary model**

```powershell
git add -- scip_first_version/model.py tests/test_cost_optimization.py
git diff --cached --check
git commit -m "实现确定性日前一级成本模型"
```

## Task 4: Add Storage Constraints and Lexicographic Secondary Solve

**Files:**

- Modify: `tests/test_cost_optimization.py`
- Modify: `scip_first_version/model.py`

- [ ] **Step 1: Add storage behavior and activity-period tests**

新增：

```python
def test_storage_obeys_soc_power_and_activity_constraints(self) -> None:
    prices = np.full(24, 0.7174, dtype=float)
    prices[:8] = 0.1804
    with tempfile.TemporaryDirectory() as temporary_directory:
        result, metrics = build_and_solve(
            cpu_arrival=self.cpu_arrival,
            solar_available_mw=np.zeros(24),
            wind_available_mw=np.zeros(24),
            electricity_price_cny_per_kwh=prices,
            params=self.params,
            enable_shift=False,
            enable_storage=True,
            enable_renewables=False,
            case_name="storage_constraints_test",
            output_dir=Path(temporary_directory),
            show_log=False,
        )

    self.assertGreater(float(result["charge_mw"].sum()), 0.0)
    self.assertGreater(float(result["discharge_mw"].sum()), 0.0)
    self.assertLessEqual(float(result["charge_mw"].max()), 0.4 + 1e-9)
    self.assertLessEqual(float(result["discharge_mw"].max()), 0.25 + 1e-9)
    self.assertGreaterEqual(float(result["soc_start"].min()), 0.10 - 1e-9)
    self.assertLessEqual(float(result["soc_end"].max()), 0.90 + 1e-9)
    self.assertAlmostEqual(float(result["soc_start"].iloc[0]), 0.50)
    self.assertAlmostEqual(float(result["soc_end"].iloc[-1]), 0.50)
    self.assertLessEqual(
        float((result["charge_mw"] * result["discharge_mw"]).max()),
        1e-9,
    )
    self.assertLessEqual(metrics["battery_active_periods"], 16)
    expected_battery_om = float(
        (
            (result["charge_mw"] + result["discharge_mw"])
            * self.params.battery_om_cost_cny_per_kw
            * self.params.time_step_h
            * 1000.0
        ).sum()
    )
    self.assertAlmostEqual(
        metrics["battery_om_cost_cny"],
        expected_battery_om,
        delta=1e-6,
    )
```

新增无价差测试：

```python
def test_storage_can_remain_idle_without_economic_value(self) -> None:
    flat_price = np.full(24, 0.4489, dtype=float)
    with tempfile.TemporaryDirectory() as temporary_directory:
        result, _ = build_and_solve(
            cpu_arrival=self.cpu_arrival,
            solar_available_mw=np.zeros(24),
            wind_available_mw=np.zeros(24),
            electricity_price_cny_per_kwh=flat_price,
            params=self.params,
            enable_shift=False,
            enable_storage=True,
            enable_renewables=False,
            case_name="storage_idle_test",
            output_dir=Path(temporary_directory),
            show_log=False,
        )

    self.assertAlmostEqual(float(result["charge_mw"].sum()), 0.0, delta=1e-8)
    self.assertAlmostEqual(
        float(result["discharge_mw"].sum()),
        0.0,
        delta=1e-8,
    )
```

- [ ] **Step 2: Add a two-level objective test**

```python
def test_secondary_solve_respects_cost_tolerance_and_reduces_delay(
    self,
) -> None:
    cpu = np.zeros(24, dtype=float)
    cpu[0] = 0.60
    prices = np.full(24, 0.4489, dtype=float)
    with tempfile.TemporaryDirectory() as temporary_directory:
        output_dir = Path(temporary_directory)
        _, metrics = build_and_solve(
            cpu_arrival=cpu,
            solar_available_mw=np.zeros(24),
            wind_available_mw=np.zeros(24),
            electricity_price_cny_per_kwh=prices,
            params=self.params,
            enable_shift=True,
            enable_storage=False,
            enable_renewables=False,
            case_name="lexicographic_test",
            output_dir=output_dir,
            show_log=False,
        )

        self.assertTrue((output_dir / "lexicographic_test_primary.lp").is_file())
        self.assertTrue(
            (output_dir / "lexicographic_test_secondary.lp").is_file()
        )

    self.assertLessEqual(
        metrics["operating_cost_cny"],
        metrics["primary_operating_cost_cny"]
        + self.params.primary_cost_tolerance_cny
        + 1e-6,
    )
    self.assertLessEqual(
        metrics["total_task_delay_cpu_hours"],
        metrics["primary_total_task_delay_cpu_hours"] + 1e-9,
    )
    self.assertEqual(metrics["primary_solve_status"], "optimal")
    self.assertEqual(metrics["secondary_solve_status"], "optimal")
```

- [ ] **Step 3: Run the new tests and confirm failure**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_cost_optimization.CostOptimizationModelTests.test_storage_obeys_soc_power_and_activity_constraints tests.test_cost_optimization.CostOptimizationModelTests.test_storage_can_remain_idle_without_economic_value tests.test_cost_optimization.CostOptimizationModelTests.test_secondary_solve_respects_cost_tolerance_and_reduces_delay -v
```

Expected: `FAILED`; storage activity fields, secondary LP, or secondary metrics are missing.

- [ ] **Step 4: Implement the exact storage constraints**

当 `enable_storage=True` 时建立：

```python
charge_power = {
    t: model.addVar(
        lb=0.0,
        ub=params.battery_charge_power_mw,
        name=f"charge_power_{t}",
    )
    for t in hours
}
discharge_power = {
    t: model.addVar(
        lb=0.0,
        ub=params.battery_discharge_power_mw,
        name=f"discharge_power_{t}",
    )
    for t in hours
}
charge_active = {
    t: model.addVar(vtype="B", name=f"charge_active_{t}")
    for t in hours
}
discharge_active = {
    t: model.addVar(vtype="B", name=f"discharge_active_{t}")
    for t in hours
}
stored_energy = {
    t: model.addVar(
        lb=params.battery_soc_min * params.battery_energy_mwh,
        ub=params.battery_soc_max * params.battery_energy_mwh,
        name=f"stored_energy_{t}",
    )
    for t in range(period_count + 1)
}
```

加入：

```python
model.addCons(
    stored_energy[0]
    == params.battery_soc_initial * params.battery_energy_mwh,
    name="initial_soc",
)
model.addCons(
    stored_energy[period_count]
    == params.battery_soc_initial * params.battery_energy_mwh,
    name="terminal_soc",
)
for t in hours:
    model.addCons(
        charge_power[t]
        <= params.battery_charge_power_mw * charge_active[t],
        name=f"charge_activity_link_{t}",
    )
    model.addCons(
        discharge_power[t]
        <= params.battery_discharge_power_mw * discharge_active[t],
        name=f"discharge_activity_link_{t}",
    )
    model.addCons(
        charge_active[t] + discharge_active[t] <= 1,
        name=f"charge_discharge_exclusion_{t}",
    )
    model.addCons(
        stored_energy[t + 1]
        == stored_energy[t]
        + params.charge_efficiency
        * charge_power[t]
        * params.time_step_h
        - discharge_power[t]
        * params.time_step_h
        / params.discharge_efficiency,
        name=f"stored_energy_balance_{t}",
    )
model.addCons(
    quicksum(
        charge_active[t] + discharge_active[t]
        for t in hours
    )
    <= params.battery_max_active_periods,
    name="battery_active_period_limit",
)
```

当储能关闭时，小时输出中的充电、放电、活动状态均为 0，SOC 起止均为 0.50。

- [ ] **Step 5: Implement the secondary sequential solve**

柔性调度的总延迟表达式固定为：

```python
total_task_delay_expr = quicksum(
    (target - origin) * shifted_cpu[origin, target]
    for origin, target in shifted_cpu
)
```

一级求解完成后立即读取：

```python
primary_operating_cost_cny = float(model.getVal(primary_cost_expr))
primary_total_task_delay_cpu_hours = float(
    model.getVal(total_task_delay_expr)
)
primary_solve_status = str(model.getStatus())
primary_solve_time_s = float(model.getSolvingTime())
primary_gap = float(model.getGap())
```

然后依次执行：

```python
model.freeTransform()
model.addCons(
    primary_cost_expr
    <= primary_operating_cost_cny
    + params.primary_cost_tolerance_cny,
    name="primary_cost_tolerance",
)
model.setObjective(total_task_delay_expr, "minimize")
model.writeProblem(str(output_dir / f"{case_name}_secondary.lp"))
model.optimize()
```

第二次求解后再次验证 `model.getNSols() > 0`。从第二次解提取所有小时变量，并独立重算四项成本。若最终 `operating_cost_cny` 大于 `primary_operating_cost_cny + 0.01 + 1e-6`，抛出 `RuntimeError`。

增加以下精确汇总字段：

```python
"primary_operating_cost_cny"
"primary_total_task_delay_cpu_hours"
"total_task_delay_cpu_hours"
"average_flexible_task_delay_h"
"primary_solve_status"
"secondary_solve_status"
"primary_solve_time_s"
"secondary_solve_time_s"
"primary_gap"
"secondary_gap"
"battery_active_periods"
```

`average_flexible_task_delay_h` 的分母为 `flex_ratio * cpu_arrival.sum()`；分母为零时返回 `0.0`。

- [ ] **Step 6: Run all model tests**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_cost_optimization.CostOptimizationModelTests -v
```

Expected: `OK`.

- [ ] **Step 7: Commit storage and two-level optimization**

```powershell
git add -- scip_first_version/model.py tests/test_cost_optimization.py
git diff --cached --check
git commit -m "加入储能约束与两层顺序求解"
```

## Task 5: Align the Runner and Public Outputs

**Files:**

- Modify: `tests/test_runner_outputs.py`
- Modify: `tests/test_refactor_regression.py`
- Modify: `run_first_version.py`
- Modify: `scip_first_version/__init__.py`

- [ ] **Step 1: Replace the runner output contract test**

将默认路径和命令参数改为：

```python
arguments = [
    "run_first_version.py",
    "--input",
    "data/instance_usage_grouped_300_seconds_month.csv",
    "--weather-source",
    "data/phoenix_nasa_power_20190501_20190528_hourly.csv",
    "--energy-scenario",
    "data/provisional_phoenix_weather_qinghai_tou_scenario.csv",
    "--output-dir",
    str(output_dir),
]
```

汇总字段至少断言：

```python
{
    "grid_purchase_cost_cny",
    "solar_om_cost_cny",
    "wind_om_cost_cny",
    "battery_om_cost_cny",
    "operating_cost_cny",
    "operating_cost_savings_vs_grid_only_pct",
    "grid_purchase_energy_mwh",
    "grid_peak_power_mw",
    "renewable_available_energy_mwh",
    "renewable_used_energy_mwh",
    "renewable_curtailment_energy_mwh",
    "renewable_curtailment_rate_pct",
    "battery_charged_energy_mwh",
    "battery_discharged_energy_mwh",
    "battery_active_periods",
    "total_task_delay_cpu_hours",
    "average_flexible_task_delay_h",
    "cpu_conservation_error",
    "soc_cycle_error",
    "max_simultaneous_charge_discharge_mw2",
    "primary_solve_status",
    "secondary_solve_status",
}
```

小时字段至少断言：

```python
{
    "cpu_arrival_pu",
    "cpu_scheduled_pu",
    "it_power_mw",
    "dc_power_mw",
    "grid_power_mw",
    "solar_available_mw",
    "solar_used_mw",
    "solar_curtailed_mw",
    "wind_available_mw",
    "wind_used_mw",
    "wind_curtailed_mw",
    "charge_mw",
    "discharge_mw",
    "soc_start",
    "soc_end",
    "tou_period",
    "electricity_price_cny_per_kwh",
    "hourly_grid_purchase_cost_cny",
    "hourly_solar_om_cost_cny",
    "hourly_wind_om_cost_cny",
    "hourly_battery_om_cost_cny",
    "hourly_operating_cost_cny",
}
```

每组算例必须存在：

```python
for case_name in [
    "grid_only",
    "renewables_only",
    "renewables_shift",
    "renewables_storage",
    "joint",
]:
    self.assertTrue(
        (output_dir / f"{case_name}_primary.lp").is_file()
    )
    self.assertTrue(
        (output_dir / f"{case_name}_secondary.lp").is_file()
    )
```

同时检查：

```python
for filename in [
    "model_input_typical_day.csv",
    "hourly_case_results.csv",
    "case_metrics.csv",
    "run_metadata.json",
]:
    self.assertTrue((output_dir / filename).is_file(), filename)
```

- [ ] **Step 2: Run the runner test and confirm failure**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_runner_outputs -v
```

Expected: `FAILED`; old default scenario, missing `--weather-source`, old USD fields, or old LP names are reported.

- [ ] **Step 3: Update CLI defaults and scenario provenance validation**

在 `parse_args` 中精确设置：

```python
parser.add_argument(
    "--weather-source",
    type=Path,
    default=Path(
        "data/phoenix_nasa_power_20190501_20190528_hourly.csv"
    ),
)
parser.add_argument(
    "--energy-scenario",
    type=Path,
    default=Path(
        "data/provisional_phoenix_weather_qinghai_tou_scenario.csv"
    ),
)
parser.add_argument(
    "--output-dir",
    type=Path,
    default=Path("outputs/day_ahead_deterministic"),
)
```

加载场景时必须传入源文件：

```python
energy_scenario = load_energy_scenario(
    args.energy_scenario,
    params,
    weather_source_path=args.weather_source,
)
```

模型调用使用：

```python
electricity_price_cny_per_kwh=energy_scenario[
    "electricity_price_cny_per_kwh"
].to_numpy(dtype=float)
```

- [ ] **Step 4: Preserve the exact five-case order and calculate savings**

五组算例顺序固定为：

```python
cases = [
    ("grid_only", False, False, False),
    ("renewables_only", False, False, True),
    ("renewables_shift", True, False, True),
    ("renewables_storage", False, True, True),
    ("joint", True, True, True),
]
```

元组含义依次为：

```text
case_name, enable_shift, enable_storage, enable_renewables
```

所有算例结束后，以 `grid_only` 的 `operating_cost_cny` 为基准计算：

```python
metrics_frame["operating_cost_savings_vs_grid_only_pct"] = (
    (
        grid_only_cost
        - metrics_frame["operating_cost_cny"]
    )
    / grid_only_cost
    * 100.0
)
```

- [ ] **Step 5: Write exact run metadata**

`run_metadata.json` 至少含以下精确键：

```python
metadata = {
    "model_type": "deterministic_day_ahead",
    "scenario_status": "provisional_mixed_region_development_scenario",
    "weather_source": {
        "file": str(args.weather_source),
        "location": "Phoenix, Arizona, USA",
        "latitude": 33.4484,
        "longitude": -112.0740,
        "time_standard": "LST",
        "period": "2019-05-01/2019-05-28",
    },
    "electricity_price_source": {
        "region": "Qinghai, China",
        "currency": "CNY",
        "tariff_type": "time_of_use",
        "source_paper": (
            "A novel demand response-based distributed multi-energy "
            "system optimal operation framework for data centers"
        ),
    },
    "geographic_interpretation": (
        "The mixed Phoenix-weather and Qinghai-price scenario is only "
        "for model development and module validation."
    ),
    "representative_day": int(representative_day),
    "stress_day": int(stress_day),
    "parameters": asdict(params),
    "software_versions": software_versions(),
}
```

由于 `asdict(params)` 不含只读派生属性，在 `parameters` 中另外加入：

```python
"server_idle_power_kw"
"solar_capacity_mw"
"wind_capacity_mw"
```

- [ ] **Step 6: Update regression tests to the exact new interface**

在 `tests/test_refactor_regression.py`：

1. 保持代表日为第 8 天、压力日为第 28 天；
2. 场景路径改为临时混合场景；
3. 加载时传入 672 小时源文件；
4. 所有价格字段改为 `electricity_price_cny_per_kwh`；
5. 所有成本断言改为 `operating_cost_cny`；
6. 验证 `joint <= renewables_shift + 0.01 + 1e-6`；
7. 验证 `renewables_storage <= renewables_only + 0.01 + 1e-6`。

- [ ] **Step 7: Run runner and regression tests**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_runner_outputs tests.test_refactor_regression -v
```

Expected: `OK`.

- [ ] **Step 8: Commit the runner contract**

```powershell
git add -- run_first_version.py scip_first_version/__init__.py tests/test_runner_outputs.py tests/test_refactor_regression.py
git diff --cached --check
git commit -m "对齐日前算例入口与输出接口"
```

## Task 6: Update All Figures for Four CNY Cost Components

**Files:**

- Modify: `scip_first_version/reporting.py`
- Modify: `tests/test_runner_outputs.py`

- [ ] **Step 1: Extend the runner test with the exact figure set**

断言以下文件存在且文件大小大于 0：

```python
expected_figures = [
    "day_ahead_power_results.png",
    "compute_scheduling_results.png",
    "battery_operation_results.png",
    "renewable_dispatch_results.png",
    "operating_cost_comparison.png",
]
for filename in expected_figures:
    path = output_dir / filename
    self.assertTrue(path.is_file(), filename)
    self.assertGreater(path.stat().st_size, 0, filename)
```

- [ ] **Step 2: Run the figure-output test and confirm failure**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_runner_outputs.RunnerOutputTests.test_cli_generates_five_cost_optimization_cases -v
```

Expected: `FAILED`; old figure names or old USD/degradation chart fields are reported.

- [ ] **Step 3: Replace cost comparison with a four-component stacked chart**

在 `_draw_cost_comparison` 中使用精确列：

```python
cost_columns = [
    "grid_purchase_cost_cny",
    "solar_om_cost_cny",
    "wind_om_cost_cny",
    "battery_om_cost_cny",
]
cost_labels = [
    "Grid purchase",
    "Solar O&M",
    "Wind O&M",
    "Battery O&M",
]
cost_colors = ["#35618F", "#E6B84A", "#6A9D65", "#B56A79"]
```

每个分量以累计 `bottom` 绘制，纵轴标题固定为：

```python
"Operating cost (CNY/day)"
```

图标题固定为：

```python
"Deterministic Day-Ahead Operating Cost"
```

不得再引用：

```text
battery_degradation_cost_usd
grid_purchase_cost_usd
operating_cost_usd
Phoenix electricity price
APS
```

- [ ] **Step 4: Align the four operational figures**

图表使用以下数据：

1. `day_ahead_power_results.png`：`dc_power_mw`、`grid_power_mw`、`solar_used_mw`、`wind_used_mw`；
2. `compute_scheduling_results.png`：`cpu_arrival_pu`、`cpu_scheduled_pu`；
3. `battery_operation_results.png`：`charge_mw`、`discharge_mw`、`soc_start`、`soc_end`；
4. `renewable_dispatch_results.png`：光伏和风电的可用、利用、弃电；
5. `operating_cost_comparison.png`：四项成本堆叠柱状图。

所有标题把场景写为 “Provisional Phoenix Weather + Qinghai TOU”，不写成菲尼克斯完整地区算例。

- [ ] **Step 5: Run the runner test**

Run:

```powershell
conda run -n scip_env python -m unittest tests.test_runner_outputs -v
```

Expected: `OK`.

- [ ] **Step 6: Commit reporting changes**

```powershell
git add -- scip_first_version/reporting.py tests/test_runner_outputs.py
git diff --cached --check
git commit -m "更新日前运行结果与成本图表"
```

## Task 7: Rewrite the User Guide Around the Deterministic Day-Ahead Model

**Files:**

- Modify: `FIRST_VERSION_GUIDE.md`

- [ ] **Step 1: Replace obsolete model statements**

指南必须精确包含：

1. 主模型是 24 小时确定性日前优化，不是连续 28 天优化；
2. 28 天 Google 轨迹用于选择代表日，第 8 天是代表日，第 28 天是压力日；
3. 菲尼克斯 672 小时气象只用于构造临时典型风光曲线；
4. 青海分时电价与菲尼克斯气象来自不同地区；
5. 当前结果只用于开发和模块验证，不作地理实证解释；
6. IT 功率公式 `4.125 + 2.75u` MW、PUE 1.10、CPU 上限 0.90；
7. 光伏 3.0 MW、风电 6.6 MW、电储能 1 MWh、电网 7.66 MW；
8. 四项 CNY 一级成本和 0.01 CNY 容差下的二级任务延迟；
9. 储能零运行可能是正确经济结果，模块有效性由合成峰谷测试验证；
10. 最终论文需重新选择并对齐气象、电价、日期和时区数据。

- [ ] **Step 2: Document the exact commands**

```powershell
conda run -n scip_env python -m unittest discover -s tests -v
conda run -n scip_env python run_first_version.py
```

默认输出目录写为：

```text
outputs/day_ahead_deterministic
```

- [ ] **Step 3: Scan the guide for obsolete terminology**

Run:

```powershell
rg -n "USD|APS|36\.35|battery_degradation|20 MW|outputs/cost_optimization|phoenix_typical_may_workday_energy_scenario" FIRST_VERSION_GUIDE.md
```

Expected: no matches.

- [ ] **Step 4: Commit the guide**

```powershell
git add -- FIRST_VERSION_GUIDE.md
git diff --cached --check
git commit -m "更新确定性日前模型使用指南"
```

## Task 8: Full Verification and Artifact Inspection

**Files:**

- Verify: all files above
- Verify outputs: `outputs/day_ahead_deterministic/`

- [ ] **Step 1: Run the complete unit-test suite**

Run:

```powershell
conda run -n scip_env python -m unittest discover -s tests -v
```

Expected: every test reports `ok`; final line is `OK`.

- [ ] **Step 2: Run the default entrypoint**

Run:

```powershell
conda run -n scip_env python run_first_version.py
```

Expected: exit code 0; five cases solve twice and files are written under `outputs/day_ahead_deterministic`.

- [ ] **Step 3: Independently verify output tables**

Run:

```powershell
conda run -n scip_env python -c "import pandas as pd; from pathlib import Path; root=Path('outputs/day_ahead_deterministic'); hourly=pd.read_csv(root/'hourly_case_results.csv'); metrics=pd.read_csv(root/'case_metrics.csv'); assert len(hourly)==120; assert metrics['case'].tolist()==['grid_only','renewables_only','renewables_shift','renewables_storage','joint']; recomputed=metrics['grid_purchase_cost_cny']+metrics['solar_om_cost_cny']+metrics['wind_om_cost_cny']+metrics['battery_om_cost_cny']; assert ((recomputed-metrics['operating_cost_cny']).abs()<=1e-6).all(); assert (hourly['grid_power_mw']>=-1e-9).all(); assert (hourly['grid_power_mw']<=7.66+1e-9).all(); print('output verification OK')"
```

Expected:

```text
output verification OK
```

- [ ] **Step 4: Verify the secondary-cost tolerance**

Run:

```powershell
conda run -n scip_env python -c "import pandas as pd; m=pd.read_csv('outputs/day_ahead_deterministic/case_metrics.csv'); assert (m['operating_cost_cny']<=m['primary_operating_cost_cny']+0.010001).all(); assert (m['total_task_delay_cpu_hours']<=m['primary_total_task_delay_cpu_hours']+1e-8).all(); print('two-level verification OK')"
```

Expected:

```text
two-level verification OK
```

- [ ] **Step 5: Verify exact LP and image files**

Run:

```powershell
$output = 'outputs\day_ahead_deterministic'
$cases = @('grid_only','renewables_only','renewables_shift','renewables_storage','joint')
foreach ($case in $cases) {
    if (-not (Test-Path -LiteralPath "$output\$case`_primary.lp")) { throw "missing primary LP: $case" }
    if (-not (Test-Path -LiteralPath "$output\$case`_secondary.lp")) { throw "missing secondary LP: $case" }
}
$figures = @(
    'day_ahead_power_results.png',
    'compute_scheduling_results.png',
    'battery_operation_results.png',
    'renewable_dispatch_results.png',
    'operating_cost_comparison.png'
)
foreach ($figure in $figures) {
    $path = Join-Path $output $figure
    if ((Get-Item -LiteralPath $path).Length -le 0) { throw "empty figure: $figure" }
}
Write-Output 'artifact verification OK'
```

Expected:

```text
artifact verification OK
```

- [ ] **Step 6: Scan implementation for obsolete units and interfaces**

Run:

```powershell
rg -n "electricity_price_usd_per_kwh|grid_purchase_cost_usd|operating_cost_usd|battery_degradation_cost_usd|36\.35|solar_performance_ratio|it_peak_power_mw|battery_power_mw" run_first_version.py scip_first_version tests FIRST_VERSION_GUIDE.md
```

Expected: no matches.

The retained legacy CSV may still contain the old APS/USD column and is intentionally outside this scan.

- [ ] **Step 7: Check formatting and inspect the worktree**

Run:

```powershell
git diff --check
git status --short
git log --oneline -8
```

Expected:

- `git diff --check` prints nothing;
- only intentionally retained user files or generated runtime output remain unstaged;
- the implementation commits appear in task order.

- [ ] **Step 8: Inspect the five figures**

Open all five PNG files and verify:

1. no clipped title, legend, label or axis text;
2. CNY/day is used on the cost chart;
3. storage charge and discharge signs are visually unambiguous;
4. SOC is bounded between 0.10 and 0.90;
5. renewable available/use/curtailment curves are distinguishable;
6. the mixed-region provisional nature is visible in figure titles or captions.

If visual defects are found, modify only `scip_first_version/reporting.py`, rerun the runner test and default entrypoint, and commit:

```powershell
git add -- scip_first_version/reporting.py
git diff --cached --check
git commit -m "修正日前结果图表布局"
```

## Final Review Checklist

- [ ] All 672 weather hours are continuous, ordered, unique and complete.
- [ ] Renewable power is calculated for each raw hour before the 28-day same-hour mean.
- [ ] The provisional CSV contains Qinghai CNY tariff values and no APS/USD field.
- [ ] The IT, renewable, storage and grid scales match the approved design.
- [ ] No compute-service shortage or load-shedding variable exists.
- [ ] The primary objective contains exactly four approved cost components.
- [ ] The secondary solve uses a hard `C* + 0.01 CNY` cost bound, not a weighted sum.
- [ ] Grid, renewable, CPU and storage conservation checks pass.
- [ ] Storage charge/discharge exclusion and the 16 active-period bound pass.
- [ ] Five cases and both LP files per case are produced.
- [ ] CSV, JSON and five figures are present and readable.
- [ ] Default results are described as a provisional mixed-region development scenario.
- [ ] The full test suite, default run, output recomputation and `git diff --check` pass.
- [ ] No unrelated file is staged.
