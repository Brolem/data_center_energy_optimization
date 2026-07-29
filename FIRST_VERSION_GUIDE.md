# Google 2019 聚合数据的 SCIP 第一版结果

## 1. 第一版做了什么

本版本从 `instance_usage_grouped_300_seconds_month.csv` 中：

1. 将 5 分钟聚合值进一步汇总为 1 小时均值；
2. 从 28 个真实日中选择最接近月平均小时曲线的第 8 天作为代表日；
3. 将 `avg_cpu` 作为归一化聚合算力需求；
4. 构造“聚合柔性算力时移 + 电池储能 + 并网功率平滑”确定性 MILP；
5. 使用 PySCIPOpt/SCIP 运行四个对照算例。

Google 2019 Cluster Trace 包含 2019 年 5 月多个 Borg cell 的使用数据，并以 5 分钟窗口提供 CPU 使用信息；当前 CSV 是在原数据基础上的第三方聚合文件，而不是原始任务表。来源：

- https://github.com/google/cluster-data/blob/master/ClusterData2019.md
- https://github.com/google/cluster-data/blob/master/clusterdata_trace_format_v3.proto

## 2. 如何复现

在项目根目录运行：

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
python run_first_version.py
```

若希望改用第 28 天压力日：

```bash
python run_first_version.py --day 28 --output-dir outputs/stress_day
```

PySCIPOpt 的标准建模流程和 `Model`、`addVar`、`addCons`、`setObjective`、`optimize` 等接口见官方教程：

- https://pyscipopt.readthedocs.io/en/latest/tutorials/model.html
- https://pyscipopt.readthedocs.io/en/latest/tutorials/vartypes.html

## 3. 数据处理与模型

### 3.1 小时聚合

第 \(t\) 小时的 CPU 使用率取该小时 12 个 5 分钟点的平均值：

\[
u_t=\frac{1}{12}\sum_{k=1}^{12}u_{t,k}.
\]

来源说明：这是常规等间隔时间序列均值聚合；原数据的 5 分钟统计窗口见 Google 2019 Trace 官方说明：
https://github.com/google/cluster-data/blob/master/ClusterData2019.md

### 3.2 聚合柔性算力时移

设柔性比例为 \(\rho\)，原时段 \(t\) 的柔性需求为：

\[
u_t^{\mathrm{flex}}=\rho u_t,\qquad
u_t^{\mathrm{fix}}=(1-\rho)u_t.
\]

来源说明：将聚合负荷按 delay-tolerant workload ratio 拆分，是针对当前缺少任务标签的数据所作的场景化简化；柔性任务分类与时间转移建模参考 Liu et al., *IEEE Access*, 2024：
https://doi.org/10.1109/ACCESS.2024.3432120

令 \(x_{t,\tau}\) 为原计划在 \(t\) 执行、实际安排到 \(\tau\) 的柔性负荷，最大允许延迟为 \(D\)：

\[
\sum_{\tau=t}^{\min(t+D,T-1)}x_{t,\tau}
=u_t^{\mathrm{flex}},\qquad \forall t.
\]

调度后 CPU 使用率为：

\[
\widetilde u_\tau
=u_\tau^{\mathrm{fix}}
+\sum_{t:\,t\le \tau\le t+D}x_{t,\tau}.
\]

来源说明：上述两式是 Liu et al. 短时可延迟任务转移矩阵的聚合简化形式：
https://doi.org/10.1109/ACCESS.2024.3432120

### 3.3 CPU 到数据中心功率的映射

采用线性 CPU 利用率—IT 功率模型：

\[
P_t^{\mathrm{IT}}
=P_{\mathrm{peak}}^{\mathrm{IT}}
\left[
\alpha+(1-\alpha)\widetilde u_t
\right],
\]

其中 \(\alpha\) 为空闲功率占峰值功率比例。来源：Dayarathna et al., “Data Center Energy Consumption Modeling: A Survey”：
https://doi.org/10.1109/COMST.2015.2481183

设施总功率按 PUE 映射：

\[
P_t^{\mathrm{DC}}=\mathrm{PUE}\cdot P_t^{\mathrm{IT}}.
\]

来源：Google 对 PUE 和数据中心能效的说明：
https://datacenters.google/efficiency/

### 3.4 储能模型

储能电量状态满足：

\[
E_{t+1}=E_t+\eta_cP_t^{\mathrm{ch}}\Delta t
-\frac{P_t^{\mathrm{dis}}\Delta t}{\eta_d}.
\]

储能状态和功率边界为：

\[
E^{\min}\le E_t\le E^{\max},
\qquad
0\le P_t^{\mathrm{ch}},P_t^{\mathrm{dis}}\le P^{\max}.
\]

来源：Eyisi et al., “Mathematical Models for Optimization of Grid-Integrated Energy Storage”：
https://www.osti.gov/servlets/purl/1592010

用二进制变量 \(z_t\) 避免同时充放电：

\[
P_t^{\mathrm{ch}}\le z_tP^{\max},\qquad
P_t^{\mathrm{dis}}\le(1-z_t)P^{\max},\qquad z_t\in\{0,1\}.
\]

来源：同一储能优化模型综述：
https://www.osti.gov/servlets/purl/1592010

### 3.5 并网功率与平滑目标

不考虑新能源和售电时，并网功率为：

\[
P_t^{\mathrm{grid}}
=P_t^{\mathrm{DC}}+P_t^{\mathrm{ch}}-P_t^{\mathrm{dis}}.
\]

来源说明：这是单母线功率平衡在“仅有数据中心负荷、电网与储能”边界下的简化；储能净充放电和电网功率平衡结构可参考：
https://www.osti.gov/servlets/purl/1592010

第一版目标是最小化相邻小时并网功率的总变化：

\[
\min\sum_{t=1}^{T-1}
\left|P_t^{\mathrm{grid}}-P_{t-1}^{\mathrm{grid}}\right|.
\]

代码中用两个线性不等式对绝对值进行线性化，并以极小的储能吞吐量项打破同目标解的退化。该目标是针对“并网联络线功率平滑”研究问题定义的实验目标，不是 Google 数据自带指标。

## 4. 本次算例参数

| 参数 | 数值 | 性质 |
|---|---:|---|
| 柔性负荷比例 \(\rho\) | 0.30 | 场景假设 |
| 最大延迟 \(D\) | 3 h | 场景假设 |
| CPU 容量上限 | 0.65 p.u. | 高于数据峰值的场景假设 |
| IT 峰值功率 | 100 MW | 场景假设 |
| 空闲功率比例 \(\alpha\) | 0.60 | 文献范围内的场景假设 |
| PUE | 1.20 | 场景假设 |
| 电池容量 | 4 MWh | 为避免单独储能完全拉平而设的小型算例参数 |
| 电池功率 | 1 MW | 场景假设 |
| 充/放电效率 | 0.95/0.95 | 场景假设 |
| 初始/终止 SOC | 0.50/0.50 | 日循环实验约束 |

这些功率和储能数值都不是 Google 数据中心的真实参数。

## 5. 第 8 天代表日的实际结果

| 算例 | 总波动量/MW | 较基准下降 | 最大爬坡/MW | 峰值并网功率/MW | SCIP 状态 |
|---|---:|---:|---:|---:|---|
| Baseline | 14.781 | 0.0% | 2.368 | 97.475 | optimal |
| 仅算力时移 | 2.190 | 85.2% | 1.244 | 96.351 | optimal |
| 仅储能 | 3.785 | 74.4% | 1.368 | 96.475 | gaplimit |
| 算力时移 + 储能 | 1.533 | 89.6% | 0.991 | 96.098 | gaplimit |

校验结果：

- 四个算例均得到满足设定精度的可行解，MIP gap 均低于 \(10^{-3}\)；Baseline 和仅算力时移的 SCIP 状态为 `optimal`，仅储能和联合优化达到相对间隙阈值后状态为 `gaplimit`；
- 调度前后 CPU 总量守恒误差低于数值容差；
- 储能初末 SOC 相等；
- 没有同时充放电；
- 联合优化的总波动量、最大爬坡量和峰值功率均为四组中最低。

## 6. 当前结果能说明什么、不能说明什么

能说明：

- 这份公共数据可以完成“数据—聚合算力建模—电功率映射—SCIP 求解—指标评价”的完整闭环；
- 聚合算力时移和储能在当前参数下具有互补的平滑作用；
- 代码结构可以继续加入新能源、分时电价和不确定性。

不能说明：

- Google 的真实数据中心功率下降了 89.6%；
- Google 真实任务中有 30% 可以延迟 3 小时；
- 当前参数已具备论文级工程真实性；
- 当前模型是任务级调度。CSV 不含任务 ID、到达时间、运行时长和截止时间，因此只能称为“聚合柔性算力负荷调度”。

## 7. 下一步建议

向老师展示第一版时，先提交本版本，不要立即加入鲁棒优化。老师认可问题结构后，按以下顺序扩展：

1. 对 28 天逐日运行，报告平均值、四分位数和最差日；
2. 对 \(\rho\)、\(D\)、电池容量/功率做敏感性分析；
3. 加入公开风光或电价数据，将目标扩展为成本与波动的约束式或分层式；
4. 若论文必须强调“任务调度”，再切换到含任务事件和截止期信息的原始 Google/Alibaba trace。
