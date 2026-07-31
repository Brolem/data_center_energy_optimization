# 数据中心 24 小时确定性日前模型使用指南

## 1. 模型定位与数据边界

本项目求解的是单日 24 小时确定性日前混合整数线性规划（MILP），联合决定算力时移、光伏和风电利用、电网购电及储能运行。主模型不是连续 28 天联合优化，也不包含日内滚动修正、预测误差、随机优化、鲁棒优化、算力服务缺口、负荷削减或向电网售电。

默认算力输入 `data/instance_usage_grouped_300_seconds_month.csv` 含 8,064 行，程序按上游约定的连续 5 分钟行序将其解释为 28 天。该 CSV 没有时间戳字段，当前程序只按行号切分日期和小时，不验证这些行在真实时间上是否连续。程序把每 12 行聚合为一个小时均值，再比较各日 CPU 曲线与 28 天平均 CPU 曲线的均方根距离：

- 第 8 天是默认代表日；
- 第 28 天是按单日 24 小时 CPU 曲线标准差最大选出的压力日；
- `--day 1` 至 `--day 28` 可显式选择任一天；
- 省略 `--day` 时使用第 8 天。

Google 轨迹没有给出这 28 天的真实日期和时区，因此“第 8 天”不能解释成某个自然月的 8 日。模型只是把所选算力日的小时索引 0–23 与能源场景的小时索引 0–23 对齐。

当前能源场景混合了两个不同地域的数据：

- `data/phoenix_nasa_power_20190501_20190528_hourly.csv` 提供菲尼克斯 2019-05-01 至 2019-05-28 的 672 个连续地方太阳时（LST）小时，仅使用 `solar_irradiance_wh_m2` 和 `wind_speed_50m_m_s`；
- `data/provisional_phoenix_weather_qinghai_tou_scenario.csv` 使用目标论文中的青海分时电价，青海电价与菲尼克斯气象在地理上不同。

构造临时 24 小时能源形状时，程序先对 672 个原始小时逐小时计算光伏和风电可用功率，再按小时 0–23 对 28 天的功率取均值；不能先平均太阳辐射或风速再计算功率。672 小时气象和 28 天算力数据只用于小时聚合、构造临时形状和选择运行日，不改变主模型的 24 小时时域。

这套混合场景只用于模型开发和模块验证，不能作为青海或菲尼克斯的地理实证结果。最终论文实验必须重新选择并统一对齐地点、真实日期、时区、气象数据和电价数据。

## 2. 参数与物理模型

### 2.1 算力与数据中心功率

| 参数 | 取值 |
|---|---:|
| 服务器数量 | 12,500 台 |
| 单台最大功率 | 0.55 kW |
| 单台空闲功率比例 | 0.60 |
| 单台空闲功率 | 0.33 kW |
| 调度后 CPU 利用率上限 | 0.90 |
| PUE | 1.10 |

设调度后 CPU 利用率为 \(u_t\)，则

\[
P_t^{\mathrm{IT}}
=\frac{12500[0.33+(0.55-0.33)u_t]}{1000}
=4.125+2.75u_t\quad\mathrm{MW},
\]

\[
P_t^{\mathrm{DC}}=1.10P_t^{\mathrm{IT}}.
\]

当 \(u_t=0.90\) 时，数据中心最大功率为 7.26 MW。电网购电约束为

\[
0\le P_t^{\mathrm{grid}}\le 7.66\quad\mathrm{MW},
\]

其中 7.66 MW 等于 7.26 MW 最大数据中心功率与 0.40 MW 最大储能充电功率之和。`grid_power_mw` 始终非负，模型没有售电变量。

### 2.2 光伏

光伏面积为 20,000 m²，基准转换效率为 0.15，名义容量为 3.0 MW。\(H_t\) 是该 1 小时间隔内的太阳辐照量，单位为 Wh/m²。先计算该间隔的光伏可用能量：

\[
E_t^{\mathrm{solar,avail}}
=\frac{20000\times0.15\times H_t}{10^6}
\quad\mathrm{MWh},
\]

再除以当前 \(\Delta t=1\ \mathrm{h}\) 得到该间隔的平均功率：

\[
P_t^{\mathrm{solar,avail}}
=\min\left(3.0,\frac{E_t^{\mathrm{solar,avail}}}{\Delta t}\right)
\quad\mathrm{MW}.
\]

当前气象源没有环境温度，因此模型不做温度修正。当前实现另行没有引入性能比（PR）参数；未引入 PR 并不是缺少环境温度导致的。光伏运行维护单价为 0.016 CNY/kW，只对 `solar_used_mw` 计费。

### 2.3 风电

风电由 33 台额定功率 200 kW 的风机组成，总装机容量为 6.6 MW。功率曲线参数为切入风速 3 m/s、额定风速 11.4 m/s、切出风速 25 m/s：

