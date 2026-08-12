# Data Center Energy Optimization

基于 PySCIPOpt 的数据中心跨日确定性日前调度项目。当前正式场景使用 Google 2019 聚合工作负载与 Houston 2020 年 5 月风光数据，比较 `renewables_only`、`renewables_shift`、`renewables_storage` 和 `joint` 四个算例。

## 项目结构

项目采用“两条主线 + 一个共享底座”：

- `dc_energy_opt/`：数据、参数、优化模型、指标绘图和结果发布等共享能力；
- `experiments/paper/`：论文主实验、敏感性分析、绘图和统一入口；
- `experiments/career/`：求职展示线的边界与路线说明，当前不包含未实现代码。

正式输入保留在 `data/`，正式输出保留在 `outputs/`。测试位于根目录 `tests/`，但不属于项目主展示结构。

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

求职线复用同一共享底座，后续用于展示预测、标准优化、工程化与面试实验。尚未实现的功能不提供空入口，当前范围见[求职线说明](experiments/career/README.md)。

## 文档

从[文档索引](docs/README.md)进入当前架构、模型、实验和结果说明。当前设计与实施状态集中在 `docs/development/current-change.md`，不再为每次修改新增多份设计文件。

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
