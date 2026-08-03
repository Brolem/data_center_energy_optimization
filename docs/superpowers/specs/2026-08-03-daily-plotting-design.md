# 指定日期绘图与结算尾段标记设计

## 目标

新增独立绘图命令，直接读取现有 `hourly_dispatch.csv`，根据用户输入的日期生成该日五张结果图，不重新运行优化。同时修复结算尾段标记贯穿功率和 SOC 坐标轴、容易被误认为数据越界的问题。

## 命令行接口

新增仓库根目录入口 `plot_day_ahead_day.py`：

```powershell
python plot_day_ahead_day.py `
  --hourly-dispatch outputs/houston_2020_main/results/hourly_dispatch.csv `
  --day 28 `
  --output-dir outputs/houston_2020_main/figures
```

参数定义：

- `--hourly-dispatch`：现有 `hourly_dispatch.csv` 的路径。
- `--day`：必填整数，允许范围严格为 `1..28`。
- `--output-dir`：单日图的父输出目录。

实际输出目录为 `<output-dir>/day_XX/`，其中 `XX` 是两位日期编号。

## 单日数据范围

- 第 1～27 天：筛选精确字段 `day` 等于指定日期的记录；每个算例必须恰好包含 24 行，绘图横轴重编号为 `0..23`。
- 第 28 天：筛选精确字段 `day` 等于 `28` 的记录；每个算例必须恰好包含 27 行，其中前 24 行的 `period_role` 为 `analysis`，后 3 行为 `settlement_tail`；绘图横轴重编号为 `0..26`。
- 四个算例必须严格为 `renewables_only`、`renewables_shift`、`renewables_storage`、`joint`，每个算例使用相同日期范围。
- 单日绘图只读取结果，不调用任何优化函数。

## 输出内容

每次生成以下五个文件：

1. `power_dispatch.png`
2. `compute_schedule.png`
3. `battery_dispatch.png`
4. `renewable_dispatch.png`
5. `cost_breakdown.png`

前四张图复用现有绘图结构，但标题必须包含 `Day XX`。成本分解图按筛选后的小时记录，对下列精确字段按算例求和：

- `hourly_grid_purchase_cost_cny`
- `hourly_solar_om_cost_cny`
- `hourly_wind_om_cost_cny`
- `hourly_battery_om_cost_cny`
- `hourly_battery_degradation_cost_cny`
- `hourly_operating_cost_cny`

第 28 天成本包含 3 小时结算尾段，与该日图展示范围一致。

## 结算尾段视觉修复

删除 `_mark_settlement_tail()` 当前绘制的全高度紫色竖线。改为在 `settlement_tail` 覆盖的横轴范围内绘制浅灰背景阴影，并在阴影顶部标注 `3 h settlement tail`。

阴影不得遮盖曲线，不得使用任何现有数据序列颜色。完整 28 天图与第 28 天单日图使用相同标记。第 1～27 天没有 `settlement_tail`，不绘制阴影或标签。

## 代码结构

- 新增 `plot_day_ahead_day.py`：只负责参数解析、读取 CSV、调用公开绘图接口并打印输出目录。
- 修改 `dc_energy_opt/reporting/plots.py`：增加公开接口 `make_daily_plots(hourly_results, day_number, output_dir)`；抽取可复用的输入校验、标题和成本汇总逻辑；将尾段标记改为浅灰背景阴影。
- 修改 `dc_energy_opt/reporting/__init__.py`：公开导出 `make_daily_plots`。
- 修改 `tests/unit/test_plots.py`：覆盖单日筛选、五图输出、日期和结构校验、尾段阴影与紫线回归。
- 修改 `tests/integration/test_cli_entrypoints.py`：覆盖独立命令的精确参数转发、读取行为和输出路径。
- 更新 `README.md` 与 `docs/houston_2020_experiment.md`：记录单日绘图命令、输出目录和第 28 天结算尾段规则。

## 错误处理

以下情况必须在写出任何 PNG 前抛出明确异常：

- `hourly_dispatch.csv` 不存在或无法读取；
- `--day` 不是整数或不在 `1..28`；
- 缺少绘图所需精确字段；
- 算例集合不是规定的四个精确名称；
- 第 1～27 天任一算例不是 24 行；
- 第 28 天任一算例不是 27 行；
- `period_role`、日期或小时结构不符合上述规则；
- 数值字段包含非有限值或违反现有物理边界。

## 测试与验收

实施遵循测试先行：

1. 先增加失败测试，证明当前代码没有 `make_daily_plots` 和独立命令。
2. 实现最小功能使单日绘图测试通过。
3. 增加第 28 天尾段阴影像素级回归测试，证明不再存在贯穿坐标轴的紫线。
4. 验证第 1 天输出五张 24 小时图，第 28 天输出五张 27 小时图。
5. 运行正式测试：`conda run -n scip_env python -m unittest discover -s tests -t . -v`。
6. 运行归档测试：`conda run -n scip_env python -m unittest discover -s archive/legacy_phoenix/tests -t . -v`。

现有完整实验与完整周期五张图必须继续生成，输出文件名保持不变。
