# 旧入口归档

本目录仅保存结构迁移前的命令脚本，便于追溯历史。它们不再是项目入口，也不纳入当前测试。

请使用以下统一入口：

| 旧脚本 | 当前命令 |
| --- | --- |
| `run_day_ahead_experiment.py` | `python -m experiments.paper day-ahead` |
| `run_first_version.py` | `python -m experiments.paper day-ahead` |
| `run_flex_ratio_sensitivity.py` | `python -m experiments.paper sensitivity flex-ratio` |
| `run_storage_scale_sensitivity.py` | `python -m experiments.paper sensitivity storage-scale` |
| `run_storage_energy_power_sensitivity.py` | `python -m experiments.paper sensitivity storage-energy-power` |
| `plot_day_ahead_day.py` | `python -m experiments.paper plot day-ahead` |
| `plot_daily_case_costs.py` | `python -m experiments.paper plot daily-costs` |
