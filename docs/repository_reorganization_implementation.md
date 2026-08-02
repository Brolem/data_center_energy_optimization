# 项目结构与命名重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 Houston 2020 主实验数学模型、参数和结果的前提下，将仓库迁移为 `dc_energy_opt` 分层包、清晰的数据与文档命名、分层实验输出及可验证的兼容入口。

**Architecture:** 先冻结当前 71 项测试和四组主实验结果作为等价基线，再依次完成包名迁移、模块拆分、历史 Phoenix 归档、实验与事务发布解耦、测试和文档重组。每个阶段通过针对性测试和本地提交建立回退点；最终同时运行新入口和旧兼容入口，并对关键 CSV 做数值等价比较。

**Tech Stack:** Python 3.13、PySCIPOpt 6.2.1、SCIP 10.0.2、pandas、NumPy、Pillow、NREL-PySAM 7.1.0、`unittest`、PowerShell、Git。

---

## 目标文件职责

实施结束后，正式代码只包含以下职责边界：

- `dc_energy_opt/config.py`：`Parameters` 及计算属性；
- `dc_energy_opt/data/workload.py`：`load_and_prepare`；
- `dc_energy_opt/data/energy.py`：`HOUSTON_ENERGY_SCENARIO_COLUMNS`、`paper_tou_tariff`、`load_houston_energy_scenario`；
- `dc_energy_opt/optimization/types.py`：`PendingFlexibleTask`、`WindowSolveState`；
- `dc_energy_opt/optimization/window_model.py`：`build_and_solve` 及求解状态校验；
- `dc_energy_opt/optimization/rolling_day_ahead.py`：`ROLLING_CASES`、预热、SOC 协调和 `run_rolling_day_ahead`；
- `dc_energy_opt/experiments/artifacts.py`：`RunPaths`、分层临时目录和原子发布；
- `dc_energy_opt/experiments/houston_2020.py`：四组主实验、元数据和结果写入；
- `dc_energy_opt/reporting/metrics.py`：逐日及算例汇总指标；
- `dc_energy_opt/reporting/plots.py`：输入校验、软件版本和五张图；
- `run_day_ahead_experiment.py`：正式 CLI；
- `run_first_version.py`：旧参数兼容层，不包含第二份实验实现。

## Task 1：冻结当前 Houston 实现与结果基线

**Files:**

- Verify: `data/instance_usage_grouped_300_seconds_month.csv`
- Verify: `data/houston_2020_main_experiment_energy_scenario.csv`
- Verify: `outputs/day_ahead_deterministic/case_metrics.csv`
- Verify: `outputs/day_ahead_deterministic/hourly_case_results.csv`
- Verify: `outputs/day_ahead_deterministic/daily_case_metrics.csv`
- Commit: 当前已验证但尚未提交的 Houston 主实验代码、数据、测试和文档

- [ ] **Step 1：记录迁移前数据哈希**

Run:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath `
  'data\instance_usage_grouped_300_seconds_month.csv', `
  'data\houston_2020_main_experiment_energy_scenario.csv' |
  Format-Table Path,Hash -AutoSize
```

Expected: 输出两个非空 SHA256；将其复制到实施记录，不修改源文件。

- [ ] **Step 2：重新验证当前基线测试**

Run:

```powershell
conda run -n scip_env python -m unittest discover -s tests -v
```

Expected: `Ran 71 tests` 和 `OK`。

- [ ] **Step 3：重新生成当前四组基线结果**

Run:

```powershell
conda run -n scip_env python run_first_version.py `
  --output-dir outputs/day_ahead_deterministic
```

Expected: 四组算例状态均为 `optimal`，并生成 2,700 行小时结果、112 行逐日指标、232 个 LP 和 5 张图。

- [ ] **Step 4：保存只读等价基线**

Run:

```powershell
$baseline = 'outputs\repository_reorganization_baseline'
New-Item -ItemType Directory -Force -Path $baseline | Out-Null
Copy-Item -LiteralPath `
  'outputs\day_ahead_deterministic\hourly_case_results.csv', `
  'outputs\day_ahead_deterministic\daily_case_metrics.csv', `
  'outputs\day_ahead_deterministic\case_metrics.csv', `
  'outputs\day_ahead_deterministic\run_metadata.json' `
  -Destination $baseline
```

Expected: 基线目录只包含三个 CSV 和一个 JSON，不包含 LP 或图片。

- [ ] **Step 5：提交现有 Houston 主实验基线**

Stage only the exact existing implementation scope:

```powershell
git add -- `
  FIRST_VERSION_GUIDE.md `
  requirements.txt `
  run_first_version.py `
  scip_first_version `
  scripts/build_houston_2020_energy_scenario.py `
  tests/test_cost_optimization.py `
  tests/test_refactor_regression.py `
  tests/test_rolling_day_ahead.py `
  tests/test_runner_outputs.py `
  data/houston_2020_main_experiment_energy_scenario.csv `
  docs/superpowers/specs/2026-07-30-deterministic-day-ahead-design.md `
  docs/superpowers/plans/2026-07-30-deterministic-day-ahead-implementation.md
git diff --cached --name-status
git commit -m "实现 Houston 跨日确定性日前主实验"
```

Expected: 暂存清单只出现以上路径；`outputs/` 不进入提交。

## Task 2：迁移正式包名并保持功能不变

**Files:**

- Move: `scip_first_version/` → `dc_energy_opt/`
- Modify: `dc_energy_opt/__init__.py`
- Modify: `run_first_version.py`
- Modify: `scripts/build_houston_2020_energy_scenario.py`
- Modify: `tests/test_cost_optimization.py`
- Modify: `tests/test_refactor_regression.py`
- Modify: `tests/test_rolling_day_ahead.py`
- Modify: `tests/test_runner_outputs.py`

- [ ] **Step 1：先写新包导入失败测试**

Add to `tests/test_refactor_regression.py`:

```python
def test_formal_package_exports_current_interfaces(self) -> None:
    import dc_energy_opt

    self.assertIs(dc_energy_opt.Parameters, Parameters)
    self.assertTrue(callable(dc_energy_opt.load_and_prepare))
    self.assertTrue(callable(dc_energy_opt.load_houston_energy_scenario))
    self.assertTrue(callable(dc_energy_opt.build_and_solve))
    self.assertTrue(callable(dc_energy_opt.run_rolling_day_ahead))
