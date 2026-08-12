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

项目采用“长期有效文档 + 一个当前变更文档”，不再为每项功能新增带日期的设计和计划文件：

```text
docs/
├── README.md
├── architecture.md
├── development/
│   └── current-change.md
├── paper/
├── career/
└── archive/
```

`docs/README.md` 是文档索引，`docs/architecture.md` 只描述当前有效架构，`docs/development/current-change.md` 合并记录当前工作的设计、实施清单和验收结果。功能完成后，长期有效内容更新到正式文档；下一项工作直接改写 `current-change.md`，历史内容由 Git 保存。仅正式实验说明和正式结果报告可以按实验或日期增加文件。

根 README 按以下顺序组织：

1. 项目目标与当前正式成果；
2. “共享底座 + 论文线 + 求职线”结构；
3. 环境与论文主实验快速运行；
4. 论文线实验索引；
5. 求职线当前状态；
6. 数据与输出约定；
7. 详细文档链接；
8. 开发与测试命令。

现有文档迁入 `docs/paper/model/`、`docs/paper/experiments/` 和 `docs/paper/results/`，并更新所有相对链接与命令。`docs/archive/` 保持归档性质，不将历史开发计划改写为当前说明。本次设计和计划使用当前文件，不创建 `docs/superpowers/specs/` 或 `docs/superpowers/plans/`。

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

---

# 两条主线与共享底座实施计划

> **执行方式：** 在当前任务中逐项执行；每项完成后更新复选框。重构遵循先更新测试预期、确认失败，再迁移实现并恢复通过的顺序。

**目标：** 将现有项目迁移为论文线、求职线和共享底座，提供统一论文命令入口，并保持正式模型、数据和结果口径不变。

**架构：** `dc_energy_opt` 保留共享数据、优化、指标和结果发布能力；`experiments.paper` 承载 Houston 2020 论文实验、敏感性分析和绘图入口；`experiments.career` 当前只声明边界。测试按 `shared` 和 `paper` 归属迁移。

**技术栈：** Python 3.13、标准库 `argparse`/`unittest`、PySCIPOpt 6.2.1、pandas 3.0.5、NumPy 2.5.1、Pillow 12.3.0。

## 任务 1：建立新边界并让新入口测试先失败

**文件：**

- 创建：`experiments/__init__.py`
- 创建：`experiments/paper/__init__.py`
- 创建：`experiments/paper/houston_2020/__init__.py`
- 创建：`experiments/paper/houston_2020/sensitivity/__init__.py`
- 创建：`experiments/paper/houston_2020/plotting/__init__.py`
- 创建：`experiments/career/__init__.py`
- 创建：`tests/shared/__init__.py`
- 创建：`tests/paper/__init__.py`
- 创建：`tests/paper/test_cli.py`

- [ ] 创建包边界文件；所有 `__init__.py` 只包含包说明或明确公开导出。
- [ ] 在 `tests/paper/test_cli.py` 写入统一入口预期：

```python
import unittest

from experiments.paper.cli import parse_command


class PaperCliRoutingTests(unittest.TestCase):
    def test_day_ahead_command_preserves_formal_defaults(self) -> None:
        command = parse_command(["day-ahead"])
        self.assertEqual(command.name, "day-ahead")

    def test_sensitivity_command_requires_exact_study_name(self) -> None:
        command = parse_command(["sensitivity", "flex-ratio"])
        self.assertEqual(command.name, "sensitivity")
        self.assertEqual(command.study, "flex-ratio")
```

- [ ] 运行 `conda run -n scip_env python -m unittest tests.paper.test_cli -v`，确认因 `experiments.paper.cli` 尚不存在而失败。

## 任务 2：迁移共享发布能力和论文实验实现

**文件：**

- 移动：`dc_energy_opt/experiments/artifacts.py` → `dc_energy_opt/artifacts.py`
- 移动：`dc_energy_opt/experiments/houston_2020.py` → `experiments/paper/houston_2020/day_ahead.py`
- 移动：`dc_energy_opt/experiments/flex_ratio_sensitivity.py` → `experiments/paper/houston_2020/sensitivity/flex_ratio.py`
- 移动：`dc_energy_opt/experiments/storage_scale_sensitivity.py` → `experiments/paper/houston_2020/sensitivity/storage_scale.py`
- 移动：`dc_energy_opt/experiments/storage_energy_power_sensitivity.py` → `experiments/paper/houston_2020/sensitivity/storage_energy_power.py`
- 修改：上述迁移模块的导入语句
- 修改：`experiments/paper/houston_2020/__init__.py`
- 修改：`experiments/paper/houston_2020/sensitivity/__init__.py`

- [ ] 移动文件，不修改函数体和正式常量。
- [ ] 将包内相对导入替换为以下精确边界：

```python
from dc_energy_opt.artifacts import build_run_provenance, staged_run_directory
from dc_energy_opt.config import Parameters
from dc_energy_opt.data import load_and_prepare, load_houston_energy_scenario
from dc_energy_opt.optimization import run_rolling_day_ahead
from dc_energy_opt.reporting import software_versions
```

