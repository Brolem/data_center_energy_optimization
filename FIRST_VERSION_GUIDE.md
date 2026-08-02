# Houston 2020 跨日确定性日前优化使用指南

## 1. 主实验范围

默认入口运行 2020 年 5 月 1–28 日的 Houston 2020 主实验。模型每天求解 24 小时正式时段与次日 3 小时前视时段，固化前 24 小时决策；5 月 29 日 00:00–02:00 只用于完成第 28 天遗留任务，不产生新任务。

正式对比仅包含四组风光算例：

| 算例 | 算力转移 | 储能 | 风光 |
|---|---:|---:|---:|
| `renewables_only` | 否 | 否 | 是 |
| `renewables_shift` | 是 | 否 | 是 |
| `renewables_storage` | 否 | 是 | 是 |
| `joint` | 是 | 是 | 是 |

成本节省率以 `renewables_only` 为基准。纯电网算例不进入正式结果。

汇总字段 `operating_cost_cny` 等于 672 小时分析期成本与 3 小时结算尾段成本之和；4 月 30 日预热成本不计入。尾段必须计费，避免通过把第 28 天任务推到分析期之外来虚减成本。

## 2. 数据与时间对齐

- 算力输入：`data/instance_usage_grouped_300_seconds_month.csv`，8,064 个五分钟点聚合为连续 672 小时。
- 能源输入：`data/houston_2020_main_experiment_energy_scenario.csv`，严格包含 699 小时：4 月 30 日预热 24 小时、5 月 1–28 日分析期 672 小时、5 月 29 日结算尾段 3 小时。
- 光伏：NSRDB 五分钟数据经 PVWatts v8 计算，再按每小时 12 点平均。
- 风电：NREL WIND Toolkit 的 80 m 五分钟风速经 GE 1.5sle 功率曲线计算，再缩放为 6.6 MW 风电场并按小时平均。
- 时间：Houston 固定 UTC−06 本地标准时间，不进行夏令时跳变。
- 电价：沿用论文分段电价，每天按本地小时重复。该电价是外生价格信号，不解释为 Houston 当地电价。

Houston 场景生成脚本锁定 `nrel-pysam==7.1.0` 和 `dos-group/vessim-opt` 提交 `724ee837f2867ef7b90658730de2d55823a3ae5c`。

## 3. 参数尺度

服务器与数据中心：

- 12,500 台服务器；
- 单台最大功率 0.55 kW；
- 空闲功率比例 0.60，单台空闲功率 0.33 kW；
- PUE 固定为 1.10；
- CPU 容量上限 0.90 p.u.；
- 柔性比例 0.30，最大延迟 3 小时。

能源系统：

- 光伏面积 20,000 m²，基础效率 0.15，对应 3.0 MWdc；
- DC/AC 比 1.15，对应交流逆变器容量约 2.609 MW；
- 风电等效装机 6.6 MW；
- 电网购电容量固定 6.6 MW，仅作物理约束，不允许售电；
- 储能容量 2 MWh，最大充电和放电功率均为 0.5 MW；
- 充、放电效率分别为 0.95 和 0.90；
- SOC 范围 0.10–0.90，实验初始与最终 SOC 均为 0.50，即 1.0 MWh；
- 不设置充放电活动时段总数上限，同一小时保持充放电互斥。

## 4. 优化目标

一级目标最小化五项运行成本：

\[
\min \sum_t1000\Delta t\left[
\lambda_tP_t^{\mathrm{grid}}
+0.03P_t^{\mathrm{solar,use}}
+0.09P_t^{\mathrm{wind,use}}
+0.015(P_t^{\mathrm{ch}}+P_t^{\mathrm{dis}})
+0.15P_t^{\mathrm{dis}}
\right].
\]

成本单位为 CNY，功率单位为 MW。光伏和风电运维费按实际利用电量计费；储能纯运维费按充放电吞吐量计费；循环退化费只按放电量计费。弃风弃光只作为结果指标，不进入目标。

一级成本在 0.01 CNY 容差内固定后，二级目标最小化柔性任务总延迟。任务需求、CPU 容量和最大延迟均为硬约束，不设置算力服务缺口变量。

## 5. 跨日状态

4 月 30 日使用现有第 28 天算力轨迹预热，只生成 5 月 1 日前三小时可能存在的遗留任务，预热成本不计入实验。

储能算例先执行一次覆盖分析期与结算尾段的确定性 SOC 协调求解，得到每天第 24 小时末的储能电量目标。随后每日 24+3 小时窗口固定该日末边界，并把以下状态传到下一日：

- 第 24 小时末储能电量；
- 当日 21–23 时到达且尚未完成的柔性任务及其原始到达时刻。

最后一个窗口同时约束结算尾段结束电量恢复到 1.0 MWh，因此不会利用窗口末端进行无偿放电。

## 6. 运行与输出

运行默认主实验：

```powershell
conda run -n scip_env python run_first_version.py
```

指定输出目录：

```powershell
conda run -n scip_env python run_first_version.py --output-dir outputs/day_ahead_deterministic
```

主要输出：

- `model_input_28_days.csv`：672 小时算力与能源对齐输入；
- `hourly_case_results.csv`：四组算例各 675 小时结果，`period_role` 区分分析期和结算尾段；
- `daily_case_metrics.csv`：四组算例各 28 行日指标；
- `case_metrics.csv`：五项成本、供能占比、弃电、储能、并网和跨日任务汇总；
- `run_metadata.json`：数据来源、时间解释、参数、软件版本和等效完整循环定义；
- 每个窗口的一级、二级 LP 文件，以及两项 SOC 协调 LP；
- 五张 PNG 图，其中时序图均标出最后 3 小时结算尾段。

储能等效完整循环定义为：

\[
N_{\mathrm{EFC}}=E_{\mathrm{discharge}}/2\ \mathrm{MWh}.
\]

## 7. 验证

```powershell
conda run -n scip_env python -m unittest discover -s tests -v
```

测试覆盖 Houston 数据连续性、PVWatts 与风机配置解析、逐小时功率平衡、6.6 MW 并网约束、风光利用与弃电守恒、CPU 守恒、3 小时最大延迟、SOC 跨日连续、初末 1.0 MWh、0.5 MW 双向功率、充放电互斥、五项成本独立重算、不可行状态和完整输出。
