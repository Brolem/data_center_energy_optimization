# Daily Case Cost Plots Implementation Plan

> **实施方式：** 在当前 Git 工作区按清单直接实现并验证。

**Goal:** 为四个正式算例分别生成横轴为真实日期、纵轴为24小时运行成本的独立柱形图。

**Architecture:** 绘图函数同时读取 `daily_metrics` 与 `hourly_dispatch`，用后者的 `timestamp_lst` 为每日成本建立精确日期映射，用前者的 `operating_cost_cny` 绘制四张统一纵轴柱形图。完整实验自动调用该函数，独立命令可直接读取现有 CSV 重新出图。

**Tech Stack:** Python、pandas、NumPy、Pillow、unittest。

---

## 已批准设计

- 四个正式算例各输出一张图：`daily_cost_renewables_only.png`、`daily_cost_renewables_shift.png`、`daily_cost_renewables_storage.png`、`daily_cost_joint.png`。
- 横轴使用 `hourly_dispatch.csv` 中分析期的真实日期；纵轴使用 `daily_metrics.csv` 的 `operating_cost_cny`，单位为每24小时 CNY。
- 四张图共用由全部算例成本范围计算出的纵轴上下限，便于横向比较。
- 每日成本以逐日柱体显示，最高和最低日标注日期与成本。
- 第28天仍只绘制24小时成本；`settlement_tail_operating_cost_cny` 作为3小时结算尾段文字注释，不加入柱体。
- 新增 `plot_daily_case_costs.py`，默认读取 `outputs/houston_2020_main/results/daily_metrics.csv` 与 `hourly_dispatch.csv`，输出至 `outputs/houston_2020_main/figures`。

## 实施清单

- [x] 在 `tests/unit/test_plots.py` 新增失败测试，要求真实日期映射后生成四张 `1800 × 900` RGB 图片。
- [x] 在 `dc_energy_opt/reporting/plots.py` 新增文件名常量、输入校验、日期映射和四图绘制函数。
- [x] 在 `tests/integration/test_cli_entrypoints.py` 新增失败测试，再实现 `plot_daily_case_costs.py` 的 CSV 参数和绘图调用。
- [x] 在 `dc_energy_opt/reporting/__init__.py` 导出接口，并在 `dc_energy_opt/experiments/houston_2020.py` 中自动生成四张图。
- [x] 更新实验输出树测试、`README.md` 与 `docs/houston_2020_experiment.md`。
- [x] 运行绘图、命令入口和完整实验相关测试；使用现有 CSV 执行独立命令并目视检查四张图后提交。

## 验证结果

- 正式项目测试共 116 项通过，4 项因当前 Windows 权限不支持符号链接而跳过。
- 独立命令成功读取现有 CSV 并生成四张图片。
- 四张图片均为 `1800 × 900` RGB，日期、统一纵轴、极值标注和结算尾段说明经目视检查。
