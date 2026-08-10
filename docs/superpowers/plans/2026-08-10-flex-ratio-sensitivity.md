# Flex Ratio Cost Sensitivity Implementation Plan

> **实施方式：** 在当前 Git 工作区按清单直接实现并验证。

**Goal:** 在固定 28 天输入、能源系统和最大时移时长的前提下，扫描 `flex_ratio`，量化时移在无储能与有储能场景中的总成本价值、节省率和边际节省。

**Architecture:** 新增独立敏感性实验入口，直接复用 `run_rolling_day_ahead`。它以 `renewables_only` 与 `renewables_storage` 的零时移结果作为两组基准，再在 `renewables_shift` 与 `joint` 中按比例求解。结果表只保存每次完整 28 天求解的汇总指标；绘图函数读取结果表输出总成本、节省率和边际节省三张图。

**Tech Stack:** Python、pandas、NumPy、Pillow、SCIP、unittest。

---

## 已确认的分析口径

- 主扫描比例严格为 `0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0`；`0.3` 保留在扫描点中。
- 除 `flex_ratio` 外，`Parameters` 的所有字段固定；其中 `max_delay_h=3`、`primary_cost_tolerance_cny=0.01`、`relative_gap=1e-6` 不变。
- 输入固定为 `data/workload/google_2019_28d_5min.csv` 与 `data/energy/houston_2020_may_hourly.csv`，即 24 小时预热、672 小时分析期和 3 小时结算尾段。
- 对 `renewables_shift`，`flex_ratio=0.0` 直接复用 `renewables_only`；对 `joint`，`flex_ratio=0.0` 直接复用 `renewables_storage`。
- 主成本严格使用 `operating_cost_cny`；实现时验证其等于 `analysis_operating_cost_cny + settlement_tail_operating_cost_cny`。
- 边际节省按相邻比例的总成本差除以比例差计算；零时移点的边际节省为空值。
- 饱和判定写入结果表：从某比例开始，后续所有边际节省均位于 0 与该场景最大正边际节省的 10% 之间；发生成本反弹时不判定为饱和。
- 若需要局部加密，命令行可显式输入包含 5 个百分点点位的比例序列；默认 10 个百分点扫描保持不变。
- `optimal` 与模型内部已接受的 `gaplimit`（相对间隙满足 `relative_gap=1e-6`）均可发布，结果表保留原始 `status`；其他状态停止发布。

## 输出契约

默认输出根目录为 `outputs/houston_2020_flex_ratio_sensitivity/`。

```text
results/flex_ratio_sensitivity.csv
figures/flex_ratio_total_cost.png
figures/flex_ratio_cost_savings.png
figures/flex_ratio_marginal_savings.png
models/<scenario>/ratio_<percent>/stage_1_cost.lp
models/<scenario>/ratio_<percent>/stage_2_delay.lp
run_metadata.json
```

结果表每行对应一个“场景 × 时移比例”，列严格为：

```text
scenario,baseline_case,flex_ratio,status,
analysis_operating_cost_cny,settlement_tail_operating_cost_cny,
operating_cost_cny,baseline_operating_cost_cny,
cost_savings_cny,cost_savings_pct,
marginal_cost_savings_cny_per_flex_ratio,
total_task_delay_cpu_hours,average_flexible_task_delay_h,
maximum_task_delay_h,saturation_onset
```

`saturation_onset` 为浮点比例：同一场景的每一行写入同一个饱和起点；若扫描范围内未出现饱和，则写入空值。

### Task 1: 创建汇总指标与比例校验

**Files:**
- Create: `dc_energy_opt/experiments/flex_ratio_sensitivity.py`
- Create: `tests/unit/test_flex_ratio_sensitivity.py`

- [x] **Step 1: 写入失败测试。**

```python
def test_build_sensitivity_summary_uses_total_cost_and_marginal_savings(self) -> None:
    metrics = build_sensitivity_summary(
        baseline_metrics={
            "renewables_shift": _metric("renewables_only", 100.0, 90.0, 10.0),
            "joint": _metric("renewables_storage", 80.0, 72.0, 8.0),
        },
        solved_metrics={
            "renewables_shift": {0.1: _metric("renewables_shift", 95.0, 86.0, 9.0)},
            "joint": {0.1: _metric("joint", 70.0, 63.0, 7.0)},
        },
        flex_ratios=(0.0, 0.1),
    )
    shift = metrics.loc[(metrics["scenario"] == "renewables_shift") & (metrics["flex_ratio"] == 0.1)].iloc[0]
    self.assertEqual(shift["operating_cost_cny"], 95.0)
    self.assertEqual(shift["cost_savings_cny"], 5.0)
    self.assertEqual(shift["cost_savings_pct"], 5.0)
    self.assertEqual(shift["marginal_cost_savings_cny_per_flex_ratio"], 50.0)
```

- [x] **Step 2: 验证测试失败。**

Run:

```powershell
conda run -n scip_env python -m unittest tests.unit.test_flex_ratio_sensitivity.FlexRatioSensitivityTests.test_build_sensitivity_summary_uses_total_cost_and_marginal_savings
```

Expected: FAIL，因为模块和函数尚不存在。

- [x] **Step 3: 实现最小汇总函数。**

```python
DEFAULT_FLEX_RATIOS = tuple(index / 10.0 for index in range(11))
SCENARIOS = (
    ("renewables_shift", "renewables_only", False),
    ("joint", "renewables_storage", True),
)

def validate_flex_ratios(flex_ratios: tuple[float, ...]) -> tuple[float, ...]:
    values = tuple(float(value) for value in flex_ratios)
    if not values or values[0] != 0.0:
        raise ValueError("flex_ratios 必须以 0.0 开始。")
    if any(not 0.0 <= value <= 1.0 for value in values):
        raise ValueError("flex_ratios 必须位于 0.0..1.0。")
    if tuple(sorted(set(values))) != values:
        raise ValueError("flex_ratios 必须严格递增且不重复。")
    return values
```

`build_sensitivity_summary` 为每个场景写入零时移基准行，验证成本恒等式，计算节省、边际节省和 10% 饱和起点。只有全部后续边际节省均在闭区间 `[0, 0.1 × 最大正边际节省]` 内时，才写入饱和起点。

- [x] **Step 4: 验证测试通过。**

```powershell
conda run -n scip_env python -m unittest tests.unit.test_flex_ratio_sensitivity.FlexRatioSensitivityTests.test_build_sensitivity_summary_uses_total_cost_and_marginal_savings
```

### Task 2: 实现完整 28 天敏感性实验

**Files:**
- Modify: `dc_energy_opt/experiments/flex_ratio_sensitivity.py`
- Modify: `dc_energy_opt/experiments/__init__.py`
- Create: `tests/integration/test_flex_ratio_sensitivity.py`

- [x] **Step 1: 写入发布目录与基准复用的失败测试。**

调用：

```python
result = run_flex_ratio_sensitivity_experiment(
    workload_data=workload_path,
    energy_data=energy_path,
    output_dir=output_dir,
    flex_ratios=(0.0, 0.1, 0.2),
)
```

断言结果表有 6 行；两个场景各有 `0.0, 0.1, 0.2`；求解器依次接收无储能基准、储能基准、无储能时移、储能时移、无储能时移、储能时移；发布目录含输入快照、结果 CSV、模型文件和元数据。

- [x] **Step 2: 验证测试失败。**

```powershell
conda run -n scip_env python -m unittest tests.integration.test_flex_ratio_sensitivity.FlexRatioSensitivityExperimentTests.test_full_experiment_uses_two_baselines_and_publishes_summary
```

Expected: FAIL，因为实验入口尚不存在。

- [x] **Step 3: 实现实验入口。**

定义不可变 `FlexRatioSensitivityResult`，字段为 `metrics: pd.DataFrame` 与 `metadata: dict[str, object]`；定义 `run_flex_ratio_sensitivity_experiment`，参数严格为 `workload_data`、`energy_data`、`output_dir`、`flex_ratios`、`params` 与 `show_solver_log`，返回 `FlexRatioSensitivityResult`。

入口使用 `staged_run_directory`，复制两份输入、复用主实验对齐逻辑，以 `replace(base_params, flex_ratio=0.0)` 求解两个基准；再对每个正比例依次求解 `renewables_shift` 与 `joint`。模型目录严格使用 `paths.models / scenario / f"ratio_{round(flex_ratio * 100):03d}"`。仅当全部汇总行 `status` 为 `optimal` 或模型已接受的 `gaplimit` 时发布。

- [x] **Step 4: 导出入口并验证。**

```powershell
conda run -n scip_env python -m unittest tests.integration.test_flex_ratio_sensitivity.FlexRatioSensitivityExperimentTests.test_full_experiment_uses_two_baselines_and_publishes_summary
```

### Task 3: 生成三张敏感性图

**Files:**
- Modify: `dc_energy_opt/reporting/plots.py`
- Modify: `dc_energy_opt/reporting/__init__.py`
- Modify: `tests/unit/test_plots.py`

- [x] **Step 1: 写入绘图失败测试。**

```python
output_paths = plots.make_flex_ratio_sensitivity_plots(sensitivity_metrics, output_dir)
self.assertEqual([path.name for path in output_paths], [
    "flex_ratio_total_cost.png",
    "flex_ratio_cost_savings.png",
    "flex_ratio_marginal_savings.png",
])
```

测试数据包含两个场景各三个比例，以及零时移行的空边际节省；每张图必须是 RGB 并可由 Pillow 验证。

- [x] **Step 2: 验证测试失败。**

```powershell
conda run -n scip_env python -m unittest tests.unit.test_plots.PlotTests.test_flex_ratio_sensitivity_plots_write_three_images
```

