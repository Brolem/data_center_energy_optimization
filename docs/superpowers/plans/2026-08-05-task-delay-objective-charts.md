# Task Delay Objective Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保存逐日一级、二级加权任务延迟，并生成28天全周期图和指定日期图。

**Architecture:** 保留现有两阶段优化流程，在一级解完成后补充“已提交时段”的一级延迟指标。滚动调度把一级、二级延迟按正式统计口径写入 `daily_metrics.csv`，统一绘图函数读取该文件生成上下双面板柱状图。

**Tech Stack:** Python、PySCIPOpt、pandas、Pillow、unittest/pytest。

---

## 已批准设计

- 图中只展示启用任务转移的 `renewables_shift` 和 `joint`。
- 每个算例一个面板，两个面板上下排列并共用纵轴范围。
- 灰色柱表示一级成本最优解的延迟，算例颜色柱表示二级延迟最小化后的延迟。
- 横轴为第1～28天，纵轴标题为 `Weighted delay (p.u.·h)`；每个面板标注全周期降低量和降幅。
- 第1～27天使用实际提交24小时的延迟；第28天使用完整27小时窗口延迟，从而计入结清遗留任务的3小时尾段，并与正式全周期延迟口径一致。
- 完整实验输出 `figures/task_delay_objectives.png`；指定日期命令输出 `figures/day_NN/task_delay_objectives.png`。
- B方案的逐小时任务分配图不在本次范围内。

## 实施清单

- [x] 在 `dc_energy_opt/optimization/window_model.py` 的一级求解结果中计算并返回 `primary_committed_task_delay_cpu_hours`。
- [x] 在 `dc_energy_opt/reporting/metrics.py` 的逐日记录中新增 `primary_task_delay_cpu_hours` 和 `secondary_task_delay_cpu_hours`；非末日分别取一级/二级已提交延迟，末日分别取一级/二级完整窗口延迟。
- [x] 在 `dc_energy_opt/reporting/plots.py` 新增 `TASK_DELAY_PLOT_FILENAME` 和 `make_task_delay_objective_plot(...)`，验证所需字段、两个算例、日期唯一性、数值非负性后绘制上下双面板柱状图。
- [x] 在 `dc_energy_opt/reporting/__init__.py` 导出新绘图接口；在 `dc_energy_opt/experiments/houston_2020.py` 完整实验结束时生成全周期图。
- [x] 在 `plot_day_ahead_day.py` 新增 `--daily-metrics`，默认读取 `outputs/houston_2020_main/results/daily_metrics.csv`，并为 `--day` 生成指定日期延迟图。
- [x] 更新 `README.md` 与 `docs/houston_2020_experiment.md` 的结果文件和命令说明。
- [x] 先补充少量失败测试，再实现最小代码；运行与窗口指标、逐日指标、绘图及命令入口相关的测试。
- [x] 重新运行 `conda run -n scip_env python run_day_ahead_experiment.py`，核对新CSV字段、两张图和全周期汇总一致性后提交本次改动。

## 实施验证

- 相关单元与集成测试共 54 项，全部通过。
- `renewables_shift`：一级 `112.9361 p.u.·h`，二级 `63.8959 p.u.·h`，降低 `43.42%`。
- `joint`：一级 `110.6468 p.u.·h`，二级 `63.1928 p.u.·h`，降低 `42.89%`。
- 两个算例的逐日二级延迟之和分别与 `case_metrics.csv` 的正式总延迟一致，浮点差异均小于 `1e-14 p.u.·h`。
- 完整实验图和第28天指定日期图均已生成并完成目视检查。
