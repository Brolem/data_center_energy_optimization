# 论文输出路径统一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将论文实验默认输出统一到 `outputs/paper/houston_2020/`，同时保持现有简洁命令、固定路径安全覆盖和实验内部产物结构。

**Architecture:** 只修改 `HOUSTON_2020` 中四个最终目录，论文 CLI 继续从该配置派生实验与绘图默认路径。现有实验函数和 `staged_run_directory()` 不变，因此每个叶子实验目录仍作为一个完整事务发布单元。

**Tech Stack:** Python 3.13、`pathlib.Path`、标准库 `argparse`/`unittest`、PySCIPOpt 6.2.1。

---

## 已批准设计

## 结论

`outputs/` 按“主线 → 场景 → 实验”组织。论文线和求职线从顶层隔离，Houston 2020 的主实验与敏感性分析在场景目录内分开。每个实验继续使用固定路径安全覆盖，不按时间创建运行目录。

## 目标结构

```text
outputs/
├── paper/
│   └── houston_2020/
│       ├── day_ahead/
│       │   ├── inputs/
│       │   ├── models/
│       │   ├── results/
│       │   ├── figures/
│       │   └── run_metadata.json
│       └── sensitivity/
│           ├── flex_ratio/
│           ├── storage_scale/
│           └── storage_energy_power/
└── career/
```

三类敏感性分析目录继续保留各自现有的完整产物结构。产生 `analysis.md` 或 `experiments/` 子目录的实验仍在自己的最终目录内保存这些产物。

## 默认路径映射

| 论文命令 | 默认最终目录 |
|---|---|
| `python -m experiments.paper day-ahead` | `outputs/paper/houston_2020/day_ahead/` |
| `python -m experiments.paper sensitivity flex-ratio` | `outputs/paper/houston_2020/sensitivity/flex_ratio/` |
| `python -m experiments.paper sensitivity storage-scale` | `outputs/paper/houston_2020/sensitivity/storage_scale/` |
| `python -m experiments.paper sensitivity storage-energy-power` | `outputs/paper/houston_2020/sensitivity/storage_energy_power/` |

绘图命令保持不变：

```powershell
python -m experiments.paper plot day-ahead --day 28
python -m experiments.paper plot daily-costs
```

它们默认读取 `outputs/paper/houston_2020/day_ahead/results/`，并写入 `outputs/paper/houston_2020/day_ahead/figures/`。

## 命令设计

- 日常运行不需要提供输出参数；
- 保留现有 `--output-dir`，用于明确指定临时或外部最终目录；
- 保留绘图命令现有的结果文件和输出目录高级参数；
- 不增加 `--output-root`、命令别名、结果清理命令或时间戳运行目录；
- 不扁平化 `sensitivity` 子命令，继续让实验类别在命令层级中清晰可见。

## 发布与失败处理

每个实验的最终目录仍由 `staged_run_directory()` 整体发布。运行过程先在最终目录同级位置构建临时树；全部输入快照、模型、结果、图和元数据成功生成后，再替换固定最终目录。运行失败时保留上一份完整结果，不发布半成品。

输入文件不得等于最终目录或位于最终目录内部。路径层级变化不得削弱现有冲突检查、只读文件处理、符号链接与目录联接保护。

## 范围

本次修改：

- `HOUSTON_2020` 的四个默认输出目录；
- 论文 CLI 的绘图默认读取与写入路径；
- 当前非归档文档中的默认路径、目录树和产物链接；
- 直接验证上述默认路径的测试断言。

本次不修改：

- 数学模型、正式参数、数据文件和计算口径；
- 实验目录内部的 `inputs/`、`models/`、`results/`、`figures/` 结构；
- 原子发布实现；
- 用户已有结果文件。

旧 `outputs/` 结果由用户自行删除。本次不迁移、不删除、不兼容旧输出目录，也不为旧路径增加回退逻辑。

## 验收标准

- 四个无输出参数的论文实验命令解析到表中规定的精确目录；
- 两个绘图命令解析到 `day_ahead/results/` 和 `day_ahead/figures/`；
- `--output-dir` 仍能覆盖各实验默认最终目录；
- 当前非归档文档不再引用四个旧默认输出目录；
- 共享底座与论文线测试通过，Windows 无符号链接权限时仅既有符号链接测试允许跳过；
- 编译检查与 `git diff --check` 通过；
- `git status` 不包含 `outputs/` 文件变更。

---

## 实施任务

### 任务 1：用精确路径测试驱动配置修改

**文件：**

- 修改：`tests/paper/test_cli.py`
- 修改：`dc_energy_opt/config.py`

- [ ] **步骤 1：添加四个配置路径和两个绘图路径的精确断言**

在 `PaperCliRoutingTests` 中添加：

```python
def test_houston_2020_output_paths_are_track_scoped(self) -> None:
    self.assertEqual(
        HOUSTON_2020.main_output_dir,
        Path("outputs/paper/houston_2020/day_ahead"),
    )
    self.assertEqual(
        HOUSTON_2020.flex_ratio_sensitivity_output_dir,
        Path("outputs/paper/houston_2020/sensitivity/flex_ratio"),
    )
    self.assertEqual(
        HOUSTON_2020.storage_scale_sensitivity_output_dir,
        Path("outputs/paper/houston_2020/sensitivity/storage_scale"),
    )
    self.assertEqual(
        HOUSTON_2020.storage_energy_power_sensitivity_output_dir,
        Path(
            "outputs/paper/houston_2020/sensitivity/"
            "storage_energy_power"
        ),
    )
```