- [ ] 在 `experiments/paper/houston_2020/__init__.py` 导出 `ExperimentResult` 和 `run_houston_2020_experiment`；在 `sensitivity/__init__.py` 导出三类敏感性分析现有结果类型和运行函数。
- [ ] 使用 `rg` 检查生产代码不再导入 `dc_energy_opt.experiments`。
- [ ] 运行窗口模型和滚动调度测试，确认共享计算未改变。

## 任务 3：建立统一论文命令入口

**文件：**

- 创建：`experiments/paper/cli.py`
- 创建：`experiments/paper/__main__.py`
- 移动并改造：`plot_day_ahead_day.py` → `experiments/paper/houston_2020/plotting/day_ahead.py`
- 移动并改造：`plot_daily_case_costs.py` → `experiments/paper/houston_2020/plotting/daily_costs.py`
- 创建：`archive/legacy_entrypoints/README.md`
- 移动：原四个 `run_*.py`、`run_first_version.py` 至 `archive/legacy_entrypoints/`

- [ ] `experiments/paper/__main__.py` 只保留：

```python
from .cli import main


if __name__ == "__main__":
    main()
```

- [ ] 在 `cli.py` 定义不可变的 `PaperCommand`，并由 `parse_command()` 返回：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PaperCommand:
    name: str
    study: str | None
    arguments: object
```

- [ ] 使用标准库 `argparse` 创建 `day-ahead`、`sensitivity` 和 `plot` 三个一级命令，以及设计中列出的精确二级命令；迁移现有参数和默认值，不增加未存在的实验参数。
- [ ] `main()` 只分派现有运行函数或绘图函数；摘要格式化逻辑从旧入口迁入 `cli.py`，不得复制数学计算。
- [ ] 将旧入口放入归档并在归档 README 记录旧命令到新命令的逐项映射；归档入口不再属于正式支持接口。
- [ ] 运行 `tests.paper.test_cli`，确认新入口路由测试通过。

## 任务 4：按共享底座和论文线迁移现有测试

**文件：**

- 移动：共享职责测试 → `tests/shared/`
- 移动：论文实验、敏感性、绘图和 CLI 测试 → `tests/paper/`
- 修改：迁移测试中的导入路径和补丁目标

- [ ] 将配置、数据、窗口模型、滚动调度、指标、结果来源、事务发布和等价验证测试移至 `tests/shared/`。
- [ ] 将 Houston 2020 完整实验、三类敏感性分析、绘图和入口测试移至 `tests/paper/`。
- [ ] 将所有 `dc_energy_opt.experiments.*` 导入和补丁目标替换为实际迁移后的精确模块路径。
- [ ] 将旧入口专属断言替换为新统一入口的等价断言；不删除物理约束、数据哈希、结果口径或发布安全验证。
- [ ] 分别运行：

```powershell
conda run -n scip_env python -m unittest discover -s tests/shared -t . -v
conda run -n scip_env python -m unittest discover -s tests/paper -t . -v
```

预期两组均通过；Windows 缺少符号链接权限时，仅现有符号链接测试允许跳过。

## 任务 5：整理当前文档入口

**文件：**

- 创建：`docs/README.md`
- 创建：`docs/architecture.md`
- 创建：`docs/career/README.md`
- 创建：`experiments/paper/README.md`
- 创建：`experiments/career/README.md`
- 修改：`README.md`
- 移动：`docs/model/` → `docs/paper/model/`
- 移动：`docs/experiments/` → `docs/paper/experiments/`
- 移动：`docs/results/` → `docs/paper/results/`

- [ ] 根 README 先展示共享底座、论文线和求职线，再给论文快速运行命令；测试命令放在最后的开发与验证章节。
- [ ] `docs/README.md` 只链接当前有效的架构、论文、求职和归档入口。
- [ ] `docs/architecture.md` 记录最终目录、依赖方向、统一入口和文档维护规则。
- [ ] 更新所有当前非归档 Markdown 中的命令和相对链接；归档文档保持原始历史内容。
- [ ] 使用 `rg` 确认当前非归档文档不再引用根目录旧入口或 `docs/superpowers/`。

## 任务 6：完整验收

**文件：**

- 修改：`docs/development/current-change.md` 的任务状态和验收结果

- [ ] 运行编译检查：

```powershell
conda run -n scip_env python -m compileall -q dc_energy_opt experiments scripts tests
```

- [ ] 运行完整正式测试：

```powershell
conda run -n scip_env python -m unittest discover -s tests -t . -v
```

- [ ] 运行统一入口的 `--help`、三个实验子命令的参数解析测试及两个绘图子命令的参数解析测试。
- [ ] 运行现有等价验证工具，确认结果表仅允许既有计时字段差异。
- [ ] 重新统计 `outputs/` 文件数和字节数，确认与重构前记录的 4,580 个文件和 262,285,219 字节一致。
- [ ] 运行 `git diff --check`，检查 `git status --short` 仅包含批准范围内的文件。
- [ ] 将执行命令、测试数量、跳过数量、等价验证和输出目录核对结果写入当前文件的验收结果章节。
