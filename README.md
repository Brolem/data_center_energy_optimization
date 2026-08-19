# Data Center Energy Optimization（已归档）

> **本仓库已冻结，不再开发新功能。** 当前研究已迁移到独立新项目；本仓库只作历史归档与复现参考。归档说明见 [ARCHIVED.md](ARCHIVED.md)。

基于 PySCIPOpt 的数据中心确定性日前调度项目。`main` 现保留 Houston 2020 论文线与求职线历史工作；Spot GPU 论文线等后续研究已封存为 Git tag。

## 归档 tag 与新方向

| tag | 内容 |
| --- | --- |
| `archive/paper-spot-gpu` | ERCOT 2025 × Alibaba Spot GPU 论文线（设计 + 因果预测 + 作业重放 + 调度器 WIP） |
| `archive/career-forecast-validation` | 求职线预测模型选择协议 |

新的研究“数据中心算电协同调度（Alibaba cluster-trace-v2018 + PV/BESS + 分布鲁棒/鲁棒优化 + 双侧不确定）”已迁到独立项目，规格见新项目根目录 `README.md`。

## 项目结构

项目采用“两条主线 + 一个共享底座”：

- `dc_energy_opt/`：数据、参数、优化模型、指标绘图和结果发布等共享能力；
- `experiments/paper/`：论文主实验、敏感性分析、绘图和统一入口；
- `experiments/career/`：求职线（ERCOT 2025 Spot GPU 预测驱动调度），已归档、不再开发。
- `legacy/`：遗留代码（旧入口与 Phoenix 场景），只读。

正式输入保留在 `data/`。论文输出写入 `outputs/paper/`，求职线使用预留的 `outputs/career/`；每个实验固定覆盖自己的完整结果目录。测试位于根目录 `tests/`，但不属于项目主展示结构。

## 环境

```powershell
conda create -n scip_env python=3.13 -y
conda activate scip_env
python -m pip install -r requirements.txt
```

项目锁定 PySCIPOpt 6.2.1、pandas 3.0.5、NumPy 2.5.1、Pillow 12.3.0 和 NREL-PySAM 7.1.0；运行前需确保 PySCIPOpt 可以加载 SCIP。

## 论文线快速运行

主实验：

```powershell
conda run -n scip_env python -m experiments.paper day-ahead
```

敏感性分析：

```powershell
conda run -n scip_env python -m experiments.paper sensitivity flex-ratio
conda run -n scip_env python -m experiments.paper sensitivity storage-scale
conda run -n scip_env python -m experiments.paper sensitivity storage-energy-power
```

直接使用已有结果绘图，无需重新求解：

```powershell
conda run -n scip_env python -m experiments.paper plot day-ahead --day 28
conda run -n scip_env python -m experiments.paper plot daily-costs
```

各命令保留原有输入、输出和求解日志参数。完整说明见[论文线入口](experiments/paper/README.md)。

## 求职线

求职线复用同一共享底座，包含 ERCOT 2025 Spot GPU 预测驱动调度的实现，已归档、不再开发。说明见 [求职线说明](experiments/career/README.md)。

## 文档

从[文档索引](docs/README.md)进入当前架构、模型、实验和结果说明。开发状态按主线分存于 `docs/development/paper/`、`docs/development/career/` 和 `docs/development/shared/`；`docs/development/current-change.md` 仅保留历史记录。

## 开发与验证

按修改范围运行测试：

```powershell
# 共享底座
conda run -n scip_env python -m unittest discover -s tests/shared -t . -v

# 论文线
conda run -n scip_env python -m unittest discover -s tests/paper -t . -v

# 发布前完整验证
conda run -n scip_env python -m unittest discover -s tests -t . -v
```

无需专门学习更多测试框架；当前重点是读懂关键约束、实验入口和结果验证。新增功能只补最小必要测试：一个正常路径、一个关键边界，以及涉及正式数据或结果时的回归检查。