\[
P_t^{\mathrm{wind,avail}}=
\begin{cases}
0, & v_t<3\ \text{或}\ v_t\ge25,\\
6.6\dfrac{v_t^3-3^3}{11.4^3-3^3}, & 3\le v_t<11.4,\\
6.6, & 11.4\le v_t<25.
\end{cases}
\]

风电运行维护单价为 0.018 CNY/kW，只对 `wind_used_mw` 计费。

### 2.4 储能

| 参数 | 取值 |
|---|---:|
| 能量容量 | 1.0 MWh |
| 最大充电功率 | 0.40 MW |
| 最大放电功率 | 0.25 MW |
| 充电效率 | 0.95 |
| 放电效率 | 0.90 |
| SOC 下限 / 上限 | 0.10 / 0.90 |
| 初始 SOC / 日末 SOC | 0.50 / 0.50 |
| 运行维护单价 | 0.18 CNY/kW |
| 充电或放电活动时段数上限 | 16 |

每小时能量平衡为

\[
E_{t+1}=E_t+0.95P_t^{\mathrm{ch}}\Delta t
-\frac{P_t^{\mathrm{dis}}\Delta t}{0.90},
\qquad \Delta t=1\ \mathrm{h}.
\]

独立的 `charge_active` 和 `discharge_active` 二进制状态保证同一小时不能同时充放电，并满足

\[
\sum_{t=0}^{23}\left(z_t^{\mathrm{ch}}+z_t^{\mathrm{dis}}\right)\le16.
\]

这里限制的是充电或放电的活动时段数，不是循环次数。

### 2.5 柔性算力

柔性比例固定为 0.30，最大延迟固定为 3 小时。令 \(a_o\) 为小时 \(o\) 到达的 CPU 负荷，\(x_{o,t}\) 为从到达小时 \(o\) 分配到执行小时 \(t\) 的柔性负荷。变量的有效域严格为

\[
0\le o\le t\le\min(o+3,23).
\]

每个到达小时的柔性负荷满足

\[
\sum_{t=o}^{\min(o+3,23)}x_{o,t}=0.30a_o,
\]

而小时 \(t\) 的调度后 CPU 利用率只汇总能够到达 \(t\) 的来源小时：

\[
u_t=0.70a_t+\sum_{o=\max(0,t-3)}^t x_{o,t},
\qquad 0\le u_t\le0.90.
\]

柔性负荷必须在到达后 3 小时内且不跨日完整执行。守恒是硬约束；模型没有服务缺口、任务删除或负荷削减变量。

二级目标中的柔性负荷加权延迟为

\[
D=\sum_{0\le o\le t\le\min(o+3,23)}(t-o)x_{o,t}.
\]

它的单位是 CPU p.u.-h，不是任务条数；`total_task_delay_cpu_hours` 按这一口径输出。`average_flexible_task_delay_h` 的分母是 `flex_ratio * sum(cpu_arrival_pu)`，即 \(0.30\sum_o a_o\)，结果单位为 h；分母为 0 时程序返回 0。

### 2.6 新能源与功率平衡

光伏和风电分别满足“利用 + 弃电 = 可用”：

\[
P_t^{\mathrm{solar,use}}+P_t^{\mathrm{solar,curt}}
=P_t^{\mathrm{solar,avail}},
\]

\[
P_t^{\mathrm{wind,use}}+P_t^{\mathrm{wind,curt}}
=P_t^{\mathrm{wind,avail}}.
\]

每小时功率平衡为

\[
P_t^{\mathrm{grid}}+P_t^{\mathrm{solar,use}}
+P_t^{\mathrm{wind,use}}+P_t^{\mathrm{dis}}
=P_t^{\mathrm{DC}}+P_t^{\mathrm{ch}}.
\]

## 3. 两层优化目标

所有成本均以 CNY 计。电价 `electricity_price_cny_per_kwh` 是 CNY/kWh；`solar_om_cost_cny_per_kw`、`wind_om_cost_cny_per_kw` 和 `battery_om_cost_cny_per_kw` 的参数名及参数表量纲保持为 CNY/kW。本离散模型把三项运行维护参数解释为“每个 1 小时调度间隔的单位在运功率费用”。令 \(\Delta t=1\ \mathrm{h}\)，一级目标严格最小化下式中的四项运行成本：

\[
\begin{aligned}
C_{\mathrm{DA}}=\sum_{t=0}^{23}\bigg[
&\lambda_t\,(1000P_t^{\mathrm{grid}})\,\Delta t\\
&+0.016\,(1000P_t^{\mathrm{solar,use}})\frac{\Delta t}{1\ \mathrm{h}}\\
&+0.018\,(1000P_t^{\mathrm{wind,use}})\frac{\Delta t}{1\ \mathrm{h}}\\
&+0.18\,1000(P_t^{\mathrm{ch}}+P_t^{\mathrm{dis}})
\frac{\Delta t}{1\ \mathrm{h}}
\bigg].
\end{aligned}
\]

