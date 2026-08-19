# 项目架构

> 本仓库已冻结归档；本文描述的是历史工作结构，不再演进。归档说明见根目录 [ARCHIVED.md](../ARCHIVED.md)。

## 总体结构

```text
dc_energy_opt/       共享底座：配置、数据、优化、报告、产物发布
experiments/
  paper/             论文线：Houston 2020 实验、敏感性与绘图
  career/            求职线（已归档）：ERCOT 2025 Spot GPU 预测驱动调度
data/                 共享正式输入
outputs/
  paper/
    houston_2020/
      day_ahead/      论文主实验完整结果
      sensitivity/    三类论文敏感性分析结果
  career/             求职线结果边界
docs/                 当前文档与历史归档
tests/                次级工程设施：shared 与 paper
```

## 依赖方向

`experiments.paper` 可以调用 `dc_energy_opt`；`dc_energy_opt` 不反向依赖任何实验线。论文线与求职线不互相导入。共享底座不包含具体论文命令，实验线不复制数据读取、优化模型或结果发布实现。

论文线统一入口为 `python -m experiments.paper`。入口只负责参数解析、调用现有实验函数和输出摘要；数学模型仍位于共享底座。

每个叶子实验目录是一个完整发布单元，内部包含输入快照、模型、结果、图和元数据。同一命令重复运行时安全覆盖固定目录；运行失败时保留上一份完整结果。

## Git 与文档规则

长期使用一个 `main` 主干，两条线通过目录区分；具体修改使用短生命周期功能分支。文档采用“长期有效文档 + 按主线隔离的开发状态”：架构、模型和实验说明保持稳定；论文线、求职线和共享改动分别记录在 `development/paper/`、`development/career/` 和 `development/shared/`。旧 `development/current-change.md` 仅保留为历史记录，不再承载新工作。

正式实验说明和正式结果报告可以按实验增加文件；一般功能修改不新增日期化设计文档。完成一项工作后直接改写所属主线的开发状态文件，历史版本交给 Git。
