# Data Center Energy Optimization

基于 PySCIPOpt 的数据中心跨日确定性日前调度模型。项目在算力需求、最大任务延迟、设备容量、电网功率与储能荷电状态约束下，联合优化购电、风光利用、任务时移和电池运行。

当前正式场景采用 Google 2019 聚合工作负载与 Houston 2020 年 5 月风光数据，覆盖 28 天。主实验比较四个算例：`renewables_only`、`renewables_shift`、`renewables_storage` 和 `joint`。

## 环境

```powershell
conda create -n scip_env python=3.13 -y
conda activate scip_env
python -m pip install -r requirements.txt
```

项目锁定 PySCIPOpt 6.2.1、pandas 3.0.5、NumPy 2.5.1、Pillow 12.3.0 和 NREL-PySAM 7.1.0；运行前还需确保 PySCIPOpt 可以加载 SCIP。

## 主实验

```powershell
conda run -n scip_env python run_day_ahead_experiment.py
```

默认结果写入 `outputs/houston_2020_main/`。可使用 `--workload-data`、`--energy-data`、`--output-dir` 与 `--show-solver-log` 指定输入、输出和求解日志。

`run_first_version.py` 仅保留旧参数的兼容转换；新实验请使用上面的正式入口。

## 结果查看

已有主实验结果时，可直接绘制指定日期，无需重新求解：

```powershell
conda run -n scip_env python plot_day_ahead_day.py --day 28
```

该命令读取 `daily_metrics.csv` 和 `hourly_dispatch.csv`，将图片写入 `figures/day_XX/`。第 28 天的图会额外标出 3 小时结算尾段。

如需比较四个正式算例的逐日运行成本：

```powershell
conda run -n scip_env python plot_daily_case_costs.py
```

## 扩展分析

时移比例敏感性分析固定模型条件，默认扫描 `flex_ratio=0.00..1.00`、步长为 0.10：

```powershell
conda run -n scip_env python run_flex_ratio_sensitivity.py
```

固定 3 小时时移下的储能规模敏感性分析，同时改变电池能量与充放电功率，并将每档完整项目保存到独立子目录：

```powershell
conda run -n scip_env python run_storage_scale_sensitivity.py
```

详见[储能规模敏感性分析说明](docs/experiments/houston_2020_storage_scale_sensitivity.md)和[本次正式结果报告](docs/results/houston_2020_storage_scale_sensitivity_2026-08-10.md)。

如需将电池能量和功率解耦，分别扫描 2、4、6 MWh 与 0.5、1、1.5 MW 的全部九种组合：

```powershell
conda run -n scip_env python run_storage_energy_power_sensitivity.py
```

该实验同样固定 3 小时时移，每个组合单独保存一个完整项目；详见[储能能量×功率敏感性分析说明](docs/experiments/houston_2020_storage_energy_power_sensitivity.md)和[本次正式结果报告](docs/results/houston_2020_storage_energy_power_sensitivity_2026-08-11.md)。

## 文档

- [确定性日前模型](docs/model/deterministic_day_ahead_model.md)
- [Houston 2020 主实验](docs/experiments/houston_2020_experiment.md)
- [储能规模敏感性分析](docs/experiments/houston_2020_storage_scale_sensitivity.md)
- [储能规模正式结果报告](docs/results/houston_2020_storage_scale_sensitivity_2026-08-10.md)
- [储能能量×功率敏感性分析](docs/experiments/houston_2020_storage_energy_power_sensitivity.md)
- [储能能量×功率正式结果报告](docs/results/houston_2020_storage_energy_power_sensitivity_2026-08-11.md)

## 测试

```powershell
conda run -n scip_env python -m unittest discover -s tests -t . -v
conda run -n scip_env python -m unittest discover -s archive/legacy_phoenix/tests -t . -v
```

第一条命令只运行正式项目测试；第二条命令单独运行历史 Phoenix 场景测试。
