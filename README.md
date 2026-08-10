# Data Center Energy Optimization

## 固定延迟储能规模敏感性

固定 max_delay_h=3、分别运行 2.0 MWh / 0.5 MW、4.0 MWh / 1.0 MW 与 6.0 MWh / 1.5 MW 三档独立储能项目：

~~~powershell
conda run -n scip_env python run_storage_scale_sensitivity.py
~~~

每档结果保存在独立子目录，父目录额外保存横向汇总 CSV、两张比较图与分析报告。详见 [储能规模敏感性说明](docs/houston_2020_storage_scale_sensitivity.md)。

## 项目简介

本项目使用 PySCIPOpt 建立数据中心跨日确定性日前调度模型，在满足算力需求、最大任务延迟、设备容量和储能状态约束的前提下，联合优化电网购电、风光利用、算力时移与电储能运行。当前正式实现为 Houston 2020 风光与 Google 2019 聚合工作负载的 28 天主实验。

## 主实验

正式实验比较四组均含风光的算例：`renewables_only`、`renewables_shift`、`renewables_storage` 和 `joint`。目标首先最小化购电、光伏运维、风电运维、储能吞吐运维和储能循环退化五项成本，再在一级成本容差内最小化柔性任务总延迟。6.6 MW 并网容量仅作为物理约束。

## 环境安装

推荐使用独立 Conda 环境：

```powershell
conda create -n scip_env python=3.13 -y
conda activate scip_env
python -m pip install -r requirements.txt
```

项目锁定 PySCIPOpt 6.2.1、pandas 3.0.5、NumPy 2.5.1、Pillow 12.3.0 和 NREL-PySAM 7.1.0。运行前还需确保 SCIP 可由 PySCIPOpt 正常加载。

## 快速运行

运行默认主实验：

```powershell
conda run -n scip_env python run_day_ahead_experiment.py
```

可使用 `--workload-data`、`--energy-data`、`--output-dir` 和 `--show-solver-log` 指定输入、输出与求解日志。

迁移说明：`run_first_version.py` 仅保留旧参数转换功能，新实验应使用正式入口。

## 输出目录

默认输出位于 `outputs/houston_2020_main/`，包含输入快照、结果表、十张图、按算例和窗口分层的 LP 模型，以及 `run_metadata.json`。其中 `task_delay_objectives.png` 对比两个任务转移算例每天的一级、二级加权延迟；四张 `daily_cost_<case>.png` 分别展示四个正式算例的每日 24 小时运行成本，并使用相同纵轴范围。发布采用同级临时目录整体替换；失败时保留上一次完整结果。

已有完整实验结果时，可直接生成指定日期的六张图，无需重新求解：

```powershell
conda run -n scip_env python plot_day_ahead_day.py --day 28
```

命令同时读取同一结果目录中的 `daily_metrics.csv`。结果写入 `figures/day_XX/`；`task_delay_objectives.png` 用上下双面板展示 `renewables_shift` 与 `joint` 当天的一级、二级加权延迟。第 1～27 天绘制 24 小时；第 28 天绘制 24 小时分析期和 3 小时浅灰背景标识的结算尾段。终端首先打印纯电网核算成本、纯电网所需峰值和风光成本贡献，随后打印四个正式算例的成本摘要；不打印图片目录。

已有完整实验结果时，也可直接生成四个算例各自的每日成本柱形图：

```powershell
conda run -n scip_env python plot_daily_case_costs.py
```

横轴日期来自 `hourly_dispatch.csv` 的分析期时间戳，纵轴来自 `daily_metrics.csv` 的 `operating_cost_cny`。第 28 日的 3 小时结算尾段成本仅标注在图中，不计入柱体。

固定模型条件下进行时移比例敏感性分析：

```powershell
conda run -n scip_env python run_flex_ratio_sensitivity.py
```

默认扫描 `flex_ratio=0.00..1.00`、步长 0.10，分别以 `renewables_only` 和 `renewables_storage` 为零时移基准，输出总成本、节省率、边际节省和三张敏感性图。需要局部加密时，可显式传入逗号分隔的比例，例如 `--flex-ratios 0,0.05,0.1,0.15,0.2`。

## 测试

```powershell
conda run -n scip_env python -m unittest discover -s tests -t . -v
conda run -n scip_env python -m unittest discover -s archive/legacy_phoenix/tests -t . -v
```

第一条命令只运行正式项目测试；历史 Phoenix 场景测试由第二条命令单独运行。

## 文档导航

- [确定性日前模型](docs/deterministic_day_ahead_model.md)
- [Houston 2020 主实验](docs/houston_2020_experiment.md)
- [仓库重组设计](docs/repository_reorganization_design.md)
- [仓库重组实施清单](docs/repository_reorganization_implementation.md)