其中 \(1000P\) 把 MW 转换为 kW；购电项中的 \(\Delta t\) 以 h 计，运行维护项中的 \(\Delta t/(1\ \mathrm{h})\) 是无量纲的间隔缩放因子。当前 \(\Delta t=1\ \mathrm{h}\)，所以实现中的数值乘数为 1。该口径不能直接解释为长期平准化能源成本，也不能未经重新定义就用于任意时间步长的能量费率。

四项分别是电网购电费用、光伏运行维护费用、风电运行维护费用和储能充放电运行维护费用。新能源弃电只作为结果指标，不进入一级目标。

得到一级最优成本 \(C^*\) 后，程序增加

\[
C_{\mathrm{DA}}\le C^*+0.01\quad\mathrm{CNY},
\]

再以纯柔性负荷加权延迟

\[
D=\sum_{0\le o\le t\le\min(o+3,23)}(t-o)x_{o,t}
\]

作为二级最小化目标。该量的单位是 CPU p.u.-h，不代表任务条数。两层目标按先后顺序分别求解，不是把成本和延迟组成加权和。

## 4. 五组算例与精确开关

下表中的列名与 `build_and_solve` 接口一致：

| `case_name` | `enable_shift` | `enable_storage` | `enable_renewables` | 含义 |
|---|---:|---:|---:|---|
| `grid_only` | `False` | `False` | `False` | 仅电网，不时移，不启用储能 |
| `renewables_only` | `False` | `False` | `True` | 电网与风光，不时移，不启用储能 |
| `renewables_shift` | `True` | `False` | `True` | 电网、风光与算力时移 |
| `renewables_storage` | `False` | `True` | `True` | 电网、风光与储能，不时移 |
| `joint` | `True` | `True` | `True` | 电网、风光、算力时移与储能联合优化 |

五组算例使用相同的算力日、气象、电价、服务器规模、PUE 和电网容量。

## 5. 运行与测试

在项目根目录运行默认 24 小时代表日：

```powershell
conda run -n scip_env python run_first_version.py
```

运行压力日并指定独立输出目录：

```powershell
conda run -n scip_env python run_first_version.py --day 28 --output-dir outputs/stress_day
```

完整命令行选项：

| 选项 | 默认值 | 作用 |
|---|---|---|
| `--input` | `data/instance_usage_grouped_300_seconds_month.csv` | 按连续 5 分钟行序解释的 8,064 行 Google 2019 聚合算力 CSV；文件无时间戳，程序不验证真实时间连续性 |
| `--weather-source` | `data/phoenix_nasa_power_20190501_20190528_hourly.csv` | 672 小时菲尼克斯 NASA POWER 气象源 CSV |
| `--energy-scenario` | `data/provisional_phoenix_weather_qinghai_tou_scenario.csv` | 24 小时临时风光与青海分时电价场景 CSV |
| `--output-dir` | `outputs/day_ahead_deterministic` | 结果目录 |
| `--day` | 省略 | 指定第 1–28 天；省略时自动选择第 8 天 |
| `--show-scip-log` | 关闭 | 显示 SCIP 求解日志 |

运行全部单元测试：

```powershell
conda run -n scip_env python -m unittest discover -s tests -v
```

这组测试覆盖气象连续性和字段、临时能源场景重建、青海分时电价、参数尺度、物理守恒、两层目标、峰谷价储能、平价储能、高风光弃电、五组默认算例以及 CSV、JSON、LP 和图片输出。

## 6. 输出文件与字段

默认结果写入 `outputs/day_ahead_deterministic`。程序还会把三个输入 CSV 按原文件名复制到结果目录，便于复核本次运行使用的数据。

### 6.1 模型输入与中间数据

- `model_input_typical_day.csv`：24 行所选日模型输入。主要字段为 `day`、`hour`、`cpu_arrival_pu`、`avg_mem`、`avg_assigned_mem`、`avg_cycles_per_instruction`、`solar_irradiance_wh_m2`、`wind_speed_50m_m_s`、`solar_available_mw`、`wind_available_mw`、`tou_period`、`electricity_price_cny_per_kwh`。
- `all_days_hourly.csv`：28 天小时聚合结果。字段为 `day`、`hour`、`avg_cpu`、`avg_mem`、`avg_assigned_mem`、`avg_cycles_per_instruction`。

### 6.2 小时结果

`hourly_case_results.csv` 共 120 行，即 5 个算例各 24 行。字段为：

