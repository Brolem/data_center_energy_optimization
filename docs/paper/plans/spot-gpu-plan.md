# Spot GPU 算电协同实施计划

> **供执行代理使用：** 必须使用 `executing-plans` 技能逐项实施。本计划以复选框跟踪进度。

**目标：** 交付一个仅属于论文线、可复现的 GPU 调度研究：在 ERCOT Houston 日前市场价格下，滚动调度 Alibaba HP/Spot GPU 作业；以运行成本为首要目标，以系统风光时段匹配和消费侧碳排为次级结果。

**架构：** 所有新增代码仅位于 `experiments/paper/ercot_2025_spot_gpu/`，不得导入、读取、复制或修改求职线命名空间。数据层生成四个 1,062 小时输入和一个固定的 trace 重放片段；调度层组合 HP 风险预留、满足 gang 约束的 Spot 作业与 GPU 功率模型；评价层生成四季策略矩阵和可审计的论文产物。

**技术栈：** Python 3.13、pandas、NumPy、PySCIPOpt、标准库 `unittest`、CSV/JSON、Markdown。

---

## 不可变更的研究规则

- 既有年度表的 `timestamp_utc` 是**小时结束时刻**。论文输入新增 `interval_start_utc` 与 `interval_end_utc`；市场值不得整体平移六小时。
- 每个季节窗口均为 171 小时上下文、720 小时核心期、171 小时结算尾段。`H=3` 是额外完成宽限，而不是尾段总长度。
- 主实验的 Spot 作业资格为 `D_max=168 h`。只有预注册可行性试验未通过、且尚未比较任何成本/风光/碳结果时，才允许统一改为 `72 h`。
- 调度器只使用次日 DAM 价格、截止时刻前可得的风光预测，以及仅由过去数据构建的碳预测。实际风、光和碳只用于评价。
- 原始下载文件始终忽略；仅提交脚本、来源及哈希清单和紧凑的论文输入。完整运行结果继续位于被忽略的 `outputs/` 目录。
- 论文表述为系统级可再生能源**时段匹配**，而非数据中心本地新能源消纳；表述为消费侧碳，而非边际碳。

## 五阶段交付图

| 阶段 | 交付物 | 测试 |
| --- | --- | --- |
| 1. 输入合同 | 四个带哈希的 1,062 小时季节输入 | `test_inputs.py` |
| 2. 算力合同 | 固定 Alibaba 重放片段、HP 容量表与功率情景 | `test_compute_contract.py` |
| 3. 调度器 | B0/B1/B2/P 滚动策略及 gang 可行性恢复 | `test_scheduler.py` |
| 4. 试验与矩阵 | 可行性结论、四季策略结果与图表 | `test_replay_integration.py` |
| 5. 可复现性交付 | 核验后的结果记录与论文表格 | 四个专用测试模块及既有论文/共享测试 |

## 阶段 1：建立论文输入合同

**文件：**

- 新建：`experiments/paper/ercot_2025_spot_gpu/{__init__,config,types,energy}.py`
- 新建：`scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py`
- 新建：`tests/paper/ercot_2025_spot_gpu/{__init__,test_inputs}.py`
- 修改：`.gitignore`、`experiments/paper/cli.py`、`data/energy/README.md`
- 修改：`docs/paper/experiments/ercot_2025_houston_spot_gpu_experiment.md`、`docs/development/paper/ercot_2025_houston_spot_gpu_energy_inputs.md`

- [ ] **步骤 1：编写一个精简的数据合同测试模块。**

```python
import unittest
from datetime import date

from experiments.paper.ercot_2025_spot_gpu.energy import (
    build_study_window_rows,
    to_energy_interval,
)


class PaperInputTests(unittest.TestCase):
    def test_end_timestamp_defines_the_preceding_one_hour_interval(self) -> None:
        interval = to_energy_interval({"timestamp_utc": "2025-01-01T07:00:00Z"})
        self.assertEqual(interval.interval_start_utc, "2025-01-01T06:00:00Z")
        self.assertEqual(interval.interval_end_utc, "2025-01-01T07:00:00Z")

    def test_winter_window_has_exact_context_core_and_tail_sizes(self) -> None:
        rows = build_study_window_rows(
            annual_2025=synthetic_annual_rows(),
            december_2024=synthetic_december_rows(),
            window_start=date(2025, 1, 1),
        )
        self.assertEqual(len(rows), 1062)
        self.assertEqual(sum(row["period_role"] == "context" for row in rows), 171)
        self.assertEqual(sum(row["period_role"] == "core" for row in rows), 720)
        self.assertEqual(sum(row["period_role"] == "settlement_tail" for row in rows), 171)

    def test_rejects_forecast_issued_after_its_daily_cutoff(self) -> None:
        with self.assertRaisesRegex(ValueError, "published after cutoff"):
            build_study_window_rows(late_forecast_rows=late_forecast_rows())
```