```

- [ ] **Step 2：验证测试因新包不存在而失败**

Run:

```powershell
conda run -n scip_env python -m unittest `
  tests.test_refactor_regression.RefactorRegressionTests.test_formal_package_exports_current_interfaces -v
```

Expected: FAIL，错误为 `ModuleNotFoundError: No module named 'dc_energy_opt'`。

- [ ] **Step 3：移动包并精确更新导入**

Run:

```powershell
git mv scip_first_version dc_energy_opt
```

Replace every formal import prefix exactly:

```python
from dc_energy_opt.config import Parameters
from dc_energy_opt.data import load_and_prepare, load_houston_energy_scenario
from dc_energy_opt.model import PendingFlexibleTask, WindowSolveState, build_and_solve
from dc_energy_opt.rolling import ROLLING_CASES, run_rolling_day_ahead
from dc_energy_opt.reporting import make_plots, software_versions
```

Do not perform case-insensitive or partial identifier substitution. Run `rg -n "scip_first_version" run_first_version.py dc_energy_opt scripts tests` and update every exact hit.

- [ ] **Step 4：更新包说明并运行全量测试**

Set the first line of `dc_energy_opt/__init__.py` to:

```python
"""Data-center energy optimization with rolling deterministic day-ahead scheduling."""
```

Run:

```powershell
conda run -n scip_env python -m unittest discover -s tests -v
```

Expected: 71 项测试全部通过，四组算例输出不变。

- [ ] **Step 5：提交包名迁移**

```powershell
git add -- dc_energy_opt run_first_version.py scripts tests
git diff --cached --check
git commit -m "重命名正式优化包"
```

## Task 3：拆分优化模型与跨日状态

**Files:**

- Create: `dc_energy_opt/optimization/__init__.py`
- Create: `dc_energy_opt/optimization/types.py`
- Move: `dc_energy_opt/model.py` → `dc_energy_opt/optimization/window_model.py`
- Move: `dc_energy_opt/rolling.py` → `dc_energy_opt/optimization/rolling_day_ahead.py`
- Modify: `dc_energy_opt/__init__.py`
- Modify: `run_first_version.py`
- Modify: affected tests
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_optimization_types.py`

- [ ] **Step 1：写状态类型导入测试**

Create `tests/unit/__init__.py` as an empty file and create `tests/unit/test_optimization_types.py`:

```python
import unittest

from dc_energy_opt.optimization.types import PendingFlexibleTask, WindowSolveState


class OptimizationTypeTests(unittest.TestCase):
    def test_window_state_preserves_energy_and_pending_tasks(self) -> None:
        task = PendingFlexibleTask(origin_hour=-1, remaining_cpu_pu=0.25)
        state = WindowSolveState(
            stored_energy_mwh=1.0,
            pending_flexible_tasks=(task,),
        )
        self.assertEqual(state.stored_energy_mwh, 1.0)
        self.assertEqual(state.pending_flexible_tasks, (task,))
```

- [ ] **Step 2：验证新模块尚不存在**

Run:

```powershell
conda run -n scip_env python -m unittest tests.unit.test_optimization_types -v
```

Expected: FAIL，缺少 `dc_energy_opt.optimization`。

- [ ] **Step 3：移动模型文件并抽取类型**

Run:

```powershell
New-Item -ItemType Directory -Force -Path 'dc_energy_opt\optimization' | Out-Null
git mv dc_energy_opt/model.py dc_energy_opt/optimization/window_model.py
git mv dc_energy_opt/rolling.py dc_energy_opt/optimization/rolling_day_ahead.py
```

Create `dc_energy_opt/optimization/types.py` with the exact definitions moved from `window_model.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PendingFlexibleTask:
    origin_hour: int
    remaining_cpu_pu: float


@dataclass(frozen=True)
class WindowSolveState:
    stored_energy_mwh: float
    pending_flexible_tasks: tuple[PendingFlexibleTask, ...]
```

Remove only these two dataclass definitions and the `dataclass` import from `window_model.py`.

- [ ] **Step 4：建立优化层公开接口并修复相对导入**

Create `dc_energy_opt/optimization/__init__.py`:

```python
from .rolling_day_ahead import ROLLING_CASES, run_rolling_day_ahead
from .types import PendingFlexibleTask, WindowSolveState
from .window_model import build_and_solve

__all__ = [
    "PendingFlexibleTask",
    "WindowSolveState",
    "build_and_solve",
    "ROLLING_CASES",
    "run_rolling_day_ahead",
]
```

Use these exact imports inside the moved files:

```python
# window_model.py
from ..config import Parameters
from .types import PendingFlexibleTask, WindowSolveState

# rolling_day_ahead.py
from ..config import Parameters
from ..data import HOUSTON_ENERGY_SCENARIO_COLUMNS
from .types import PendingFlexibleTask
from .window_model import build_and_solve
```

Update root exports and all test imports to `dc_energy_opt.optimization` paths.

- [ ] **Step 5：运行优化层测试和全量测试**

```powershell
conda run -n scip_env python -m unittest `
  tests.unit.test_optimization_types `
  tests.test_cost_optimization `
  tests.test_rolling_day_ahead -v
conda run -n scip_env python -m unittest discover -s tests -v
```

Expected: 全部通过，SOC、任务跨日和成本结果与基线一致。

- [ ] **Step 6：提交优化层拆分**

```powershell
git add -- dc_energy_opt run_first_version.py tests
git commit -m "拆分窗口模型与滚动调度"
```

## Task 4：拆分正式数据并归档 Phoenix/Qinghai

**Files:**

- Create: `dc_energy_opt/data/__init__.py`
- Create: `dc_energy_opt/data/workload.py`
- Create: `dc_energy_opt/data/energy.py`
- Delete after extraction: `dc_energy_opt/data.py`
- Move: `data/instance_usage_grouped_300_seconds_month.csv` → `data/workload/google_2019_28d_5min.csv`
- Move: `data/houston_2020_main_experiment_energy_scenario.csv` → `data/energy/houston_2020_may_hourly.csv`
- Create: `data/workload/README.md`
- Create: `data/energy/README.md`
- Create: `archive/__init__.py`
- Create: `archive/legacy_phoenix/__init__.py`
- Create: `archive/legacy_phoenix/legacy_energy_data.py`
- Move: two historical CSV files into `archive/legacy_phoenix/data/`
- Create: `archive/legacy_phoenix/tests/test_legacy_energy_data.py`
- Modify: `scripts/build_houston_2020_energy_scenario.py`
- Create: `tests/unit/test_workload_data.py`
- Create: `tests/unit/test_energy_data.py`

