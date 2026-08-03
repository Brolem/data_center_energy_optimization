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
- 新增 `plot_day_ahead_day.py`，只负责参数解析、CSV 读取和调用 `make_daily_plots`。
- 更新 `README.md` 与 `docs/houston_2020_experiment.md`。

## 验收

保留少量关键测试：

1. 结算尾段使用浅灰阴影且不存在紫色贯穿线。
2. 第 1 天和第 28 天均输出五张图，且第 28 天包含 3 小时结算尾段。
3. 独立命令只读取现有 CSV，并把指定日期传给绘图接口。

最后运行全部正式测试、归档测试，并实际生成和检查第 28 天五张图。