- [ ] **步骤 2：先确认测试失败，再实现最小的论文专用数据层。**

执行：`conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_inputs -v`

预期（实现前）：因模块尚不存在而导入失败。

建立不可变配置：`core_hours=720`、`context_hours=171`、`tail_hours=171`、`max_spot_duration_h=168`、`completion_slack_h=3`、`cost_guardrail_fraction=0.01`、`hp_risk_quantile=0.95`、`hp_calibration_hours=336`。在 `experiments.paper.cli` 新增 `spot-gpu replay`、`spot-gpu pilot` 与 `spot-gpu report`，不得改变既有 Houston 2020 命令。

输入 CSV 固定为：

```python
ENERGY_INPUT_COLUMNS = (
    "window_id", "window_hour", "period_role",
    "interval_start_utc", "interval_end_utc", "local_date",
    "dam_lz_houston_usd_per_mwh",
    "erco_solar_generation_mwh", "erco_wind_generation_mwh",
    "erco_consumed_co2_intensity_lbs_per_kwh",
    "forecast_issue_utc", "forecast_target_end_utc",
    "forecast_system_wind_hsl_mw", "forecast_system_solar_hsl_mw",
    "forecast_consumed_co2_lbs_per_kwh",
)
```

准备脚本生成 `2025-01-01_30d_d168_h3_energy.csv`、`2025-04-01_30d_d168_h3_energy.csv`、`2025-07-01_30d_d168_h3_energy.csv`、`2025-10-01_30d_d168_h3_energy.csv` 和 `inputs_manifest.json`。清单记录来源与输出 SHA-256、预测截止规则、HSL 报告编号、仅使用过去数据的碳预测规则和缺失值数量；不记录访问令牌、原始数据或本地绝对路径。