同时把 `test_plot_commands_use_existing_result_paths` 中的两个固定期望改为：

```python
Path("outputs/paper/houston_2020/day_ahead/results/hourly_dispatch.csv")
Path("outputs/paper/houston_2020/day_ahead/results/daily_metrics.csv")
```

- [ ] **步骤 2：运行路径测试并确认预期失败**

运行：

```powershell
conda run -n scip_env python -m unittest tests.paper.test_cli.PaperCliRoutingTests -v
```

预期：新增固定路径测试和绘图默认路径测试因仍返回旧 `outputs/houston_2020_*` 路径而失败；其他路由断言通过。

- [ ] **步骤 3：修改四个默认最终目录**

将 `dc_energy_opt/config.py` 中的 `HOUSTON_2020` 输出字段改为：

```python
main_output_dir=Path("outputs/paper/houston_2020/day_ahead"),
flex_ratio_sensitivity_output_dir=Path(
    "outputs/paper/houston_2020/sensitivity/flex_ratio"
),
storage_scale_sensitivity_output_dir=Path(
    "outputs/paper/houston_2020/sensitivity/storage_scale"
),
storage_energy_power_sensitivity_output_dir=Path(
    "outputs/paper/houston_2020/sensitivity/storage_energy_power"
),
```

- [ ] **步骤 4：运行论文 CLI 测试并确认通过**

运行：

```powershell
conda run -n scip_env python -m unittest tests.paper.test_cli -v
```

预期：7 项测试全部通过；实验命令、绘图命令和 `--output-dir` 分派行为不变。

- [ ] **步骤 5：提交配置与测试**

```powershell
git add -- dc_energy_opt/config.py tests/paper/test_cli.py
git commit -m "refactor: organize paper output paths"
```

### 任务 2：更新当前文档中的输出路径

**文件：**

- 修改：`README.md`
- 修改：`docs/architecture.md`
- 修改：`docs/paper/experiments/houston_2020_experiment.md`
- 修改：`docs/paper/experiments/houston_2020_storage_scale_sensitivity.md`
- 修改：`docs/paper/experiments/houston_2020_storage_energy_power_sensitivity.md`
- 修改：`docs/paper/results/houston_2020_storage_scale_sensitivity_2026-08-10.md`
- 修改：`docs/paper/results/houston_2020_storage_energy_power_sensitivity_2026-08-11.md`

- [ ] **步骤 1：更新架构与运行说明**

根 README 和架构文档使用以下当前结构，不加入旧路径兼容说明：

```text
outputs/
├── paper/
│   └── houston_2020/
│       ├── day_ahead/
│       └── sensitivity/
│           ├── flex_ratio/
│           ├── storage_scale/
│           └── storage_energy_power/
└── career/
```

实验文档中的命令保持不变，只将默认目录、绘图参数示例和目录树替换为批准设计中的精确路径。

- [ ] **步骤 2：更新正式结果报告的相对产物链接**

储能规模报告使用：

```text
../../../outputs/paper/houston_2020/sensitivity/storage_scale/
```

储能能量与功率报告使用：

```text
../../../outputs/paper/houston_2020/sensitivity/storage_energy_power/
```

链接后半部分的 `results/`、`figures/`、`experiments/` 和 `run_metadata.json` 保持不变。

- [ ] **步骤 3：确认当前文档不再引用四个旧目录**

运行：

```powershell
rg -n "outputs/houston_2020_(main|flex_ratio_sensitivity|storage_scale_sensitivity|storage_energy_power_sensitivity)" README.md docs experiments --glob "!docs/archive/**"
```

预期：退出码 1，无匹配。

- [ ] **步骤 4：提交文档更新**

```powershell
git add -- README.md docs/architecture.md docs/paper
git commit -m "docs: update paper output locations"
```

### 任务 3：完整验收并记录结果

**文件：**

- 修改：`docs/development/current-change.md`

- [ ] **步骤 1：验证六个命令的默认路径解析**

运行：

```powershell
conda run -n scip_env python -m unittest tests.paper.test_cli -v
```

预期：7 项测试全部通过，其中四个实验目录和两个绘图文件路径均为批准设计中的精确路径。

- [ ] **步骤 2：运行编译和完整测试**

```powershell
conda run -n scip_env python -m compileall -q dc_energy_opt experiments scripts tests
conda run -n scip_env python -m unittest discover -s tests -t .
```

预期：编译退出码 0；129 项测试通过，Windows 无符号链接权限时仅既有 4 项符号链接测试跳过。

- [ ] **步骤 3：验证文档、差异和输出目录未被修改**

```powershell
rg -n "outputs/houston_2020_(main|flex_ratio_sensitivity|storage_scale_sensitivity|storage_energy_power_sensitivity)" README.md docs experiments --glob "!docs/archive/**"
git diff --check
git status --short
```

预期：旧路径搜索无匹配；`git diff --check` 退出码 0；`git status --short` 不包含 `outputs/`。

- [ ] **步骤 4：在本文件记录实际测试数量、跳过数量和检查结果**

只记录实际命令输出，不生成正式实验结果，不创建新的 `outputs/` 目录。

- [ ] **步骤 5：提交验收记录**

```powershell
git add -- docs/development/current-change.md
git commit -m "docs: record output path verification"
```