Expected: FAIL，因为绘图函数尚不存在。

- [x] **Step 3: 实现绘图函数。**

新增 `make_flex_ratio_sensitivity_plots(sensitivity_metrics: pd.DataFrame, output_dir: Path) -> list[Path]`，严格验证输出契约中的列、两个场景、比例递增、有限成本和场景内比例唯一性。

- `flex_ratio_total_cost.png`：上下两面板，总成本对比例；
- `flex_ratio_cost_savings.png`：两场景成本节省率对比，含零线；
- `flex_ratio_marginal_savings.png`：两场景边际节省柱形图，跳过零时移空值，含零线与 `saturation_onset` 竖线。

三张图片均为 `1800 × 900` RGB。

在 `tests/integration/test_flex_ratio_sensitivity.py` 的完整实验测试中补充断言：发布目录的 `figures/` 严格包含这三张图片。

- [x] **Step 4: 验证绘图测试。**

```powershell
conda run -n scip_env python -m unittest tests.unit.test_plots.PlotTests.test_flex_ratio_sensitivity_plots_write_three_images
```

### Task 4: 新增独立命令

**Files:**
- Create: `run_flex_ratio_sensitivity.py`
- Modify: `tests/integration/test_cli_entrypoints.py`

- [x] **Step 1: 写入命令失败测试。**

```python
run_flex_ratio_sensitivity.main([
    "--flex-ratios", "0,0.1,0.2",
    "--output-dir", "sensitivity-output",
])
self.assertEqual(run_experiment.call_args.kwargs["flex_ratios"], (0.0, 0.1, 0.2))
```

测试还断言终端只打印每个场景的基准成本、最低成本比例、最低成本、节省率与饱和起点，不打印图片目录。

- [x] **Step 2: 验证测试失败。**

```powershell
conda run -n scip_env python -m unittest tests.integration.test_cli_entrypoints.CliEntrypointTests.test_flex_ratio_sensitivity_command_delegates_and_prints_summary
```

Expected: FAIL，因为命令文件尚不存在。

- [x] **Step 3: 实现命令并验证。**

默认参数严格为：

```text
--workload-data data/workload/google_2019_28d_5min.csv
--energy-data data/energy/houston_2020_may_hourly.csv
--flex-ratios 0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1
--output-dir outputs/houston_2020_flex_ratio_sensitivity
```

`--flex-ratios` 将逗号分隔值转换为元组并调用 `validate_flex_ratios`；`--show-solver-log` 与主实验一致。

```powershell
conda run -n scip_env python -m unittest tests.integration.test_cli_entrypoints.CliEntrypointTests.test_flex_ratio_sensitivity_command_delegates_and_prints_summary
```

### Task 5: 更新说明并完成验证

**Files:**
- Modify: `README.md`
- Modify: `docs/houston_2020_experiment.md`
- Modify: `docs/superpowers/plans/2026-08-10-flex-ratio-sensitivity.md`

- [x] **Step 1: 更新 README 与实验文档。**

加入正式命令：

```powershell
conda run -n scip_env python run_flex_ratio_sensitivity.py
```

明确说明 0%–100% 的 10 个百分点扫描、三张图、零时移基准、总成本口径，以及局部 5 个百分点加密用法。

- [x] **Step 2: 运行正式项目测试与默认敏感性实验。**

```powershell
conda run -n scip_env python -m unittest discover -s tests -t . -v
conda run -n scip_env python run_flex_ratio_sensitivity.py
```

Expected: 项目测试通过；默认实验生成 22 行结果表和三张 PNG，终端仅打印两行场景摘要。

- [x] **Step 3: 核验并提交。**

核验每个场景有 11 个比例点、成本恒等式成立、零时移基准正确、首行边际节省为空值，并目视检查三张图。

```powershell
git add README.md dc_energy_opt/experiments/__init__.py dc_energy_opt/experiments/flex_ratio_sensitivity.py dc_energy_opt/reporting/__init__.py dc_energy_opt/reporting/plots.py docs/houston_2020_experiment.md docs/superpowers/plans/2026-08-10-flex-ratio-sensitivity.md run_flex_ratio_sensitivity.py tests/integration/test_cli_entrypoints.py tests/integration/test_flex_ratio_sensitivity.py tests/unit/test_flex_ratio_sensitivity.py tests/unit/test_plots.py
git commit -m "完成时移比例成本敏感性分析"
```

## 验证结果

- 正式项目测试共 120 项通过，4 项因当前 Windows 权限不支持符号链接而跳过。
- 默认 10 个百分点扫描生成 22 行结果表和三张 PNG。
- 两个场景的成本恒等式 22/22 行通过；成本均单调下降。
- `renewables_shift` 全部为 `optimal`；`joint` 的 0.8、0.9 比例为模型已接受的 `gaplimit`，其余比例为 `optimal`。
- 三张敏感性图已目视检查，边际节省图的首尾柱体均在坐标框内。
