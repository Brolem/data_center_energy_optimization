# 仓库重组最终报告

## 1. 结论与范围

本次重组把 Houston 2020 跨日确定性日前主实验整理为职责清晰、可复现、可独立验证的项目结构。正式包统一为 `dc_energy_opt`，正式入口为 `run_day_ahead_experiment.py`，`run_first_version.py` 只保留旧参数转换功能，Phoenix 历史场景移入独立归档。

重组没有修改数学模型、参数、正式数据字节、四组算例或实验范围。冻结基线与新正式输出的三张核心结果表逐列等价；正式入口与旧兼容入口也逐列等价。当前工作只保留在本地分支 `codex/reorganize-repository`，尚未合并、尚未推送，工作区根目录和 GitHub 仓库名称均未改名。

## 2. 最终结构

```text
data_center_energy_optimization/
├── dc_energy_opt/
│   ├── config.py
│   ├── data/
│   ├── optimization/
│   ├── experiments/
│   └── reporting/
├── data/
│   ├── workload/google_2019_28d_5min.csv
│   └── energy/houston_2020_may_hourly.csv
├── archive/legacy_phoenix/
├── scripts/
│   ├── prepare_houston_2020_energy.py
│   └── verify_reorganization_equivalence.py
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
├── run_day_ahead_experiment.py
└── run_first_version.py
```

正式输出固定为：

```text
outputs/houston_2020_main/
├── inputs/
├── results/
├── figures/
├── models/
└── run_metadata.json
```

## 3. 实施提交

| 提交 | 内容 | 结果 |
| --- | --- | --- |
| `b33b1ee` | 设计项目结构与命名重构 | 固定项目名、包名、入口、数据、输出和归档边界。 |
| `0e3c449` | 制定项目结构重构实施计划 | 固定分批实施、TDD、评审和数值验收流程。 |
| `3179a3f` | 实现 Houston 跨日确定性日前主实验 | 建立四算例、24+3 小时滚动日前和 28 天主实验基线。 |
| `dda43b3` | 澄清日前前视任务语义 | 固定次日前视柔性任务的终端处理策略并补回归验证。 |
| `b69f521` | 重命名正式优化包 | 将正式代码统一到 `dc_energy_opt`。 |
| `cff02e7` | 拆分窗口模型与滚动调度 | 分离单窗口建模、跨日状态与滚动编排。 |
| `63c811c` | 分层正式数据并归档历史场景 | 建立工作负载、能源数据目录并隔离 Phoenix 历史内容。 |
| `9f293ed` | 固定正式能源数据换行 | 固定 Houston 数据的仓库与工作树原始字节。 |
| `c383ce7` | 拆分指标计算与结果绘图 | 分离结果计算和图形输出职责。 |
| `781200e` | 按算例与窗口分层保存 LP | 将两级目标 LP 固定到算例和滚动窗口目录。 |
| `60661b5` | 抽取主实验与事务化发布 | 建立主实验编排、输入快照和整体输出发布。 |
| `2995045` | 拒绝输入与输出目录冲突 | 在任何读取、求解或暂存前阻止输入被输出覆盖。 |
| `d0daf13` | 保留实验元数据相对路径 | 运行时解析路径，但元数据保留调用者传入形式。 |
| `ea2c981` | 强化事务路径与输入快照安全 | 防止清理符号链接或目录联接目标，完善暂存清理，并改为先快照后加载。 |
| `04c8dbf` | 建立正式实验入口与兼容层 | 新增正式 CLI，旧入口缩减为参数转换层。 |
| `5982c7b` | 按模块职责重组测试 | 将正式测试整理为单元与集成两层。 |
| `ecb7a75` | 统一项目文档与运行说明 | 建立扁平 `docs/` 和根目录 README。 |
| `adc5139` | 修正兼容入口路径参数转发 | 确保以 `-` 开头的路径和值能完整传给正式入口，并补默认入口验收。 |
| 本报告所在提交 | 验证重构结果数值等价 | 新增等价脚本、最终验证报告，并修复兼容提示的 Windows 终端编码问题。 |