- 标识与算力：`case`、`hour`、`cpu_arrival_pu`、`cpu_scheduled_pu`；
- 数据中心与电网：`it_power_mw`、`dc_power_mw`、`grid_power_mw`；
- 光伏：`solar_available_mw`、`solar_used_mw`、`solar_curtailed_mw`；
- 风电：`wind_available_mw`、`wind_used_mw`、`wind_curtailed_mw`；
- 储能：`charge_mw`、`discharge_mw`、`charge_active`、`discharge_active`、`soc_start`、`soc_end`；
- 电价：`electricity_price_cny_per_kwh`、`tou_period`；
- 小时成本：`hourly_grid_purchase_cost_cny`、`hourly_solar_om_cost_cny`、`hourly_wind_om_cost_cny`、`hourly_battery_om_cost_cny`、`hourly_operating_cost_cny`。

### 6.3 汇总指标

`case_metrics.csv` 每个算例一行，包含：

- 开关与状态：`case`、`status`、`shift_enabled`、`storage_enabled`、`renewables_enabled`；
- 四项成本与总成本：`grid_purchase_cost_cny`、`solar_om_cost_cny`、`wind_om_cost_cny`、`battery_om_cost_cny`、`operating_cost_cny`；
- 相对基准节省：`operating_cost_savings_vs_grid_only_pct`；
- 电网指标：`grid_purchase_energy_mwh`、`grid_peak_power_mw`、`grid_mean_power_mw`；
- 新能源指标：`renewable_available_energy_mwh`、`renewable_used_energy_mwh`、`renewable_curtailment_energy_mwh`、`renewable_curtailment_rate_pct`；
- 储能指标：`battery_charged_energy_mwh`、`battery_discharged_energy_mwh`、`battery_active_periods`、`soc_cycle_error`、`max_simultaneous_charge_discharge_mw2`；其中 `soc_cycle_error` 是最后一小时 `soc_end` 与第一小时 `soc_start` 的绝对差，无量纲；`battery_active_periods` 按 `charge_mw > 1e-8` 或 `discharge_mw > 1e-8` 的小时计数，不是二进制状态之和；`max_simultaneous_charge_discharge_mw2` 是逐小时 `charge_mw * discharge_mw` 的最大值，单位为 MW²；
- 算力指标：`cpu_conservation_error`、`primary_total_task_delay_cpu_hours`、`total_task_delay_cpu_hours`、`average_flexible_task_delay_h`；
- 两层求解信息：`primary_operating_cost_cny`、`primary_solve_status`、`secondary_solve_status`、`primary_solve_time_s`、`secondary_solve_time_s`、`primary_gap`、`secondary_gap`、`solve_time_s`、`mip_gap`。带 `primary_` 和 `secondary_` 前缀的字段分别对应两层求解；兼容字段 `status`、`solve_time_s` 和 `mip_gap` 对应二级求解结果。

### 6.4 元数据、模型与图片

- `run_metadata.json`：顶层字段为 `model_type`、`scenario_status`、`input_file`、`energy_scenario_file`、`weather_source`、`electricity_price_source`、`geographic_interpretation`、`raw_rows`、`energy_scenario_rows`、`days`、`representative_day`、`stress_day`、`selected_day`、`parameters`、`software_versions`。
- `{case}_primary.lp`：每个算例的一级成本模型。
- `{case}_secondary.lp`：每个算例增加一级成本容差约束后的二级延迟模型。

每个 `case` 都生成一对 LP 文件，共 10 个。图片文件严格为：

1. `day_ahead_power_results.png`：数据中心、电网、光伏利用和风电利用的日前功率对比；
2. `compute_scheduling_results.png`：CPU 到达曲线和调度后曲线；
3. `battery_operation_results.png`：`renewables_storage` 与 `joint` 的充电、放电和 SOC；
4. `renewable_dispatch_results.png`：新能源可用、利用和弃电；
5. `operating_cost_comparison.png`：四项运行成本堆叠对比。

## 7. 正确解释结果

若运行结果出现储能零充电和零放电，这可能是分时价差、充放电效率和 0.18 CNY/kW 运行维护费共同作用下的经济最优解，不能据此认定储能模块失效。单元测试使用合成峰谷价场景验证充电量和放电量都大于零，并检查 SOC 平衡、充放电互斥、功率上限、活动时段上限和运行维护成本复算；该测试没有断言充放电发生在具体分时时段。统一平价场景另行验证储能可以保持零运行。

新能源弃电不受罚且不能售电，因此弃电量由逐小时供需、储能可用性和禁止售电共同决定。合成高风光测试验证正弃电量及 `renewable_curtailment_rate_pct` 的计算，默认运行是否弃电则由实际 24 小时供需结果决定。

本模型是目标论文电力子系统的确定性日前扩展，不是冷热电多能源系统的完整复现，也不是任务级数据中心调度。当前参数与混合场景可用于代码开发、模块验证和方法说明；最终论文的结果表、经济结论和地域结论必须建立在地点、日期、时区、气象与电价全部重新对齐的数据集上。