- [ ] **Step 1：写正式数据模块失败测试**

Create `tests/unit/test_energy_data.py`:

```python
import unittest
from pathlib import Path

from dc_energy_opt.config import Parameters
from dc_energy_opt.data.energy import load_houston_energy_scenario, paper_tou_tariff


class EnergyDataTests(unittest.TestCase):
    def test_committed_houston_file_has_exact_main_window(self) -> None:
        rows = load_houston_energy_scenario(
            Path("data/energy/houston_2020_may_hourly.csv"),
            Parameters(),
        )
        self.assertEqual(len(rows), 699)
        self.assertEqual(str(rows.iloc[0]["timestamp_lst"]), "2020-04-30 00:00:00")
        self.assertEqual(str(rows.iloc[-1]["timestamp_lst"]), "2020-05-29 02:00:00")

    def test_paper_tariff_preserves_exact_prices(self) -> None:
        periods, prices = paper_tou_tariff([0, 8, 9, 13, 18, 23])
        self.assertEqual(periods.tolist(), ["valley", "flat", "peak", "flat", "peak", "flat"])
        self.assertEqual(prices.tolist(), [0.1804, 0.4489, 0.7174, 0.4489, 0.7174, 0.4489])
```

Create `tests/unit/test_workload_data.py`:

```python
import unittest
from pathlib import Path

from dc_energy_opt.data.workload import load_and_prepare


class WorkloadDataTests(unittest.TestCase):
    def test_committed_google_file_aggregates_to_672_hours(self) -> None:
        raw, hourly, representative_day, stress_day = load_and_prepare(
            Path("data/workload/google_2019_28d_5min.csv")
        )
        self.assertEqual(len(raw), 8064)
        self.assertEqual(len(hourly), 672)
        self.assertEqual(representative_day, 8)
        self.assertEqual(stress_day, 28)
```

- [ ] **Step 2：验证新路径与模块尚不存在**

```powershell
conda run -n scip_env python -m unittest `
  tests.unit.test_energy_data tests.unit.test_workload_data -v
```

Expected: FAIL，缺少正式数据子包或新数据路径。

- [ ] **Step 3：移动正式数据并验证哈希不变**

```powershell
New-Item -ItemType Directory -Force -Path 'data\workload','data\energy' | Out-Null
git mv data/instance_usage_grouped_300_seconds_month.csv data/workload/google_2019_28d_5min.csv
git mv data/houston_2020_main_experiment_energy_scenario.csv data/energy/houston_2020_may_hourly.csv
Get-FileHash -Algorithm SHA256 -LiteralPath `
  'data\workload\google_2019_28d_5min.csv', `
  'data\energy\houston_2020_may_hourly.csv' |
  Format-Table Path,Hash -AutoSize