## 4. 执行中发现与采用的修正

下表中的“数值影响”均指对数学模型、输入参数和三张核心结果表非计时字段的影响。

| 发现 | 采用方案 | 理由 | 验证 | 数值影响 |
| --- | --- | --- | --- | --- |
| 次日 3 小时前视中，柔性到达若在当前截断窗口创建，会缩短其完整到期域；`_prewarm_carry_in` 的返回类型标注也与实际二元结构不一致。 | 前视段只承担 70% 非柔性最低负荷，30% 柔性任务在下一日完整窗口创建；修正返回类型标注并加入源码注释。 | 保持任务只创建一次，并让每项柔性任务获得完整 3 小时最大延迟域；这是滚动窗口的终端策略，不是任务削减。 | `test_preview_flexible_arrival_is_created_only_next_day` 和 `test_prewarm_carry_in_return_annotation_matches_structure`。 | 0；冻结基线在该语义固定后建立。 |
| Windows `core.autocrlf` 会改变 Google 工作负载工作树字节，原始 SHA256 无法作为稳定复现标识。 | 在 `.gitattributes` 对 `data/workload/google_2019_28d_5min.csv` 设置 `-text`。 | 让 Git 不再对正式输入执行换行转换，仓库对象和工作树保持相同字节。 | 原始字节 SHA256 回归测试和 672 小时聚合测试。 | 0；恢复并固定基线字节。 |
| Houston CSV 的仓库对象为 LF、目标正式文件为 CRLF，仓库对象与工作树哈希不一致；常规文本差异检查还会把 CRLF 显示为行尾噪声。 | 对 Houston CSV 设置 `-text -diff`，生成脚本显式使用 CRLF，并同时校验规范化文本和原始字节 SHA256。 | `-text` 固定原始字节，`-diff` 避免 Git 文本差异层改写或把 CR 显示为尾随空白；数据加载器仍按 CSV 读取。 | `test_committed_houston_file_preserves_raw_sha256`、换行与生成结果回归测试。 | 0；最终字节与冻结基线完全一致。 |
| 输入文件位于输出目录内或与输出路径相同时，事务发布可能覆盖仍需读取的输入。 | 在数据读取、求解和暂存之前，解析并拒绝 `workload_data`、`energy_data` 与 `output_dir` 的包含或相等冲突。 | 失败必须发生在任何副作用之前，不能依靠后续回滚恢复输入。 | 工作负载位于输出根、能源位于 `inputs/`、输入等于文件输出三类集成测试。 | 0；只新增无效路径防护。 |
| 路径安全校验需要使用解析后的绝对路径，但若直接写入元数据，会把调用者的相对路径变成机器相关绝对路径。 | 安全比较使用解析路径，`run_metadata.json` 保留调用者传入的相对路径文本。 | 同时满足安全判断与跨机器可复现元数据。 | `test_relative_input_paths_remain_relative_in_metadata`。 | 0；只改变元数据路径表示。 |
| 事务清理若先解析路径再递归删除，可能沿符号链接或 Windows 目录联接删除外部目标；`mkdtemp` 后、进入清理区前的目录创建失败会遗留暂存目录。 | 校验原始目录项的父目录和名称；符号链接、断链和目录联接只删除目录项本身；所有 `mkdtemp` 后操作纳入 `try/finally`。 | 清理边界必须以原始目录项为准，且每个暂存创建后的失败点都必须可回收。 | 普通目录拒绝、只读文件、符号链接、断链、目录联接、第二和第三子目录创建失败等集成测试；当前 Windows 环境的目录联接测试通过，两个需要创建符号链接的测试因系统权限跳过。 | 0；只强化输出事务安全。 |
| 若先加载源输入、后复制发布快照，源文件在两步之间变化时，模型实际读取内容与已发布 `inputs/` 可能不一致。 | 冲突校验后先复制输入到暂存快照，再从该不可变快照加载、求解和发布；元数据仍记录调用者路径。 | 发布的输入必须就是模型实际读取的输入。 | `test_model_and_published_input_use_same_immutable_snapshot`，覆盖复制前后源文件变化。 | 0；正式固定输入未变化。 |
| 使用 `python -m unittest discover -s tests -t .` 时，顶层 `tests/` 缺少包标记会破坏稳定发现。 | 新增空的 `tests/__init__.py`，保留 `unit/`、`integration/` 各自包标记。 | 明确发现根和导入路径，避免依赖当前目录偶然行为。 | 使用带 `-t .` 的正式发现命令。 | 0；仅测试基础设施。 |
| 实施计划中的旧测试文件描述与迁移时仓库实际文件名存在差异，不能按名称推测迁移。 | 实际读取并逐项迁移当时存在的 `tests/test_cost_optimization.py`、`tests/test_refactor_regression.py`、`tests/test_rolling_day_ahead.py` 和 `tests/test_runner_entrypoint.py`；模型测试进入 `unit/test_window_model.py`，滚动测试进入 `integration/test_rolling_day_ahead.py`，配置、数据和入口断言按职责拆分。 | 以 Git 树中真实文件和测试方法为准，避免遗漏或重复。 | 重组前后逐方法核对，最终正式发现覆盖单元与集成目录。 | 0；测试位置改变，断言语义保留。 |
| 旧入口曾重新导出参数、数据、模型、滚动、绘图和实验内部接口，使过渡文件继续承担正式 API 职责。 | `run_first_version.py` 只解析四个旧参数并调用正式入口，不重新导出内部接口。 | 兼容层应可删除、职责单一，正式接口只由 `dc_energy_opt` 提供。 | `test_legacy_entrypoint_does_not_export_internal_interfaces` 和正式包导出测试。 | 0；调用同一正式实验函数。 |
| 旧入口把选项和值拆成两个参数时，以 `-` 开头的路径会被正式解析器当作新选项。 | 转发为 `--workload-data=<value>`、`--energy-data=<value>`、`--output-dir=<value>` 三个单字符串。 | `argparse` 能把等号后的完整内容确定为该选项的值。 | `test_legacy_dash_prefixed_paths_reach_the_formal_experiment`。 | 0；只修复参数边界。 |
| 只测试显式参数不能证明旧入口无参数运行与正式默认值完全一致。 | 比较两个解析器的三条默认路径和日志开关，并比较两入口最终实验调用。 | 默认入口是复现实验的主要路径，必须单独验收。 | `test_legacy_defaults_map_exactly_to_formal_defaults`。 | 0；确认现有默认值相同。 |
| 编译检查最初只覆盖正式入口，未覆盖仍需工作的旧兼容入口。 | `compileall` 同时包含 `run_day_ahead_experiment.py` 和 `run_first_version.py`。 | 兼容层仍是公开迁移路径，语法错误必须在验收中发现。 | 最终 `compileall` 命令。 | 0；仅扩大静态编译范围。 |
| Windows 下 `conda run` 按 UTF-8 解码子进程输出，而旧入口中文迁移提示按本地代码页写入管道；解码得到 `U+FFFD` 后，Conda 外层 GBK 输出无法编码该字符，完整求解完成后仍返回 1。 | 将迁移提示改为纯 ASCII：`run_first_version.py is deprecated; use run_day_ahead_experiment.py.`。 | 消除不同 Windows 代码页之间的歧义，同时保留明确迁移指引；正式入口本来只输出 ASCII 安全的 JSON 和英文标题。 | RED：迁移提示精确值与 `isascii()` 两项测试失败；GREEN：两项测试通过，隔离 `conda run` 返回 0，完整旧入口返回 0。 | 0；只影响终端提示编码显示，正式与兼容三表最大绝对差仍为 0。 |
| 重组后缺少可重复执行的逐列数值证明，人工查看总成本不足以发现列顺序、文本、行数或局部数值变化。 | 新增 `scripts/verify_reorganization_equivalence.py`，显式选择 `legacy` 或 `current` 布局；列名和顺序、行数、文本和布尔值精确比较，非计时数值使用 `atol=1e-9`、`rtol=0`，四个明确计时字段只要求有限且非负。 | 将重组“不改变实验结果”转化为自动化、可失败的验收条件，并可复用于正式入口和兼容入口。 | 5 个脚本测试覆盖容差内差异、当前布局互比、列顺序、行数、文本、超容差数值、负计时和无限计时。 | 0；验证工具不参与求解。 |

