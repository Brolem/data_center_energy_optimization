# 指定日期绘图：设计与实施说明

## 目标

直接读取现有 `hourly_dispatch.csv`，输入第 `1..28` 天并生成该日五张图，不重新运行优化。同时将误导性的紫色结算尾段贯穿线改为浅灰背景阴影。

## 接口

新增命令：

```powershell
python plot_day_ahead_day.py `
  --hourly-dispatch outputs/houston_2020_main/results/hourly_dispatch.csv `
  --day 28 `
  --output-dir outputs/houston_2020_main/figures
```

输出目录为 `figures/day_XX/`，包含：

- `power_dispatch.png`
- `compute_schedule.png`
- `battery_dispatch.png`
- `renewable_dispatch.png`
- `cost_breakdown.png`

第 1～27 天绘制 24 小时；第 28 天绘制 24 小时分析期和 3 小时结算尾段。第 28 天成本包含结算尾段。

## 实施

- 在 `dc_energy_opt/reporting/plots.py` 增加公开接口 `make_daily_plots(hourly_results, day_number, output_dir)`。
- 严格校验 `day`、四个正式算例、每个算例的行数和 `period_role`；在写图前拒绝无效输入。
- 将选定日期按算例排序，并把横轴重编号为 `0..23` 或 `0..26`。
- 从六个精确的 `hourly_*_cost_cny` 字段汇总当日成本。
- 复用现有五个绘图器，标题增加 `Day XX`。
- 将 `_mark_settlement_tail()` 改为浅灰背景阴影和中性文字，不再绘制紫色贯穿线。
- 新增 `plot_day_ahead_day.py`，负责参数解析、CSV 读取、目标相关摘要打印和调用 `make_daily_plots`。
- 更新 `README.md` 与 `docs/houston_2020_experiment.md`。

### 电池时序对齐修正

- 同一小时的充电、放电柱使用相同中心横坐标，仅通过正负方向和颜色区分，不再左右错位。
- SOC 不再把 `soc_start` 与 `soc_end` 作为两条同横坐标折线叠画；改为一条小时边界状态轨迹：第一个点为首小时 `soc_start`，后续点依次为各小时 `soc_end`。
- 功率柱位于对应小时区间中心，SOC 点位于小时区间边界，使充放电功率与该小时造成的 SOC 变化严格对齐。
- 只修改绘图及其最小回归测试，不修改优化模型、CSV 字段或求解结果。

### 终端目标摘要

- 最开始打印纯电网核算成本和纯电网所需峰值；峰值取选定日期 `renewables_only` 的 `dc_power_mw` 最大值。
- 纯电网核算成本使用相同 `dc_power_mw`，按 `electricity_price_cny_per_kwh` 计算，不重新求解。
- 打印 `renewables_only` 成本以及风光贡献的金额和比例。
- 随后仅打印四个正式算例的分析期成本、结算尾段成本、总成本及相对 `renewables_only` 的节省率。
- 不打印模型并网功率上界、超出量和图片输出目录。

## 验收

保留少量关键测试：

1. 结算尾段使用浅灰阴影且不存在紫色贯穿线。
2. 第 1 天和第 28 天均输出五张图，且第 28 天包含 3 小时结算尾段。
3. 独立命令只读取现有 CSV，并把指定日期传给绘图接口。
4. 充电和放电柱共用同一小时中心，SOC 轨迹包含 `N+1` 个小时边界状态点。
5. 单日命令首先打印纯电网核算结果和所需峰值，只保留目标相关成本摘要且不打印图片目录。

最后运行全部正式测试、归档测试，并实际生成和检查第 28 天五张图。
