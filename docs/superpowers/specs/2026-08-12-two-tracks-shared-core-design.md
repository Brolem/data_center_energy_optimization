# 两条主线与共享底座重构设计

## 1. 目标与边界

本次重构把项目整理为“论文线、求职线、共享底座”，同时清理根目录中重复的 `run_*.py` 和 `plot_*.py` 入口。重构只调整目录、模块归属、命令入口、文档链接和测试位置。

本次不修改以下内容：

- 确定性日前优化模型、数学约束和两级目标；
- `Parameters` 中的正式参数值；
- Google 2019 与 Houston 2020 正式数据的文件内容；
- 四个正式算例及三类敏感性分析的计算口径；
- `outputs/` 中已有的未跟踪实验结果；
- 预测、启发式、不确定优化及其他尚未实现的功能。

Git 长期只保留 `main` 主干。论文和求职在目录中分线，具体开发使用短生命周期功能分支。

## 2. 目标结构

```text
data_center_energy_optimization/
├── dc_energy_opt/                     # 共享底座
│   ├── __init__.py
│   ├── config.py
│   ├── artifacts.py
│   ├── data/
│   ├── optimization/
│   └── reporting/
│
├── experiments/
│   ├── __init__.py
│   ├── paper/                         # 论文线
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── cli.py
│   │   ├── README.md
│   │   └── houston_2020/
│   │       ├── __init__.py
│   │       ├── day_ahead.py
│   │       ├── sensitivity/
│   │       │   ├── __init__.py
│   │       │   ├── flex_ratio.py
│   │       │   ├── storage_scale.py
│   │       │   └── storage_energy_power.py
│   │       └── plotting/
│   │           ├── __init__.py
│   │           ├── day_ahead.py
│   │           └── daily_costs.py
│   └── career/                        # 求职线
│       ├── __init__.py
│       └── README.md
│
├── data/                              # 两条线共享的正式输入
├── outputs/                           # 保持现有位置和内容
├── scripts/                           # 数据准备与验证工具
├── docs/
│   ├── architecture/
│   ├── paper/
│   │   ├── model/
│   │   ├── experiments/
│   │   └── results/
│   └── archive/
│
├── tests/                             # 次级工程设施
│   ├── shared/
│   └── paper/
│
├── README.md
└── requirements.txt
```

`tests/` 保留在根目录，这是 Python 项目的标准位置；但 README 与项目结构说明先展示共享底座和两条主线，测试说明放在开发与验证章节。生产模块中不嵌入测试代码。

## 3. 模块迁移

### 3.1 共享底座

以下能力继续由 `dc_energy_opt` 提供：

- `config.py`：正式参数和 Houston 2020 路径配置；
- `data/`：工作负载与能源数据读取和校验；
- `optimization/`：窗口模型、跨日滚动调度和状态类型；
- `reporting/`：两条线均可复用的指标与基础绘图能力；
- `artifacts.py`：运行来源记录与结果目录事务发布。

现有 `dc_energy_opt/experiments/artifacts.py` 移至 `dc_energy_opt/artifacts.py`。`dc_energy_opt` 现有正式公开接口保持可用。

### 3.2 论文线

现有实验模块按以下关系迁移：

| 现有模块 | 新模块 |
|---|---|
| `dc_energy_opt/experiments/houston_2020.py` | `experiments/paper/houston_2020/day_ahead.py` |
| `dc_energy_opt/experiments/flex_ratio_sensitivity.py` | `experiments/paper/houston_2020/sensitivity/flex_ratio.py` |
| `dc_energy_opt/experiments/storage_scale_sensitivity.py` | `experiments/paper/houston_2020/sensitivity/storage_scale.py` |
| `dc_energy_opt/experiments/storage_energy_power_sensitivity.py` | `experiments/paper/houston_2020/sensitivity/storage_energy_power.py` |
| `plot_day_ahead_day.py` | `experiments/paper/houston_2020/plotting/day_ahead.py` |
| `plot_daily_case_costs.py` | `experiments/paper/houston_2020/plotting/daily_costs.py` |

实验函数名称、参数名称和返回类型保持不变，只更新导入路径。论文专属绘图实现随论文线迁移；共享指标和基础绘图辅助函数保留在 `dc_energy_opt/reporting/`。

