# Data Center Energy Optimization

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

默认输出位于 `outputs/houston_2020_main/`，包含输入快照、结果表、五张图、按算例和窗口分层的 LP 模型，以及 `run_metadata.json`。发布采用同级临时目录整体替换；失败时保留上一次完整结果。

已有完整实验结果时，可直接生成指定日期的五张图，无需重新求解：

```powershell
conda run -n scip_env python plot_day_ahead_day.py `
  --hourly-dispatch outputs/houston_2020_main/results/hourly_dispatch.csv `
  --day 28 `
  --output-dir outputs/houston_2020_main/figures
```

结果写入 `figures/day_XX/`。第 1～27 天绘制 24 小时；第 28 天绘制 24 小时分析期和 3 小时浅灰背景标识的结算尾段。终端首先打印纯电网核算成本、纯电网所需峰值和风光成本贡献，随后打印四个正式算例的成本摘要；不打印图片目录。

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