## 5. 正式数据与输出验收

### 5.1 数据字节

| 文件 | SHA256 |
| --- | --- |
| `data/workload/google_2019_28d_5min.csv` | `3F2A240BCBCC97FE74D3609381029C03AAD97D4ADF28B753D2B058CBD448D20D` |
| `data/energy/houston_2020_may_hourly.csv` | `1E075995C24141BA358B0452EE829C6006FAB25B3E83C6868587EDD837BDD7E0` |

主仓冻结基线 `outputs/repository_reorganization_baseline/` 未删除、未移动、未修改。

### 5.2 正式入口

默认命令完整运行耗时 15.904 秒，输出根目录正好包含 `inputs/`、`results/`、`figures/`、`models/` 和 `run_metadata.json`。

| 验收项 | 实际值 |
| --- | ---: |
| `hourly_dispatch.csv` | 2,700 行 |
| `daily_metrics.csv` | 112 行 |
| `case_metrics.csv` | 4 行 |
| LP | 232 个 |
| PNG | 5 张 |

四组算例状态与运行成本为：

| 算例 | 状态 | 运行成本（CNY） | 相对 `renewables_only` 节省率 |
| --- | --- | ---: | ---: |
| `renewables_only` | `optimal` | 1,137,926.2633406164 | 0% |
| `renewables_shift` | `optimal` | 1,108,096.329888567 | 2.621429385457467% |
| `renewables_storage` | `optimal` | 1,123,755.8163364362 | 1.2452869276942349% |
| `joint` | `optimal` | 1,094,637.0544977891 | 3.804219151752669% |