### 3.3 求职线

求职线当前只创建包边界与 `README.md`。文档明确计划中的预测、标准优化、启发式、规模测试和预测驱动优化均尚未实现，不创建空 Python 入口，也不写无法运行的示例命令。

## 4. 统一命令入口

`experiments/paper/__main__.py` 只调用 `cli.py` 的 `main()`。`cli.py` 使用子命令分派现有实验和绘图函数。

正式命令为：

```powershell
conda run -n scip_env python -m experiments.paper day-ahead
conda run -n scip_env python -m experiments.paper sensitivity flex-ratio
conda run -n scip_env python -m experiments.paper sensitivity storage-scale
conda run -n scip_env python -m experiments.paper sensitivity storage-energy-power
conda run -n scip_env python -m experiments.paper plot day-ahead --day 28
conda run -n scip_env python -m experiments.paper plot daily-costs
```

现有 `--workload-data`、`--energy-data`、`--output-dir` 和 `--show-solver-log` 参数按各自实验入口迁移；`--flex-ratios` 按时移比例敏感性入口迁移；`--hourly-dispatch`、`--daily-metrics` 和 `--day` 按绘图入口迁移。所有默认值保持不变。未知命令、未知参数和无效数值继续由命令解析或现有校验明确拒绝。

根目录的四个 `run_*.py`、两个 `plot_*.py` 以及 `run_first_version.py` 不再作为正式入口。完成新入口及文档迁移后，将这些旧入口移入 `archive/legacy_entrypoints/`，避免继续占据项目根目录。

## 5. 文档设计

根 README 按以下顺序组织：

1. 项目目标与当前正式成果；
2. “共享底座 + 论文线 + 求职线”结构；
3. 环境与论文主实验快速运行；
4. 论文线实验索引；
5. 求职线当前状态；
6. 数据与输出约定；
7. 详细文档链接；
8. 开发与测试命令。

现有文档迁入 `docs/paper/model/`、`docs/paper/experiments/` 和 `docs/paper/results/`，并更新所有相对链接与命令。`docs/archive/` 保持归档性质，不将历史开发计划改写为当前说明。

## 6. 测试迁移与使用策略

测试保留其现有验证含义，按被测职责迁移：

- `tests/shared/`：配置、正式数据、窗口模型、滚动调度、指标、运行来源、事务发布和结果等价验证；
- `tests/paper/`：统一论文入口、Houston 2020 完整实验、三类敏感性分析和论文绘图。

不为尚无实现的求职线创建测试。迁移期间不同时删除或合并现有测试，以便精确判断失败是否由路径和入口调整引起。结构稳定后，只有验证对象、输入和失败原因完全相同的测试才可另行合并。

README 只保留以下三种使用方式：

```powershell
# 日常修改共享底座
conda run -n scip_env python -m unittest discover -s tests/shared -t . -v

# 日常修改论文线
conda run -n scip_env python -m unittest discover -s tests/paper -t . -v

# 重构验收或发布前
conda run -n scip_env python -m unittest discover -s tests -t . -v
```

测试是结果可信度保障，不作为项目首页的核心卖点，也不要求当前学习重点转向测试框架。

## 7. 验收标准

重构完成必须同时满足：

- `git status` 只包含本次批准范围内的迁移和修改；
- 新包和所有正式入口通过编译检查；
- `tests/shared/`、`tests/paper/` 和完整测试分别通过；
- 新命令的默认输入、默认输出和布尔开关与现有入口一致；
- 主实验四个算例和三类敏感性分析仍调用原有计算函数；
- 结果等价验证通过，允许的差异仅限求解时间等非确定性计时字段；
- 正式数据文件的 SHA-256 验证继续通过；
- `outputs/` 现有 4,580 个文件不被移动、删除或改写；
- README 与当前非归档文档不再引用旧的根目录入口；
- `git diff --check` 无空白错误。

## 8. 明确不做

本次不添加配置文件体系、不引入新的命令行框架、不更换 `unittest`、不新增 CI、不重新生成正式实验结果、不重构数学模型内部函数，也不实现求职线算法。上述工作均需单独设计和验证。
