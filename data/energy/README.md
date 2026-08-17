# Houston 2020 小时能源场景

`houston_2020_may_hourly.csv` 包含 699 行连续小时数据，采用 Houston 固定 UTC-06 本地标准时间：2020-04-30 00:00 至 2020-05-29 02:00。时间段由 24 小时预热、2020-05-01 至 2020-05-28 的 672 小时分析期，以及 3 小时结算尾段组成。

字段与单位：

| 字段 | 含义 | 单位 |
| --- | --- | --- |
| `timestamp_lst` | Houston 本地标准时间 | `YYYY-MM-DDTHH:MM:SS`，UTC-06 |
| `solar_available_mw` | 光伏可用交流功率 | MW |
| `wind_available_mw` | 风电可用功率 | MW |
| `tou_period` | 论文分段电价时段 | `valley`、`flat` 或 `peak`，无量纲 |
| `electricity_price_cny_per_kwh` | 外生论文分段购电价 | CNY/kWh |

光伏源为 NSRDB 五分钟数据，经 PVWatts v8 计算后按每小时 12 点平均；风电源为 NREL WIND Toolkit 的 80 m 五分钟风速，经 GE 1.5sle 功率曲线计算并缩放到 6.6 MW 后按小时平均。固定来源为 `dos-group/vessim-opt` 提交 `724ee837f2867ef7b90658730de2d55823a3ae5c`，脚本 `scripts/prepare_houston_2020_energy.py` 固定校验五个源文件哈希并使用 `nrel-pysam==7.1.0` 生成本文件。

电价沿用论文分段价格信号，不解释为 Houston 当地电价。

原始字节 SHA256：`1E075995C24141BA358B0452EE829C6006FAB25B3E83C6868587EDD837BDD7E0`。

## ERCOT 2025 DAM 价格与 EIA ERCO 风光/碳原始数据

以下文件在 2026-08-15 下载，保留为未经变换的原始输入。它们服务于“Houston 负荷区成本信号 + ERCOT 系统级可再生能源与碳信号”的论文实验边界；不将系统级风光或碳排放解释为 Houston 本地能源数据。

