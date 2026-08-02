# 数据中心能源优化项目结构重构设计

## 1. 目标与范围

本次重构解决以下问题：

- 项目、Python 包和入口仍使用 `first_version` 等阶段性名称；
- 现行 Houston 主实验与历史 Phoenix/Qinghai 数据和代码混放；
- 数据读取、窗口优化、滚动调度、实验执行和报告生成之间职责边界不清晰；
- 232 个 LP、结果表、输入快照和图片平铺在同一个输出目录；
- 测试文件按历史迭代累积，不能直接对应当前模块；
- 项目文档分散在根目录和 `docs/superpowers/` 中，存在重复内容。

本轮只重构仓库内部结构和命名，不改变数学模型、参数、求解器设置、Houston 数据、四组主实验或实验结论。本地仓库目录和 GitHub 仓库名称在内部重构完成并验证后单独处理。

正式名称统一为：

- 项目名称：`data_center_energy_optimization`；
- Python 包名：`dc_energy_opt`；
- 正式入口：`run_day_ahead_experiment.py`。

## 2. 目标目录结构

```text
data_center_energy_optimization/
├── data/
│   ├── workload/
│   │   ├── google_2019_28d_5min.csv
│   │   └── README.md
│   └── energy/
│       ├── houston_2020_may_hourly.csv
│       └── README.md
├── dc_energy_opt/
│   ├── __init__.py
│   ├── config.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── workload.py
│   │   └── energy.py
│   ├── optimization/
│   │   ├── __init__.py
│   │   ├── types.py
│   │   ├── window_model.py
│   │   └── rolling_day_ahead.py
│   ├── experiments/
│   │   ├── __init__.py
│   │   ├── houston_2020.py
│   │   └── artifacts.py
│   └── reporting/
│       ├── __init__.py
│       ├── metrics.py
│       └── plots.py
├── scripts/
│   └── prepare_houston_2020_energy.py
├── tests/
│   ├── unit/
│   └── integration/
├── archive/
│   └── legacy_phoenix/
├── outputs/
│   └── houston_2020_main/
├── docs/
│   ├── deterministic_day_ahead_model.md
│   ├── houston_2020_experiment.md
│   ├── repository_reorganization_design.md
│   └── repository_reorganization_implementation.md
├── run_day_ahead_experiment.py
├── run_first_version.py
├── README.md
└── requirements.txt
```

此处的根目录名称表示最终项目名称。本轮实施不移动当前工作区根目录。

## 3. 代码职责边界

### 3.1 配置

`dc_energy_opt/config.py` 只定义 `Parameters` 及其计算属性，不读取文件、不执行实验、不生成报告。

### 3.2 数据

`dc_energy_opt/data/workload.py` 负责读取、校验和聚合 Google 2019 算力数据。

`dc_energy_opt/data/energy.py` 负责读取并校验 Houston 风光出力、电价和连续时间轴。

两个模块只返回经过校验的数据，不构建优化变量，不写入实验输出。

### 3.3 优化

`dc_energy_opt/optimization/types.py` 定义跨日遗留任务和窗口求解状态。

`dc_energy_opt/optimization/window_model.py` 构建并求解单个 27 小时窗口，包括变量、约束、一级成本目标和二级任务延迟目标。

`dc_energy_opt/optimization/rolling_day_ahead.py` 负责预热、全周期 SOC 协调、每日 24+3 小时滚动求解以及任务和储能状态的跨日传递。

### 3.4 实验

`dc_energy_opt/experiments/houston_2020.py` 定义 `renewables_only`、`renewables_shift`、`renewables_storage` 和 `joint` 四组正式算例，组织 Houston 2020 主实验并返回结果。

`dc_energy_opt/experiments/artifacts.py` 负责输出路径、临时目录、输入快照、事务化发布、失败回滚和旧产物清理。实验模块不直接实现文件回滚细节。

### 3.5 报告

`dc_energy_opt/reporting/metrics.py` 负责小时、逐日和算例汇总指标及成本重算。

`dc_energy_opt/reporting/plots.py` 负责五张正式结果图，不承担指标计算或实验执行。

## 4. 数据与历史归档

正式输入文件调整为：

- `data/workload/google_2019_28d_5min.csv`：8,064 行五分钟 Google 2019 聚合算力数据；
- `data/energy/houston_2020_may_hourly.csv`：699 小时 Houston 风光可用功率和外生分时电价数据。

两个数据目录分别提供 `README.md`，记录字段、单位、时间范围、数据来源、处理方法和复现入口。文件迁移前后内容哈希必须相同。

历史 Phoenix/Qinghai 内容移入：

```text
archive/legacy_phoenix/
├── README.md
├── data/
│   ├── phoenix_nasa_power_20190501_20190528_hourly.csv
│   └── provisional_phoenix_weather_qinghai_tou_scenario.csv
├── legacy_energy_data.py
└── tests/
```

归档代码不由 `dc_energy_opt` 导出，不进入默认测试，也不参与 Houston 主实验。归档说明必须写明其历史用途以及不再作为正式实验输入。

## 5. 入口与兼容策略

正式运行命令为：

```powershell
conda run -n scip_env python run_day_ahead_experiment.py
```

正式入口使用以下参数：

- `--workload-data`；
- `--energy-data`；
- `--output-dir`；
- `--show-solver-log`。

