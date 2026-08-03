# Houston 2020 主实验

## 1. 正式输入

- 工作负载：`data/workload/google_2019_28d_5min.csv`，8,064 行五分钟数据，聚合为 28 天、672 小时。
- 能源场景：`data/energy/houston_2020_may_hourly.csv`，699 个连续小时，范围为 2020-04-30 00:00 至 2020-05-29 02:00。

699 小时由 24 小时预热、672 小时分析期和 3 小时结算尾段组成，时间采用 Houston 固定 UTC−06 本地标准时间，不进行夏令时跳变。

## 2. 风光与电价

光伏来自 NSRDB 五分钟数据，经 PVWatts v8 计算 3 MWdc 系统的交流出力，再对每小时 12 个点取平均。风电来自 NREL WIND Toolkit 的 80 m 五分钟风速，经 GE 1.5sle 功率曲线得到容量因子，缩放到 6.6 MW 后按小时平均。

电价按本地小时每日重复：

- 00:00–07:59：0.1804 CNY/kWh；
- 09:00–12:59、18:00–22:59：0.7174 CNY/kWh；
- 其余时段：0.4489 CNY/kWh。

风光数据来自 Houston；电价沿用论文分段价格，只作为外生价格信号，不主张二者具有地理一致性。

## 3. 对比算例

| 算例 | 算力转移 | 储能 | 风光 |
| --- | ---: | ---: | ---: |
| `renewables_only` | 否 | 否 | 是 |
| `renewables_shift` | 是 | 否 | 是 |
| `renewables_storage` | 否 | 是 | 是 |
| `joint` | 是 | 是 | 是 |

成本节省率以 `renewables_only` 为基准。纯电网算例不进入正式图表和结果表。

## 4. 运行方式

```powershell
conda run -n scip_env python run_day_ahead_experiment.py
```

正式命令行参数为：

- `--workload-data`：工作负载 CSV；
- `--energy-data`：Houston 能源 CSV；
- `--output-dir`：完整实验输出目录；
- `--show-solver-log`：显示 SCIP 求解日志。

主实验完成后，终端仅打印与优化目标直接相关的摘要：纯电网核算成本、纯电网所需峰值、风光成本贡献，以及四个正式算例的求解状态、总运行成本、成本节省率、柔性任务总延迟和最大延迟。纯电网核算使用 `renewables_only` 相同的 `dc_power_mw` 和逐时电价，不重新求解；完整元数据与其他指标仍保存在 `run_metadata.json` 和结果 CSV 中。

已有 `hourly_dispatch.csv` 时，可输入指定日期直接生成单日图，无需重新求解：

```powershell
conda run -n scip_env python plot_day_ahead_day.py `
  --hourly-dispatch outputs/houston_2020_main/results/hourly_dispatch.csv `
  --day 28 `
  --output-dir outputs/houston_2020_main/figures
```

`--day` 必须位于 `1..28`。第 1～27 天输出 24 小时；第 28 天输出 24 小时分析期和 3 小时结算尾段，尾段使用浅灰背景标识，其成本包含在第 28 天成本分解图中。

## 5. 输出结构

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
│   ├── cost_breakdown.png
│   └── day_XX/
│       ├── power_dispatch.png
│       ├── compute_schedule.png
│       ├── battery_dispatch.png
│       ├── renewable_dispatch.png
│       └── cost_breakdown.png
├── models/<case>/<window>/
│   ├── stage_1_cost.lp
│   └── stage_2_delay.lp
└── run_metadata.json
```

默认完整运行生成 2,700 行 `hourly_dispatch.csv`、112 行 `daily_metrics.csv`、4 行 `case_metrics.csv`、232 个 LP 文件和 5 张 PNG。四个算例各含 672 小时分析期与 3 小时结算尾段。

## 6. 结果字段

`hourly_dispatch.csv` 的主要字段分为：

- 时间与算例：`case`、`timestamp_lst`、`day`、`hour_of_day`、`period_role`；
- 算力与功耗：`cpu_arrival_pu`、`cpu_scheduled_pu`、`it_power_mw`、`dc_power_mw`；
- 电源调度：`grid_power_mw`，风光的 `available`、`used`、`curtailed` 功率；
- 储能：`charge_mw`、`discharge_mw`、充放电状态、起止 SOC 与起止电量；
- 成本：小时购电、光伏运维、风电运维、储能运维、储能退化和总运行成本。

`daily_metrics.csv` 记录每天的窗口初末电量、协调边界、遗留任务量、当日任务延迟和结算尾段成本。`case_metrics.csv` 汇总五项成本、分析期与尾段成本、供能占比、弃电率、储能充放电量与等效完整循环、并网约束生效小时、任务延迟、守恒误差和求解状态。

`operating_cost_cny` 等于 672 小时分析期成本与 3 小时结算尾段成本之和；预热成本不计入。储能等效完整循环定义为放电能量除以 2 MWh。

## 7. 复现来源

能源场景生成脚本为 `scripts/prepare_houston_2020_energy.py`，锁定 `nrel-pysam==7.1.0`，并校验全部源文件哈希。风光方法和原始配置固定到 `dos-group/vessim-opt` 提交 `724ee837f2867ef7b90658730de2d55823a3ae5c`。

提交数据的原始字节 SHA256：

- Google 工作负载：`3F2A240BCBCC97FE74D3609381029C03AAD97D4ADF28B753D2B058CBD448D20D`；
- Houston 能源：`1E075995C24141BA358B0452EE829C6006FAB25B3E83C6868587EDD837BDD7E0`。
