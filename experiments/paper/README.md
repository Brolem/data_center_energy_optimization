# 论文线入口

统一命令格式：

```powershell
conda run -n scip_env python -m experiments.paper day-ahead
conda run -n scip_env python -m experiments.paper sensitivity flex-ratio
conda run -n scip_env python -m experiments.paper sensitivity storage-scale
conda run -n scip_env python -m experiments.paper sensitivity storage-energy-power
conda run -n scip_env python -m experiments.paper plot day-ahead --day 28
conda run -n scip_env python -m experiments.paper plot daily-costs
```

使用 `--help` 查看一级命令，或在具体命令后添加 `--help` 查看其参数。默认输入和输出路径由 `dc_energy_opt.config.HOUSTON_2020` 提供；绘图命令读取已有 CSV，不重新求解。

实现按职责放在 `houston_2020/day_ahead.py`、`houston_2020/sensitivity/` 和 `houston_2020/plotting/`。入口文件只负责命令解析与分派。