来源清单必须列出 ERCOT DAM `np4-180-er`、风电预测 `NP4-732-CD`（[产品页](https://www.ercot.com/mp/data-products/data-product-details?id=NP4-732-CD)）和光伏预测 `NP4-737-CD`（[产品页](https://www.ercot.com/mp/data-products/data-product-details?id=NP4-737-CD)），并明确 HSL 预测不能与 EIA 实际发电量直接作为同一预测误差口径评价。

- [ ] **步骤 3：原始文件保持忽略，只提交紧凑输入。**

将宽泛的输出忽略规则替换为下列规则；同时添加 2024 DAM 原始归档和 ERCOT 风光预测原始目录的忽略项。

```gitignore
outputs/*
!outputs/paper/
!outputs/paper/ercot_2025_houston_spot_gpu/
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/*.csv
!outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/*.json
```

将两份论文数据文档从过时的 723 小时描述更新为 1,062 小时合同；保留既有共享 2025 年度表与旧生成器行为。

- [ ] **步骤 4：运行测试并提交本阶段。**

执行：`conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_inputs tests.shared.test_ercot_2025_energy tests.paper.test_cli -v`

预期：所选测试全部通过。

```powershell
git add .gitignore data/energy/README.md scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py experiments/paper/ercot_2025_spot_gpu tests/paper/ercot_2025_spot_gpu/test_inputs.py experiments/paper/cli.py docs/paper/experiments/ercot_2025_houston_spot_gpu_experiment.md docs/development/paper/ercot_2025_houston_spot_gpu_energy_inputs.md outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs
git commit -m "feat: prepare paper spot gpu inputs"
```

## 阶段 2：固化算力合同

**文件：**

- 新建：`experiments/paper/ercot_2025_spot_gpu/{workload,power}.py`
- 新建：`tests/paper/ercot_2025_spot_gpu/test_compute_contract.py`
- 新建：`docs/paper/data/{alibaba_2026_spot_gpu_replay_contract,gpu_power_assumptions}.md`
- 修改：`experiments/paper/ercot_2025_spot_gpu/types.py`

- [ ] **步骤 1：编写一个合并的工作负载与功率测试模块。**

```python
import unittest

from experiments.paper.ercot_2025_spot_gpu.power import PowerModel
from experiments.paper.ercot_2025_spot_gpu.workload import (
    make_spot_job,
    realized_hp_reservation,
    select_replay_core,
)


class ComputeContractTests(unittest.TestCase):
    def test_frozen_core_uses_median_eligible_spot_gpu_hours(self) -> None:
        selection = select_replay_core(normalized_jobs, core_hours=720, max_duration_h=168)
        self.assertEqual(selection.core_start_seconds, 3_369_600)
        self.assertEqual(selection.core_end_seconds, 5_961_600)

    def test_deadline_adds_duration_and_h(self) -> None:
        job = make_spot_job(submit_hour=10, duration_seconds=7_201, gpu_count=8)
        self.assertEqual(job.required_run_hours, 3)
        self.assertEqual(job.deadline_hour, 16)

    def test_hp_and_power_accounting_are_model_specific(self) -> None:
        self.assertEqual(realized_hp_reservation([hp_job], 4).loc[1, "A100-SXM4-80GB"], hp_job.gpu_count)
        power = PowerModel.baseline().facility_mw({"A100-SXM4-80GB": 10})
        self.assertAlmostEqual(power, 0.003864)
```

- [ ] **步骤 2：确认失败，再实现 trace 与功率合同。**

执行：`conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_compute_contract -v`

预期（实现前）：因模块尚不存在而导入失败。

标准化规则为 `gpu_count = gpu_request * worker_num`、`submit_hour = floor(submit_time / 3600)`、`required_run_hours = ceil(duration / 3600)`。HP 不虚构截止期；Spot 使用 `deadline_hour = submit_hour + required_run_hours + H`。以立即开始代理构建 HP 容量并包含 core 前已提交的 HP；以固定 EDF 预热重建 inherited Spot 状态，所有策略共用该状态。

在所有可选 720 小时块上以“可用 Spot GPU-hours 最接近中位数”选择工作负载 core，平局取最早开始。将选择规则、来源哈希、开始秒 `3,369,600`、结束秒 `5,961,600`、7,050 个符合资格作业、122,773.2 GPU-hours 和 10 个超过 168 小时的排除作业写入 `workload_selection.json`。

功率只实现增量设施功率：

\[
\Delta P_t=PUE\,\kappa_{IT}\sum_m n_{m,t}u_mP_m^{TDP}.
\]

`(PUE, IT-overhead, active-power fraction)` 低/基准/高情景分别为 `(1.10, 1.00, 0.50)`、`(1.20, 1.15, 0.70)`、`(1.40, 1.30, 0.90)`。命名 GPU 必须在文档给出公开 TDP 来源；`GPU-series-*` 只能标为情景假设，不能标为测量值。

- [ ] **步骤 3：运行测试并提交本阶段。**

执行：`conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_compute_contract -v`

预期：所选测试全部通过。

```powershell
git add experiments/paper/ercot_2025_spot_gpu/workload.py experiments/paper/ercot_2025_spot_gpu/power.py experiments/paper/ercot_2025_spot_gpu/types.py tests/paper/ercot_2025_spot_gpu/test_compute_contract.py docs/paper/data outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/workload_selection.json
git commit -m "feat: freeze spot gpu compute contract"
```

## 阶段 3：实现并验证滚动调度器

**文件：**

- 新建：`experiments/paper/ercot_2025_spot_gpu/{hp_forecast,envelope,scheduler}.py`
- 新建：`tests/paper/ercot_2025_spot_gpu/test_scheduler.py`
- 新建：`docs/paper/experiments/ercot_2025_spot_gpu_feasibility_gate.md`

- [ ] **步骤 1：用一个调度器测试模块覆盖三条关键不变量。**

```python
import unittest

from experiments.paper.ercot_2025_spot_gpu.scheduler import run_replay, schedule_one_day


class SchedulerTests(unittest.TestCase):
    def test_day_d_sees_only_next_24_dam_prices_and_past_carbon(self) -> None:
        decision = schedule_one_day(state, energy_rows, decision_hour=48, policy="P")
        self.assertEqual(decision.price_information_end_hour, 71)
        self.assertEqual(decision.carbon_training_end_hour, 47)

    def test_every_recovered_job_respects_release_deadline_and_gang_capacity(self) -> None:
        replay = run_replay(synthetic_case, policy="B2")
        self.assertTrue(replay.job_completion["is_deadline_feasible"].all())
        self.assertTrue(replay.hourly["spot_capacity_excess_gpus"].eq(0).all())

    def test_realized_hp_has_priority_and_proposed_policy_obeys_guardrail(self) -> None:
        replay = run_replay(synthetic_case, policy="P")
        self.assertTrue(replay.hourly["hp_capacity_invasion_gpus"].eq(0).all())
        self.assertLessEqual(replay.cost_usd, replay.price_optimum_usd + replay.cost_guardrail_usd)
```

- [ ] **步骤 2：确认失败，再在同一调度路径中实现全部策略。**

执行：`conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_scheduler -v`

预期（实现前）：因模块尚不存在而导入失败。

每日决策边界按 GPU 型号，以“已知仍在运行的 HP 占用”和“前 336 个已实现 HP 小时的 0.95 分位”较大者预测 HP，并按物理容量截断。碳预测为前 336 个已发布 EIA 碳值的同小时中位数；不足 168 个非空历史值时拒绝该决策。两类审计训练集均在上一个小时结束。

仅将 `(gpu_model, gpu_count, release_hour, deadline_hour, required_run_hours)` 完全相同的作业合并为整数 cohort。包络每小时必须安排完整 GPU gang，并通过 EDF 恢复到具体 job ID。恢复不能满足时抛出具名不可行错误，绝不输出连续松弛结果。

同一重放循环内实现：B0 静态配额 EDF；B1 风险预留 EDF；B2 风险预留+次日价格；P 先求 B2 价格最优值，再施加 `cost <= optimum + max(0.01, 0.01 * abs(optimum))`，随后最大化预测风光匹配并最小化只基于过去的碳预测。未来时段只用于可行性、没有价格系数。每次只提交 24 小时，遇到实现 HP 时抢占 Spot，传递未完成 Spot，并在核心期第 720 小时后阻止新 Spot 到达。

- [ ] **步骤 3：运行调度器测试并提交本阶段。**

执行：`conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_scheduler -v`

预期：所选测试全部通过。

```powershell
git add experiments/paper/ercot_2025_spot_gpu/hp_forecast.py experiments/paper/ercot_2025_spot_gpu/envelope.py experiments/paper/ercot_2025_spot_gpu/scheduler.py tests/paper/ercot_2025_spot_gpu/test_scheduler.py docs/paper/experiments/ercot_2025_spot_gpu_feasibility_gate.md
git commit -m "feat: add rolling spot gpu scheduler"
```

## 阶段 4：运行可行性试验与季节评价矩阵

**文件：**

- 新建：`experiments/paper/ercot_2025_spot_gpu/{evaluation,reporting,run}.py`
- 新建：`tests/paper/ercot_2025_spot_gpu/test_replay_integration.py`
- 新建：`docs/paper/results/ercot_2025_houston_spot_gpu_results.md`
- 修改：`experiments/paper/cli.py`、`docs/paper/README.md`

- [ ] **步骤 1：编写一个基于小样本的端到端测试。**

```python
import tempfile
import unittest
from pathlib import Path

from experiments.paper.ercot_2025_spot_gpu.run import run_study


class ReplayIntegrationTests(unittest.TestCase):
    def test_fixture_run_writes_all_policies_metrics_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = run_study(input_dir=fixture_inputs, output_dir=Path(temporary_directory))
            self.assertEqual(set(result.case_metrics["policy"]), {"B0", "B1", "B2", "P"})
            self.assertIn("spot_incremental_facility_cost_usd", result.case_metrics)
            self.assertIn("renewable_matching_mwh_weighted", result.case_metrics)
            self.assertIn("consumed_co2_kg", result.case_metrics)
            self.assertTrue((Path(temporary_directory) / "run_metadata.json").is_file())
```

- [ ] **步骤 2：确认失败，再实现评价与统一运行器。**

执行：`conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_replay_integration -v`

预期（实现前）：因模块尚不存在而导入失败。

评价只使用实际 EIA 信号：增量设施 MWh、DAM USD 成本、MWh 加权系统风光匹配和消费侧碳 kg（`lbs/kWh × 453.59237`）。输出小时调度、日/案例指标、作业完成、HP 预留审计、求解器审计与 `run_metadata.json`。元数据包括输入哈希、选定 trace core、跨域地点声明、决策截止时间、策略、功率情景、求解状态/缺口及资格阈值。

完整结果前先执行冬季试验，四种策略均参与。只有每次日求解在 300 秒内获得接受状态、冬季重放在 8 小时内结束、截止期恢复失败为零、HP 侵占为零时才通过。必须先保存可行性结论，再生成策略对比表。若失败，统一切换为 72 小时资格、重建输入及选择清单，并重复阶段 2–4 后才可比较。

- [ ] **步骤 3：运行测试，再运行完整季节矩阵。**

执行：`conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_replay_integration tests.paper.test_cli -v`

预期：所选测试全部通过。

执行：`conda run -n scip_env python -m experiments.paper spot-gpu pilot --input-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs --output-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead`

预期：生成带有明确通过/失败结论的 `pilot_feasibility.json`。

仅在 `pass=true` 后执行：`conda run -n scip_env python -m experiments.paper spot-gpu replay --input-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs --output-dir outputs/paper/ercot_2025_houston_spot_gpu/day_ahead`。

- [ ] **步骤 4：提交评价阶段。**

```powershell
git add experiments/paper/ercot_2025_spot_gpu/evaluation.py experiments/paper/ercot_2025_spot_gpu/reporting.py experiments/paper/ercot_2025_spot_gpu/run.py experiments/paper/cli.py tests/paper/ercot_2025_spot_gpu/test_replay_integration.py docs/paper/results/ercot_2025_houston_spot_gpu_results.md docs/paper/README.md
git commit -m "feat: evaluate paper spot gpu study"
```

## 阶段 5：完成可复现性与论文交付

**文件：**

- 修改：`docs/paper/results/ercot_2025_houston_spot_gpu_results.md`
- 修改：`docs/paper/README.md`

- [ ] **步骤 1：运行三层测试与完整性检查。**

执行：`conda run -n scip_env python -m unittest tests.paper.ercot_2025_spot_gpu.test_inputs tests.paper.ercot_2025_spot_gpu.test_compute_contract tests.paper.ercot_2025_spot_gpu.test_scheduler tests.paper.ercot_2025_spot_gpu.test_replay_integration -v`

预期：四个论文专用测试模块全部通过。

执行：`conda run -n scip_env python -m unittest discover -s tests/paper -t . -v`

预期：论文线测试全部通过。

执行：`conda run -n scip_env python -m unittest discover -s tests/shared -t . -v`

预期：共享测试全部通过。

执行：`git diff --check`

预期：无输出且退出码为 0。

执行：`git check-ignore -v data/energy/ercot_2024_historical_dam_load_zone_and_hub_prices.zip data/energy/ercot_2025_public_wind_solar_forecasts`

预期：两个原始路径都被忽略。

- [ ] **步骤 2：生成结果记录并提交。**

结果记录必须包含可行性结论、哈希、准确命令、求解状态/缺口、来源和模型限制、核心/尾段核算、被排除/未完成的工作以及各策略的季节结果。禁止出现以下表述：`local renewable consumption`、`local wind`、`local solar`、`marginal carbon`、`observed HP SLO`、`observed GPU power`、`actual Houston workload`。

```powershell
git add docs/paper/results/ercot_2025_houston_spot_gpu_results.md docs/paper/README.md
git commit -m "docs: record verified spot gpu results"
```

## 自检结论

- 原十项任务已压缩为五个交付阶段，每一阶段只需一次提交。
- 测试压缩为四个专用模块：输入合同、算力合同、调度器不变量和小样本端到端回放；既有论文/共享测试只在最后作为回归门槛。
- 已覆盖顶层设计的全部要求：时间语义、原始数据排除、trace 边界、HP 风险预留、gang 可行性、成本优先策略、风光/碳信息边界、168→72 小时规则、四季评价和受限表述。
- 本计划不包含求职线实现或文档。
