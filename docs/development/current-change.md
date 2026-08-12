# 当前变更：统一论文输出路径

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