```

Expected: 两个哈希分别等于 Task 1 记录值。

- [ ] **Step 4：抽取正式数据函数并重命名误导性电价函数**

Move `load_and_prepare` unchanged into `dc_energy_opt/data/workload.py`.

Move `HOUSTON_ENERGY_SCENARIO_COLUMNS` and `load_houston_energy_scenario` into `dc_energy_opt/data/energy.py`. Rename `_qinghai_tou` exactly to:

```python
def paper_tou_tariff(hours: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hour_values = np.asarray(hours, dtype=int)
    valley = (hour_values >= 0) & (hour_values < 8)
    peak = ((hour_values >= 9) & (hour_values < 13)) | (
        (hour_values >= 18) & (hour_values < 23)
    )
    periods = np.select([valley, peak], ["valley", "peak"], default="flat")
    prices = np.select([valley, peak], [0.1804, 0.7174], default=0.4489)
    return periods, prices
```

Update `load_houston_energy_scenario` to call `paper_tou_tariff`.

Before removing the legacy 24-hour loader, replace the `CostOptimizationModelTests.setUpClass` scenario construction with the formal Houston data:

```python
cls.scenario = load_houston_energy_scenario(
    PROJECT_ROOT / "data" / "energy" / "houston_2020_may_hourly.csv",
    cls.params,
).iloc[24:48].reset_index(drop=True)
```

Update `tests/test_rolling_day_ahead.py` to import and call `paper_tou_tariff` instead of `_qinghai_tou`.

Create `dc_energy_opt/data/__init__.py`:

```python
from .energy import (
    HOUSTON_ENERGY_SCENARIO_COLUMNS,
    load_houston_energy_scenario,
    paper_tou_tariff,
)
from .workload import load_and_prepare

__all__ = [
    "HOUSTON_ENERGY_SCENARIO_COLUMNS",
    "load_houston_energy_scenario",
    "paper_tou_tariff",
    "load_and_prepare",
]
```

- [ ] **Step 5：归档历史实现和测试**

Move these exact identifiers from the old `dc_energy_opt/data.py` into `archive/legacy_phoenix/legacy_energy_data.py`:

```text
ENERGY_SCENARIO_COLUMNS
WEATHER_SOURCE_COLUMNS
load_phoenix_weather_source
solar_available_power_mw
wind_available_power_mw
build_provisional_energy_scenario
load_energy_scenario
```

The archive module imports:

```python
from dc_energy_opt.config import Parameters
from dc_energy_opt.data.energy import paper_tou_tariff
```

Move `ProvisionalEnergyScenarioTests` and its required Houston-independent helpers from `tests/test_cost_optimization.py` into `archive/legacy_phoenix/tests/test_legacy_energy_data.py`. Update its imports to `archive.legacy_phoenix.legacy_energy_data`.

Run:

```powershell
New-Item -ItemType Directory -Force -Path 'archive\legacy_phoenix\data','archive\legacy_phoenix\tests' | Out-Null
git mv data/phoenix_nasa_power_20190501_20190528_hourly.csv archive/legacy_phoenix/data/phoenix_nasa_power_20190501_20190528_hourly.csv
git mv data/provisional_phoenix_weather_qinghai_tou_scenario.csv archive/legacy_phoenix/data/provisional_phoenix_weather_qinghai_tou_scenario.csv
```

Delete `dc_energy_opt/data.py` only after every exact identifier above exists in its new module.

- [ ] **Step 6：更新生成脚本与数据说明**

Rename the script:

```powershell
git mv scripts/build_houston_2020_energy_scenario.py scripts/prepare_houston_2020_energy.py
```

Use these imports:

```python
from dc_energy_opt.config import Parameters
from dc_energy_opt.data.energy import HOUSTON_ENERGY_SCENARIO_COLUMNS, paper_tou_tariff
```

Set its default output to `data/energy/houston_2020_may_hourly.csv`. Add the exact four data columns and time coverage to `data/energy/README.md`, and the exact four workload columns and 8,064-row/5-minute interpretation to `data/workload/README.md`.

- [ ] **Step 7：验证正式与归档数据测试**

```powershell
conda run -n scip_env python -m unittest `
  tests.unit.test_energy_data tests.unit.test_workload_data -v
conda run -n scip_env python -m unittest discover `
  -s archive/legacy_phoenix/tests -t . -v
conda run -n scip_env python -m unittest discover -s tests -v
```

Expected: 正式数据测试、归档历史测试和默认测试全部通过；默认测试不发现归档测试。

- [ ] **Step 8：提交数据分层与归档**

```powershell
git add -- dc_energy_opt/data archive data scripts tests
git commit -m "分层正式数据并归档历史场景"
```

## Task 5：抽取指标模块并拆分绘图包

**Files:**

- Create: `dc_energy_opt/reporting/__init__.py`
- Create: `dc_energy_opt/reporting/metrics.py`
- Move: `dc_energy_opt/reporting.py` → `dc_energy_opt/reporting/plots.py`
- Modify: `dc_energy_opt/optimization/rolling_day_ahead.py`
- Create: `tests/unit/test_metrics.py`
- Create: `tests/unit/test_plots.py`

- [ ] **Step 1：为成本汇总写失败测试**

Create `tests/unit/test_metrics.py`:

```python
import unittest

import pandas as pd

from dc_energy_opt.reporting.metrics import summarize_costs


class MetricTests(unittest.TestCase):
    def test_summarize_costs_adds_exact_hourly_components(self) -> None:
        rows = pd.DataFrame({
            "hourly_grid_purchase_cost_cny": [10.0, 20.0],
            "hourly_solar_om_cost_cny": [1.0, 2.0],
            "hourly_wind_om_cost_cny": [3.0, 4.0],
            "hourly_battery_om_cost_cny": [5.0, 6.0],
            "hourly_battery_degradation_cost_cny": [7.0, 8.0],
            "hourly_operating_cost_cny": [26.0, 40.0],
        })
        self.assertEqual(summarize_costs(rows)["operating_cost_cny"], 66.0)
```

- [ ] **Step 2：验证指标模块尚不存在**

```powershell
conda run -n scip_env python -m unittest tests.unit.test_metrics -v
```

Expected: FAIL，缺少 `dc_energy_opt.reporting.metrics`。

- [ ] **Step 3：创建指标模块并移动现有计算**

Create `dc_energy_opt/reporting/metrics.py` with:

```python
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..config import Parameters
from ..optimization.types import PendingFlexibleTask, WindowSolveState


COST_COLUMNS = {
    "grid_purchase_cost_cny": "hourly_grid_purchase_cost_cny",
    "solar_om_cost_cny": "hourly_solar_om_cost_cny",
    "wind_om_cost_cny": "hourly_wind_om_cost_cny",
    "battery_om_cost_cny": "hourly_battery_om_cost_cny",
    "battery_degradation_cost_cny": "hourly_battery_degradation_cost_cny",
    "operating_cost_cny": "hourly_operating_cost_cny",
}


def summarize_costs(rows: pd.DataFrame) -> dict[str, float]:
    return {
        metric_name: float(rows[column_name].sum())
        for metric_name, column_name in COST_COLUMNS.items()
    }
```

Create the daily helper with this exact interface:

```python
def summarize_daily_window(
    *,
    case_name: str,
    day_number: int,
    result: pd.DataFrame,
    stored_energy_mwh: float,
    state: WindowSolveState,
    committed_energy_mwh: float | None,
    terminal_energy_mwh: float | None,
    initial_energy_mwh: float,
    carry_in_tasks: tuple[PendingFlexibleTask, ...],
    window_metrics: dict[str, object],
    is_final_day: bool,
) -> dict[str, object]:
    day_costs = summarize_costs(result.iloc[:24])
    tail_cost = (
        float(result.iloc[24:]["hourly_operating_cost_cny"].sum())
        if is_final_day
        else 0.0
    )
    return {
        "case": case_name,
        "day": day_number,
        **day_costs,
        "settlement_tail_operating_cost_cny": tail_cost,
        "initial_stored_energy_mwh": stored_energy_mwh,
        "committed_end_stored_energy_mwh": state.stored_energy_mwh,
        "coordinated_committed_stored_energy_mwh": (
            committed_energy_mwh
            if committed_energy_mwh is not None
            else initial_energy_mwh
        ),
        "window_terminal_stored_energy_mwh": (
            terminal_energy_mwh
            if terminal_energy_mwh is not None
            else initial_energy_mwh
        ),
        "actual_window_terminal_stored_energy_mwh": float(
            result.loc[26, "stored_energy_end_mwh"]
        ),
        "carry_in_task_cpu_pu_hours": float(
            sum(task.remaining_cpu_pu for task in carry_in_tasks)
        ),
        "carry_out_task_cpu_pu_hours": float(
            sum(
                task.remaining_cpu_pu
                for task in state.pending_flexible_tasks
            )
        ),
        "committed_task_delay_cpu_hours": window_metrics[
            "committed_task_delay_cpu_hours"
        ],
        "committed_maximum_task_delay_h": window_metrics[
            "committed_maximum_task_delay_h"
        ],
    }
```

Create the aggregate helper with this exact interface:

```python
def summarize_case_metrics(
    *,
    hourly: pd.DataFrame,
    workload: np.ndarray,
    params: Parameters,
    case_name: str,
    enable_shift: bool,
    enable_storage: bool,
    warmup_carry_in_cpu: float,
    warmup_metrics: dict[str, object] | None,
    coordination_metrics: dict[str, object] | None,
    rolling_metrics: list[dict[str, object]],
) -> dict[str, object]:
```

Move the current aggregate statements beginning with `costs = _cost_summary(hourly)` and ending with `return hourly, metrics, daily` into this helper without changing a metric name or formula. Replace `_cost_summary` with `summarize_costs`; replace the final rolling return with `return metrics`; keep the five-cost `math.isclose` check inside the helper. In `run_rolling_day_ahead`, call both helpers with the exact local values and retain `return hourly, metrics, daily`.

- [ ] **Step 4：移动绘图模块并采用新文件名**

```powershell
New-Item -ItemType Directory -Force -Path 'dc_energy_opt\reporting' | Out-Null
git mv dc_energy_opt/reporting.py dc_energy_opt/reporting/plots.py
```

Replace `PLOT_FILENAMES` exactly with:

```python
PLOT_FILENAMES = [
    "power_dispatch.png",
    "compute_schedule.png",
    "battery_dispatch.png",
    "renewable_dispatch.png",
    "cost_breakdown.png",
]
```

Create `dc_energy_opt/reporting/__init__.py`:

```python
from .metrics import summarize_case_metrics, summarize_costs, summarize_daily_window
from .plots import PLOT_FILENAMES, make_plots, software_versions

__all__ = [
    "summarize_costs",
    "summarize_daily_window",
    "summarize_case_metrics",
    "PLOT_FILENAMES",
    "make_plots",
    "software_versions",
]
```

- [ ] **Step 5：拆分现有报告测试**

Move plot-specific tests from `tests/test_runner_outputs.py` into `tests/unit/test_plots.py`, including zero-input, invalid physical semantics, numeric-column, nonnegative-cost and boundary-rendering tests. Update imports to `dc_energy_opt.reporting.plots`.

- [ ] **Step 6：运行指标、绘图和滚动测试**

```powershell
conda run -n scip_env python -m unittest `
  tests.unit.test_metrics `
  tests.unit.test_plots `
  tests.test_rolling_day_ahead -v
conda run -n scip_env python -m unittest discover -s tests -v
```

Expected: 所有成本字段、图像校验、SOC 和跨日任务测试通过。

- [ ] **Step 7：提交报告层拆分**

```powershell
git add -- dc_energy_opt/reporting dc_energy_opt/optimization tests
git commit -m "拆分指标计算与结果绘图"
```

## Task 6：实现分层 LP 路径

**Files:**

- Modify: `dc_energy_opt/optimization/window_model.py`
- Modify: `dc_energy_opt/optimization/rolling_day_ahead.py`
- Modify: window-model and rolling tests

- [ ] **Step 1：写 LP 路径失败测试**

Add `test_lp_files_use_stage_names_inside_window_directory` to `tests/unit/test_window_model.py`. Reuse that class's existing `self.solve` helper after adding optional parameter `lp_output_dir: Path | None = None`; the helper passes `lp_output_dir or self.output_dir` into `build_and_solve`. The test body is:

```python
def test_lp_files_use_stage_names_inside_window_directory(self) -> None:
    lp_output_dir = self.output_dir / "day_01"
    self.solve(
        case_name="lp_path_layout",
        lp_output_dir=lp_output_dir,
    )
    self.assertTrue((lp_output_dir / "stage_1_cost.lp").is_file())
    self.assertTrue((lp_output_dir / "stage_2_delay.lp").is_file())
    self.assertFalse((lp_output_dir / "lp_path_layout_primary.lp").exists())
    self.assertFalse((lp_output_dir / "lp_path_layout_secondary.lp").exists())
```

- [ ] **Step 2：验证旧平铺命名导致测试失败**

Run:

```powershell
conda run -n scip_env python -m unittest `
  tests.unit.test_window_model.CostOptimizationModelTests.test_lp_files_use_stage_names_inside_window_directory -v
```

Expected: FAIL，`stage_1_cost.lp` 不存在。

- [ ] **Step 3：修改窗口模型 LP 接口**

Rename parameter `output_dir` to `lp_output_dir` in `build_and_solve`, then replace the two write calls with:

```python
lp_output_dir = Path(lp_output_dir)
lp_output_dir.mkdir(parents=True, exist_ok=True)
model.writeProblem(str(lp_output_dir / "stage_1_cost.lp"))
# primary solve remains unchanged
model.writeProblem(str(lp_output_dir / "stage_2_delay.lp"))
```

Keep `case_name` for SCIP model naming, result rows and error messages.

- [ ] **Step 4：让滚动层构造精确窗口目录**

Rename `run_rolling_day_ahead` parameter `output_dir` to `model_output_dir`. Pass these exact child directories:

```python
model_output_dir / "warmup"
model_output_dir / "soc_coordination"
model_output_dir / f"day_{day_number:02d}"
```

The experiment layer will pass `paths.models / case_name` as `model_output_dir`.

- [ ] **Step 5：验证文件总数和层次**

Run rolling tests and assert storage/shift cases contain `warmup` and/or `soc_coordination` only when applicable. For the 28-day four-case run, assert exactly 232 `.lp` files recursively:

```python
self.assertEqual(len(list(paths.models.rglob("*.lp"))), 232)
```

- [ ] **Step 6：提交 LP 分层**

```powershell
git add -- dc_energy_opt/optimization tests
git commit -m "按算例与窗口分层保存 LP"
```

## Task 7：抽取事务发布与 Houston 实验模块

**Files:**

- Create: `dc_energy_opt/experiments/__init__.py`
- Create: `dc_energy_opt/experiments/artifacts.py`
- Create: `dc_energy_opt/experiments/houston_2020.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_artifact_publishing.py`
- Create: `tests/integration/test_houston_2020_experiment.py`
- Modify: `run_first_version.py`

- [ ] **Step 1：写输出布局和回滚失败测试**

Create `tests/integration/test_artifact_publishing.py` with tests that require:

```python
with staged_run_directory(final_output_dir) as paths:
    self.assertEqual(paths.inputs, paths.root / "inputs")
    self.assertEqual(paths.results, paths.root / "results")
    self.assertEqual(paths.figures, paths.root / "figures")
    self.assertEqual(paths.models, paths.root / "models")
    (paths.results / "marker.txt").write_text("new", encoding="utf-8")
```

After normal exit, assert the new tree is published. In a second test, raise `RuntimeError("stop")` inside the context and assert the previous final tree remains byte-for-byte unchanged and no staging directory remains.

- [ ] **Step 2：验证实验包尚不存在**

```powershell
conda run -n scip_env python -m unittest `
  tests.integration.test_artifact_publishing -v
```

Expected: FAIL，缺少 `dc_energy_opt.experiments.artifacts`。

- [ ] **Step 3：创建分层路径对象和事务发布**

Create `dc_energy_opt/experiments/artifacts.py` with this complete implementation:

```python
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import uuid4


@dataclass(frozen=True)
class RunPaths:
    root: Path
    inputs: Path
    results: Path
    figures: Path
    models: Path


@contextmanager
def staged_run_directory(final_output_dir: Path) -> Iterator[RunPaths]:
    """Build a complete run tree beside final_output_dir and publish atomically."""
    final_path = Path(final_output_dir).resolve(strict=False)
    parent = final_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging_path = Path(
        tempfile.mkdtemp(
            prefix=f".{final_path.name}-staging-",
            dir=parent,
        )
    ).resolve()
    if staging_path.parent != parent.resolve():
        raise RuntimeError("临时输出目录不在正式输出目录的同级目录中。")

    paths = RunPaths(
        root=staging_path,
        inputs=staging_path / "inputs",
        results=staging_path / "results",
        figures=staging_path / "figures",
        models=staging_path / "models",
    )
    for directory in (
        paths.inputs,
        paths.results,
        paths.figures,
        paths.models,
    ):
        directory.mkdir()

    backup_path = parent / f".{final_path.name}-backup-{uuid4().hex}"
    try:
        yield paths
        if final_path.exists():
            os.replace(final_path, backup_path)
        try:
            os.replace(staging_path, final_path)
        except BaseException as publish_error:
            if backup_path.exists():
                try:
                    os.replace(backup_path, final_path)
                except BaseException as restore_error:
                    raise RuntimeError(
                        f"发布失败且旧结果恢复失败；备份保留在 {backup_path}: "
                        f"{restore_error}"
                    ) from publish_error
            raise
        if backup_path.exists():
            shutil.rmtree(backup_path)
    finally:
        if staging_path.exists():
            shutil.rmtree(staging_path)
```

The publication tests must patch `os.replace` and `shutil.rmtree` at the exact failure points already covered by the existing rollback tests. Recursive removal is permitted only for the generated sibling staging or backup path after the resolved-parent check above.

- [ ] **Step 4：定义实验返回对象**

Create in `dc_energy_opt/experiments/houston_2020.py`:

```python
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ExperimentResult:
    hourly_dispatch: pd.DataFrame
    daily_metrics: pd.DataFrame
    case_metrics: pd.DataFrame
    metadata: dict[str, object]
```

Expose this exact function:

```python
def run_houston_2020_experiment(
    *,
    workload_data: Path,
    energy_data: Path,
    output_dir: Path,
    params: Parameters | None = None,
    show_solver_log: bool = False,
) -> ExperimentResult:
```

- [ ] **Step 5：移动主实验流程**

Move the current `main()` workflow from input loading through metadata construction into `run_houston_2020_experiment`. Write exact outputs to:

```python
paths.inputs / "google_2019_28d_5min.csv"
paths.inputs / "houston_2020_may_hourly.csv"
paths.inputs / "aligned_28d_hourly.csv"
paths.results / "hourly_workload.csv"
paths.results / "hourly_dispatch.csv"
paths.results / "daily_metrics.csv"
paths.results / "case_metrics.csv"
paths.figures
paths.models / case_name
paths.root / "run_metadata.json"
```

Preserve the current four cases, cost-baseline formula, metadata values and result columns.

- [ ] **Step 6：建立实验包公开接口**

Create `dc_energy_opt/experiments/__init__.py`:

```python
from .artifacts import RunPaths, staged_run_directory
from .houston_2020 import ExperimentResult, run_houston_2020_experiment

__all__ = [
    "RunPaths",
    "staged_run_directory",
    "ExperimentResult",
    "run_houston_2020_experiment",
]
```

- [ ] **Step 7：迁移事务发布测试并运行集成测试**

Move all current publish, rollback, source-collision and staging-cleanup tests from `tests/test_runner_outputs.py` into `tests/integration/test_artifact_publishing.py`. Adapt them to whole-directory publishing; preserve readonly cleanup and restore-failure coverage.

Run:

```powershell
conda run -n scip_env python -m unittest `
  tests.integration.test_artifact_publishing `
  tests.integration.test_houston_2020_experiment -v
```

Expected: 分层输出、正常发布、失败回滚和完整 Houston 实验测试全部通过。

- [ ] **Step 8：提交实验与发布层**

```powershell
git add -- dc_energy_opt/experiments dc_energy_opt/optimization tests run_first_version.py
git commit -m "抽取主实验与事务化发布"
```

## Task 8：建立正式入口和旧入口兼容层

**Files:**

- Create: `run_day_ahead_experiment.py`
- Replace: `run_first_version.py`
- Create: `tests/integration/test_cli_entrypoints.py`

- [ ] **Step 1：写两个入口参数测试**

Create tests that patch `run_houston_2020_experiment` and assert the formal defaults are exactly:

```python
Path("data/workload/google_2019_28d_5min.csv")
Path("data/energy/houston_2020_may_hourly.csv")
Path("outputs/houston_2020_main")
False
```

Add a compatibility test using exact old flags `--input`, `--energy-scenario`, `--output-dir`, `--show-scip-log`, and assert they produce the same `run_houston_2020_experiment` call as the formal flags.

- [ ] **Step 2：验证正式入口尚不存在**

```powershell
conda run -n scip_env python -m unittest `
  tests.integration.test_cli_entrypoints -v
```

Expected: FAIL，缺少 `run_day_ahead_experiment`。

- [ ] **Step 3：创建正式入口**

`run_day_ahead_experiment.py` must expose this complete parser:

```python
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="数据中心跨日确定性日前运行成本优化",
    )
    parser.add_argument(
        "--workload-data",
        type=Path,
        default=Path("data/workload/google_2019_28d_5min.csv"),
    )
    parser.add_argument(
        "--energy-data",
        type=Path,
        default=Path("data/energy/houston_2020_may_hourly.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/houston_2020_main"),
    )
    parser.add_argument("--show-solver-log", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = run_houston_2020_experiment(
        workload_data=args.workload_data,
        energy_data=args.energy_data,
        output_dir=args.output_dir,
        show_solver_log=args.show_solver_log,
    )
    print(json.dumps(result.metadata, ensure_ascii=True, indent=2))
    print("\nOperating cost metrics:")
    print(result.case_metrics.to_string(index=False))
```

The parser defines only these formal flags: `--workload-data`, `--energy-data`, `--output-dir`, and `--show-solver-log`.

- [ ] **Step 4：将旧入口缩减为参数转换层**

`run_first_version.py` imports only standard-library CLI modules and `run_day_ahead_experiment.main`. It converts exact legacy flags to formal flags, prints:

```text
run_first_version.py 已迁移，请改用 run_day_ahead_experiment.py。
```

It must not import `Parameters`, `build_and_solve`, reporting internals or artifact helpers.

- [ ] **Step 5：运行入口测试**

```powershell
conda run -n scip_env python -m unittest `
  tests.integration.test_cli_entrypoints -v
conda run -n scip_env python -m unittest discover -s tests -v
```

Expected: 新旧参数映射测试和全量测试全部通过。

- [ ] **Step 6：提交入口迁移**

```powershell
git add -- run_day_ahead_experiment.py run_first_version.py tests
git commit -m "建立正式实验入口与兼容层"
```

## Task 9：按职责重组全部测试

**Files:**

- Create/modify: `tests/unit/test_config.py`
- Create/modify: `tests/unit/test_workload_data.py`
- Create/modify: `tests/unit/test_energy_data.py`
- Create/modify: `tests/unit/test_window_model.py`
- Create/modify: `tests/unit/test_metrics.py`
- Create/modify: `tests/unit/test_plots.py`
- Create/modify: `tests/integration/test_rolling_day_ahead.py`
- Create/modify: `tests/integration/test_houston_2020_experiment.py`
- Create/modify: `tests/integration/test_artifact_publishing.py`
- Create/modify: `tests/integration/test_cli_entrypoints.py`
- Delete after migration: four old top-level test modules

- [ ] **Step 1：建立测试职责映射**

Move existing classes and methods by exact responsibility:

```text
ParameterScaleTests                 -> tests/unit/test_config.py
HoustonEnergyScenarioTests          -> tests/unit/test_energy_data.py
CostOptimizationModelTests          -> tests/unit/test_window_model.py
RollingDayAheadTests                -> tests/integration/test_rolling_day_ahead.py
plot validation tests               -> tests/unit/test_plots.py
publish and rollback tests          -> tests/integration/test_artifact_publishing.py
default full-run tests              -> tests/integration/test_houston_2020_experiment.py
entrypoint export and CLI tests      -> tests/integration/test_cli_entrypoints.py
```

Keep every assertion that validates current Houston behavior. Historical Phoenix tests remain only under `archive/legacy_phoenix/tests/`.

- [ ] **Step 2：删除已清空的旧测试文件**

Delete only after every test method has an exact destination:

```text
tests/test_cost_optimization.py
tests/test_refactor_regression.py
tests/test_rolling_day_ahead.py
tests/test_runner_outputs.py
```

- [ ] **Step 3：验证默认发现边界**

```powershell
conda run -n scip_env python -m unittest discover -s tests -t . -v
conda run -n scip_env python -m unittest discover `
  -s archive/legacy_phoenix/tests -t . -v
```

Expected: 默认命令只运行正式项目测试；第二条命令单独运行归档测试；两组均为 `OK`。

- [ ] **Step 4：提交测试重组**

```powershell
git add -- tests archive/legacy_phoenix/tests
git commit -m "按模块职责重组测试"
```

## Task 10：整理文档与根目录说明

**Files:**

- Create: `README.md`
- Create: `docs/deterministic_day_ahead_model.md`
- Create: `docs/houston_2020_experiment.md`
- Modify: `docs/repository_reorganization_design.md`
- Modify: `docs/repository_reorganization_implementation.md`
- Delete: `FIRST_VERSION_GUIDE.md`
- Delete: `docs/superpowers/specs/2026-07-30-deterministic-day-ahead-design.md`
- Delete: `docs/superpowers/plans/2026-07-30-deterministic-day-ahead-implementation.md`

- [ ] **Step 1：写根目录 README**

`README.md` must contain these exact sections:

```markdown
# Data Center Energy Optimization

## 项目简介
## 主实验
## 环境安装
## 快速运行
## 输出目录
## 测试
## 文档导航
```

Quick-run command must use `run_day_ahead_experiment.py`; the compatibility entry appears only in one migration note.

- [ ] **Step 2：迁移模型文档**

Create `docs/deterministic_day_ahead_model.md` from the current guide and design content. Preserve the five-cost objective, two-stage lexicographic optimization, 6.6 MW grid limit, 2 MWh/0.5 MW storage, SOC constraints, 24+3 rolling horizon, warmup, cross-day tasks and terminal settlement accounting.

- [ ] **Step 3：迁移实验文档**

Create `docs/houston_2020_experiment.md` with exact formal input paths, 699-hour coverage, four cases, command-line flags, output tree, result-column descriptions, Houston/exogenous-price interpretation and reproducibility source commit.

- [ ] **Step 4：删除重复旧文档**

Run exact reference search first:

```powershell
rg -n "FIRST_VERSION_GUIDE|docs/superpowers" . -g '!outputs/**' -g '!.git/**'
```

Update valid references, then delete only the three listed old Markdown files. Remove empty `docs/superpowers/plans`, `docs/superpowers/specs`, and `docs/superpowers` directories.

- [ ] **Step 5：验证文档无旧正式名称**

```powershell
rg -n "scip_first_version|run_first_version.py|day_ahead_deterministic|instance_usage_grouped_300_seconds_month|houston_2020_main_experiment_energy_scenario" `
  README.md docs data dc_energy_opt scripts tests
```

Expected: `run_first_version.py` 只在迁移说明中出现；其余旧正式名称无匹配。归档 README 可出现 Phoenix/Qinghai 名称。

- [ ] **Step 6：提交文档整理**

```powershell
git add -- README.md docs FIRST_VERSION_GUIDE.md
git commit -m "统一项目文档与运行说明"
```

## Task 11：运行新旧入口并执行结果等价检查

**Files:**

- Generate: `outputs/houston_2020_main/`
- Compare: `outputs/repository_reorganization_baseline/`
- Verify: entire repository

- [ ] **Step 1：运行正式入口**

```powershell
conda run -n scip_env python run_day_ahead_experiment.py
```

Expected: 四组算例全部为 `optimal`；默认输出根目录只包含 `inputs/`、`results/`、`figures/`、`models/` 和 `run_metadata.json`。

- [ ] **Step 2：核对正式输出数量**

```powershell
$out = Resolve-Path -LiteralPath 'outputs\houston_2020_main'
"hourly_rows=$((Import-Csv -LiteralPath (Join-Path $out 'results\hourly_dispatch.csv')).Count)"
"daily_rows=$((Import-Csv -LiteralPath (Join-Path $out 'results\daily_metrics.csv')).Count)"
"lp_count=$(@(Get-ChildItem -LiteralPath (Join-Path $out 'models') -Recurse -File -Filter '*.lp').Count)"
"png_count=$(@(Get-ChildItem -LiteralPath (Join-Path $out 'figures') -File -Filter '*.png').Count)"
Get-ChildItem -LiteralPath $out | Select-Object Name,PSIsContainer
```

Expected:

```text
hourly_rows=2700
daily_rows=112
lp_count=232
png_count=5
```

- [ ] **Step 3：数值比较新旧结果**

Create `scripts/verify_reorganization_equivalence.py`. It loads:

```text
outputs/repository_reorganization_baseline/hourly_case_results.csv
outputs/houston_2020_main/results/hourly_dispatch.csv
outputs/repository_reorganization_baseline/daily_case_metrics.csv
outputs/houston_2020_main/results/daily_metrics.csv
outputs/repository_reorganization_baseline/case_metrics.csv
outputs/houston_2020_main/results/case_metrics.csv
```

Use this complete comparison core:

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


BASELINE = Path("outputs/repository_reorganization_baseline")
CURRENT = Path("outputs/houston_2020_main/results")
TIMING_COLUMNS = {
    "solve_time_s",
    "rolling_solve_time_s",
    "warmup_solve_time_s",
    "soc_coordination_solve_time_s",
}


def compare_csv(old_name: str, new_name: str) -> None:
    old = pd.read_csv(BASELINE / old_name)
    new = pd.read_csv(CURRENT / new_name)
    if list(old.columns) != list(new.columns):
        raise AssertionError(f"column mismatch: {old_name} vs {new_name}")
    if len(old) != len(new):
        raise AssertionError(f"row mismatch: {old_name} vs {new_name}")
    for column in old.columns:
        if column in TIMING_COLUMNS:
            values = new[column].to_numpy(dtype=float)
            if not np.isfinite(values).all() or (values < 0.0).any():
                raise AssertionError(f"invalid timing column: {column}")
        elif pd.api.types.is_numeric_dtype(old[column]):
            np.testing.assert_allclose(
                old[column].to_numpy(dtype=float),
                new[column].to_numpy(dtype=float),
                rtol=0.0,
                atol=1e-9,
                err_msg=column,
            )
        elif not old[column].equals(new[column]):
            raise AssertionError(f"value mismatch: {column}")


def main() -> None:
    compare_csv("hourly_case_results.csv", "hourly_dispatch.csv")
    compare_csv("daily_case_metrics.csv", "daily_metrics.csv")
    compare_csv("case_metrics.csv", "case_metrics.csv")
    print("reorganization result equivalence passed")


if __name__ == "__main__":
    main()
```

Run:

```powershell
conda run -n scip_env python scripts/verify_reorganization_equivalence.py
```

Expected: `reorganization result equivalence passed`.

- [ ] **Step 4：运行旧兼容入口到独立目录**

```powershell
conda run -n scip_env python run_first_version.py `
  --output-dir outputs/houston_2020_compatibility_check
```

Expected: 先打印迁移提示，再生成与正式入口数值一致的分层输出。

- [ ] **Step 5：安全移除旧生成目录**

Resolve and verify these exact generated paths are under the repository `outputs` directory:

```powershell
$outputsRoot = (Resolve-Path -LiteralPath 'outputs').Path
$oldOutput = (Resolve-Path -LiteralPath 'outputs\day_ahead_deterministic').Path
if (-not $oldOutput.StartsWith($outputsRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw "旧输出目录不在 outputs 下"
}
Remove-Item -LiteralPath $oldOutput -Recurse -Force
```

Expected: 只删除可由旧入口重新生成的 `outputs/day_ahead_deterministic`。正式输入数据和新输出保持不变。

- [ ] **Step 6：运行完整验证**

```powershell
conda run -n scip_env python -m unittest discover -s tests -t . -v
conda run -n scip_env python -m unittest discover `
  -s archive/legacy_phoenix/tests -t . -v
conda run -n scip_env python -m compileall -q `
  dc_energy_opt scripts run_day_ahead_experiment.py run_first_version.py
conda run -n scip_env python -m pip check
git diff --check HEAD
```

Expected: 两组测试均为 `OK`，编译无输出，依赖检查输出 `No broken requirements found.`，差异检查无空白错误。

- [ ] **Step 7：静态确认旧包与旧路径只存在于归档或迁移说明**

```powershell
rg -n "scip_first_version|day_ahead_deterministic|instance_usage_grouped_300_seconds_month|houston_2020_main_experiment_energy_scenario" `
  dc_energy_opt run_day_ahead_experiment.py run_first_version.py scripts tests README.md docs data
```

Expected: 正式代码、测试、数据说明和当前实验文档没有旧包导入或旧默认路径；旧入口名称只出现在兼容说明和兼容入口自身。

- [ ] **Step 8：提交最终清理与验证状态**

```powershell
git add -- dc_energy_opt data archive scripts tests README.md docs `
  run_day_ahead_experiment.py run_first_version.py
git diff --cached --name-status
git commit -m "完成项目结构与命名重构"
```

Do not push. Do not rename the current workspace root. Do not rename the GitHub repository.

## Task 12：最终人工审查

**Files:**

- Review: all changed tracked files
- Review: `outputs/houston_2020_main/`

- [ ] **Step 1：审查职责边界**

Confirm:

- CLI does not construct models or manage rollback;
- optimization modules do not copy input files or draw images;
- data modules do not write outputs;
- metrics do not draw plots;
- archive modules are not exported by `dc_energy_opt`;
- `scip_first_version/` no longer exists.

- [ ] **Step 2：审查正式目录形态**

Run:

```powershell
rg --files -g '!outputs/**' -g '!.git/**' | Sort-Object
git status --short
git log -8 --oneline --decorate
```

Expected: 正式目录与设计文档一致；只有明确保留的生成物不受 Git 跟踪；实施提交均为本地提交且没有推送。

- [ ] **Step 3：记录最终结果**

In the final handoff, report:

- formal package and entry names;
- formal data paths;
- output tree and artifact counts;
- test counts for formal and archive suites;
- numerical equivalence result;
- local commit list;
- explicit statement that workspace root and GitHub repository were not renamed or pushed.