### 5.3 数值等价

冻结旧布局到新正式布局：

| 结果表 | 行数 | 非计时字段最大绝对差 |
| --- | ---: | ---: |
| `hourly_case_results.csv` → `hourly_dispatch.csv` | 2,700 | 0 |
| `daily_case_metrics.csv` → `daily_metrics.csv` | 112 | 0 |
| `case_metrics.csv` → `case_metrics.csv` | 4 | 0 |

旧兼容入口完整运行耗时 16.241 秒并返回 0。正式入口与兼容入口的新布局三表行数分别为 2,700、112 和 4，非计时字段最大绝对差均为 0；兼容输出同样包含 232 个 LP 和 5 张 PNG。

## 6. 测试与静态验收

- 正式测试：97 项通过，2 项因当前 Windows 账户没有创建符号链接权限而跳过；对应的 Windows 目录联接保护测试通过。
- 归档测试：11 项通过。
- 97 项由重组完成时的 91 项、5 项等价脚本测试和 1 项终端编码回归测试组成。
- `compileall` 覆盖 `dc_energy_opt`、`scripts` 和两个入口。
- `pip check` 验证环境依赖关系。
- `git diff --check HEAD` 验证差异格式。
- 旧包名、旧正式数据名和旧能源生成脚本名不再出现在正式包、正式测试、正式脚本、正式入口和正式实验文档中；`run_first_version.py` 仅作为明确保留的兼容入口，Phoenix 仅存在于 `archive/legacy_phoenix/`。
- `docs/` 保持单层结构。

## 7. 未执行事项

- 未合并本地分支。
- 未推送任何提交。
- 未重命名 `D:\Users\Desktop\google2019_scip_first_version` 工作区根目录。
- 未修改 GitHub 远程仓库名称。
- 未提交 `outputs/` 下的可重建结果。

根目录与 GitHub 仓库的最终重命名按既定决定留到内部重构验收之后单独执行。