| 文件 | 来源与内容 | SHA256 |
| --- | --- | --- |
| `ercot_2025_historical_dam_load_zone_and_hub_prices.zip` | [ERCOT Historical DAM Load Zone and Hub Prices](https://www.ercot.com/mp/data-products/data-product-details?id=np4-180-er) 的 2025 年公开年度归档；ZIP 内含 `rpt.00013060.0000000000000000.DAMLZHBSPP_2025.xlsx` | `30DF71EBB306BBE8C6CC075598D2E5BD47079B8AB9E0442979F3331353618320` |
| `eia_930_erco_full_history.xlsx` | [EIA Hourly Electric Grid Monitor](https://www.eia.gov/electricity/gridmonitor/about) 的 ERCO 平衡区完整历史工作簿 | `0EFF7C52C9014F83EDF83831C21C130E7055DD1DCCE24235369040EFE8AA41E0` |
| `ercot_fuel_mix_raw/IntGenbyFuel2025.xlsx` | ERCOT [Fuel Mix Report: 2025](https://www.ercot.com/files/docs/2025/02/07/IntGenbyFuel2025.xlsx)；`Dec` 表的 `FINAL` 15 分钟系统燃料出力 | `BB534618700FF3500EEE36B62FA2A9AB07B0923ED536F6D049868101189CFC54` |

这三项原始公开文件只保存在本地 `data/energy/`，由 `.gitignore` 明确排除，不进入 Git 提交。复现时重新下载后必须先核对上表 SHA-256；`ercot_2025_houston_hourly.csv` 才是纳入版本控制的共享正式输入。

ERCOT 工作簿按 `Jan` 至 `Dec` 分表，字段为 `Delivery Date`、`Hour Ending`、`Repeated Hour Flag`、`Settlement Point`、`Settlement Point Price`。`Settlement Point` 为 `LZ_HOUSTON` 的记录共有 8,760 个，覆盖 2025-01-01 01:00 至 2025-12-31 24:00，且价格字段无空值。正式处理阶段以该字段作为数据中心成本信号。

EIA 工作簿的 `Published Hourly Data` 表含 `UTC time`、`Local date`、`Local time`、`Time zone`、`Demand`、`NG: SUN`、`NG: WND` 和 `CO2 Emissions Intensity for Consumed Electricity` 等已发布列。正式处理阶段以 `UTC time` 作为跨数据源对齐的主时间索引，并显式处理时区与夏令时；不得跨当地日期通过全表行号拼接 ERCOT 与 EIA 数据。

## 共享年度表：ERCOT 2025 Houston

`ercot_2025_houston_hourly.csv` 是论文线与求职线共用的 2025 年小时能源表。其基础字段由下列命令从 DAM 与 EIA 原始表生成，随后仅对下述已发布但 EIA 缺失的风、光记录应用 Fuel Mix 补数规则：

```powershell
conda run -n scip_env python scripts/prepare_ercot_2025_houston_energy.py
```

该文件有 8,760 行。主键 `timestamp_utc` 是 EIA 定义的小时结束 UTC 时刻，范围为 `2025-01-01T07:00:00Z` 至 `2026-01-01T06:00:00Z`。EIA 记录以 `Local date` 为 2025 年筛选条件；ERCOT 记录以 `Delivery Date` 为 2025 年筛选条件。每个当地日期先校验两来源的记录数相等，之后依来源内顺序一一配对。此规则保留春季短日的 23 小时和秋季长日的 25 小时；秋季两条 ERCOT `Hour Ending = 02:00` 记录的 `Repeated Hour Flag` 分别保留为 `N` 和 `Y`，并对应两个连续 UTC 时刻。

| 字段 | 含义 | 单位或格式 |
| --- | --- | --- |
| `timestamp_utc` | EIA 小时结束 UTC 时刻，唯一且递增 | `YYYY-MM-DDTHH:MM:SSZ` |
| `local_date` | EIA 报告当地日期 | `YYYY-MM-DD` |
| `local_hour` | EIA 当地日内连续小时号 | 1–25 |
| `local_time_end` | EIA 当地小时结束时刻 | `HH:MM:SS` |
| `delivery_date` | ERCOT DAM 交割日期 | `YYYY-MM-DD` |
| `hour_ending` | ERCOT DAM 小时结束标签 | `HH:MM` |
| `repeated_hour_flag` | ERCOT 秋季重复小时标志 | `N` 或 `Y` |
| `dam_lz_houston_usd_per_mwh` | `LZ_HOUSTON` DAM 结算点价格 | USD/MWh |
| `erco_solar_generation_mwh` | ERCO 报告的 `NG: SUN` | MWh |
| `erco_wind_generation_mwh` | ERCO 报告的 `NG: WND` | MWh |
| `erco_consumed_co2_intensity_lbs_per_kwh` | ERCO 消费侧碳强度 | lbs/kWh |

风、光和碳字段是 ERCOT 平衡区系统信号，不能表述为 Houston 本地发电或本地边际排放。EIA 源工作簿在下列记录缺失；其中风、光可由 ERCOT 已结算的 Fuel Mix 官方表等价补齐，碳强度则保留为空，绝不以零、均值或插值替代：

- 对当地日期 `2025-12-04` 与 `2025-12-05` 的每一小时，`Dec` 表中相同日期、`Settlement Type = FINAL` 的四个连续 15 分钟 `Solar` 或 `Wind` 值相加，填入年度表对应的 `erco_solar_generation_mwh` 或 `erco_wind_generation_mwh`。`timestamp_utc` 是该当地小时结束时刻，故此规则恰好覆盖 `2025-12-04T07:00:00Z` 至 `2025-12-06T06:00:00Z` 的 48 小时；它不改写已有 EIA 值。
- `erco_consumed_co2_intensity_lbs_per_kwh`：仍有 72 小时未发布，`2025-12-03T07:00:00Z` 至 `2025-12-06T06:00:00Z`。Fuel Mix 不能等价还原 EIA 的“消费侧”碳强度（含跨区电力归属），因此不把它用于碳列补值。

脚本只使用标准库读取 XLSX 容器，并在生成前校验两个原始文件的 SHA-256。论文窗口的快照及其输入哈希清单写入 `outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/`；这些快照不是求职线的输入数据。

## 论文 Spot GPU 输入物化

论文专用的四个 1,062 小时输入由 `scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py` 生成。除共享 2025 年度表外，使用两项本地原始来源；它们均由 `.gitignore` 排除：

| 本地文件 | 来源与用途 | SHA256 |
| --- | --- | --- |
| `eia_930_erco_full_history.xlsx` | EIA ERCO 风、光与消费侧碳完整历史；用于 2024 选参与每天因果预测 | `0EFF7C52C9014F83EDF83831C21C130E7055DD1DCCE24235369040EFE8AA41E0` |
| `ercot_2024_historical_dam_load_zone_and_hub_prices.zip` | ERCOT [`np4-180-er`](https://www.ercot.com/mp/data-products/data-product-details?id=np4-180-er) 2024 年度归档，文档编号 `1065468714`；用于冬季上下文价格 | `B9FD0B9AA9EC83376C6385C91416174857CA6BA556C6DF08E942A2F98B89AF65` |

生成器直接把 2024 年 12 月 `LZ_HOUSTON` DAM 与 EIA ERCO 记录按当地日期逐小时配对，不生成或提交中间年度表。对每个交割日前一日 18:00 `America/Chicago` 的研究截止，只使用结束时间不晚于截止前 48 小时的观测。主预测器为滚动 90 日直接多步 Ridge，正则化强度只在 2024 年每月 15 日滚动起点选择；28 日同小时中位数保留为基线。

```powershell
conda run -n scip_env python scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py --eia-history data/energy/eia_930_erco_full_history.xlsx --ercot-2024-dam data/energy/ercot_2024_historical_dam_load_zone_and_hub_prices.zip --source eia_930_erco=data/energy/eia_930_erco_full_history.xlsx --source ercot_dam_2024_np4_180_er=data/energy/ercot_2024_historical_dam_load_zone_and_hub_prices.zip --source shared_ercot_2025=data/energy/ercot_2025_houston_hourly.csv
```

重复的 `--source stable_id=path` 参数仅用于把稳定来源标识与实际 SHA-256 写入 `inputs_manifest.json`；清单不包含本机绝对路径、访问令牌或原始内容。仅最终四个紧凑 CSV 与 JSON 清单可进入版本控制。风、光与碳是 ERCO 系统信号，不得写成数据中心本地新能源或边际碳。

2026-08-17 已完成一次真实物化：四个 CSV 各 1,062 行，核心与闭合期预测均完整，来源和输出哈希见同目录 `inputs_manifest.json`。2024 验证显示光伏 Ridge 的 MAE 高于 28 日中位数，因此不把其预测性能描述为创新；后续模型替换仍须遵守同一 48 小时信息边界和 2024 选模规则。