`run_day_ahead_experiment.py` 只负责参数解析、调用 Houston 实验模块和向终端输出结果摘要，不保存模型实现或事务发布细节。

`run_first_version.py` 暂时作为兼容入口，保留原参数 `--input`、`--energy-scenario`、`--output-dir` 和 `--show-scip-log`，转换为新入口配置并打印迁移提示。兼容入口不得保留第二份实验实现。

原 `scip_first_version` 包在迁移完成后删除。新代码、测试、文档和脚本全部导入 `dc_energy_opt`，不保留包级兼容副本。

## 6. 输出结构与命名

默认输出目录为 `outputs/houston_2020_main/`：

```text
outputs/houston_2020_main/
├── inputs/
│   ├── google_2019_28d_5min.csv
│   ├── houston_2020_may_hourly.csv
│   └── aligned_28d_hourly.csv
├── results/
│   ├── hourly_workload.csv
│   ├── hourly_dispatch.csv
│   ├── daily_metrics.csv
│   └── case_metrics.csv
├── figures/
│   ├── power_dispatch.png
│   ├── compute_schedule.png
│   ├── battery_dispatch.png
│   ├── renewable_dispatch.png
│   └── cost_breakdown.png
├── models/
│   ├── renewables_only/
│   ├── renewables_shift/
│   ├── renewables_storage/
│   └── joint/
└── run_metadata.json
```

每个算例的 LP 按窗口和目标阶段继续分层。例如：

```text
models/joint/day_01/stage_1_cost.lp
models/joint/day_01/stage_2_delay.lp
models/joint/soc_coordination/stage_1_cost.lp
models/joint/soc_coordination/stage_2_delay.lp
```

默认重复运行不创建时间戳目录。运行过程先在同级临时目录完整生成输入快照、结果、图、LP 和元数据，验证成功后再整体发布；失败时保留原正式结果并清理临时目录。旧版平铺 LP、旧文件名和历史 Phoenix 输入快照在发布时清理。

## 7. 文档结构

`docs/` 不设置下级目录：

- `deterministic_day_ahead_model.md`：数学模型、两级目标、约束、跨日机制和参数；
- `houston_2020_experiment.md`：数据来源、实验设置、运行方法、输出字段、复现方法和结果解释；
- `repository_reorganization_design.md`：本设计；
- `repository_reorganization_implementation.md`：迁移步骤与验收清单。

根目录 `README.md` 只承担项目简介、安装方法、快速运行、主要结果和文档导航。

原 `FIRST_VERSION_GUIDE.md` 以及 `docs/superpowers/` 中仍有效的内容迁入以上文档后删除，不保留重复说明。

## 8. 测试结构

默认测试按被测职责划分：

```text
tests/
├── unit/
│   ├── test_config.py
│   ├── test_workload_data.py
│   ├── test_energy_data.py
│   ├── test_window_model.py
│   ├── test_metrics.py
│   └── test_plots.py
└── integration/
    ├── test_rolling_day_ahead.py
    ├── test_houston_2020_experiment.py
    └── test_artifact_publishing.py
```

单元测试验证单个模块的输入、输出、边界和错误；集成测试验证滚动跨日状态、完整主实验和事务化发布。归档目录中的历史测试不由默认测试发现命令执行。

## 9. 迁移顺序

1. 为新目录、文件名和兼容入口补充失败测试；
2. 创建 `dc_energy_opt` 并迁移配置、数据、优化、实验和报告代码；
3. 更新正式入口和兼容入口；
4. 移动正式数据并记录迁移前后哈希；
5. 迁移 Phoenix/Qinghai 历史内容到归档目录；
6. 按单元测试和集成测试结构拆分测试；
7. 更新文档和 Houston 场景生成脚本；
8. 实现分层输出和事务发布；
9. 清理旧包、旧文档、旧输出及缓存；
10. 运行全量测试、两个入口、结果等价检查和静态旧名称搜索。

## 10. 验收标准

- 现有 71 项测试覆盖的有效行为全部保留；
- Google 与 Houston 正式输入迁移前后内容哈希不变；
- 四组算例的小时结果、运行成本、SOC、任务延迟和弃电指标保持一致；
- 默认运行生成 2,700 行小时结果、112 行逐日指标、232 个 LP 和 5 张图；
- `outputs/houston_2020_main/` 根目录只包含 `inputs/`、`results/`、`figures/`、`models/` 和 `run_metadata.json`；
- 正式输出中不存在平铺 LP、历史 Phoenix 文件或旧结果文件名；
- 新入口和旧兼容入口生成相同结果；
- 全量测试、依赖检查、Python 编译和差异格式检查通过；
- 静态搜索确认正式代码、测试和文档不再导入 `scip_first_version`；
- 实施期间允许创建分阶段本地提交作为回退点，但不推送实现代码；本轮不移动当前工作区根目录，也不重命名 GitHub 仓库。

## 11. 明确不包含的工作

- 不修改日前优化的数学模型；
- 不调整服务器、风光、储能、电网或成本参数；
- 不增加日内优化、预测误差或新实验算例；
- 不恢复纯电网算例；
- 不创建按时间戳累计的默认运行目录；
- 不在本轮重命名本地仓库目录或 GitHub 仓库。
