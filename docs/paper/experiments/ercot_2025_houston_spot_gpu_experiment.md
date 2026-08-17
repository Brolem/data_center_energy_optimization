# ERCOT 2025 × Alibaba Spot GPU 主实验

## 研究边界

本实验是单一代表性数据中心的反事实日前调度。成本使用 ERCOT `LZ_HOUSTON` DAM 价格；新能源指标使用 ERCO 平衡区系统风、光出力的时段匹配；碳指标使用 EIA ERCO 平均消费侧碳强度。Alibaba 2026 Spot GPU trace 仅提供未地理定位的相对工作负载，不能称为 Houston 的实际负载。

系统风、光不是数据中心本地风电/光伏或物理购电来源；消费侧碳强度不是边际碳。实际风光与碳只用于事后评价。

## 固定时间窗口

| 季节 | 核心当地交割日 | 上下文 | 核心期 | 结算闭合期 |
| --- | --- | ---: | ---: | ---: |
| 冬季 | 2025-01-01 至 2025-01-30 | 171 h | 720 h | 171 h |
| 春季 | 2025-04-01 至 2025-04-30 | 171 h | 720 h | 171 h |
| 夏季 | 2025-07-01 至 2025-07-30 | 171 h | 720 h | 171 h |
| 秋季 | 2025-10-01 至 2025-10-30 | 171 h | 720 h | 171 h |

每个输入固定 1,062 个连续小时。`D_max=168 h`、`H=3 h`，故结算闭合期为 `D_max+H=171 h`；核心期结束后不再接收新 Spot 作业，但继续结算已有作业的能耗、成本、碳和未完成工作。`timestamp_utc` 是小时结束时刻，窗口核心按 ERCOT 当地交割日期选取，前后段按连续 UTC 时刻扩展。

## 日前信息集

每个交割日前一日 18:00 `America/Chicago` 运行调度。次日 DAM 价格视为已知；风、光与消费侧碳由研究者从 EIA ERCO 历史观测预测。任一截止时刻 `c` 仅可使用 `timestamp_utc <= c-48h` 的数据。

主预测器为滚动 90 日、24 个目标小时直接预测的 NumPy Ridge；风、光、碳分别拟合。正则化强度只在 2024 年固定滚动起点上选择，28 日同小时中位数作为比较基线。2025 四个窗口不参与模型或超参数选择。

## 输入字段

```text
window_id,window_hour,period_role,interval_start_utc,interval_end_utc,local_date,
dam_lz_houston_usd_per_mwh,erco_solar_generation_mwh,
erco_wind_generation_mwh,erco_consumed_co2_intensity_lbs_per_kwh,
forecast_cutoff_utc,forecast_method,forecast_erco_solar_generation_mwh,
forecast_erco_wind_generation_mwh,forecast_consumed_co2_lbs_per_kwh
```

上下文行不需要预测；核心期与闭合期每小时必须有预测。`inputs_manifest.json` 记录原始来源和输出 SHA-256、48 小时保护期、Ridge 参数、2024 预测误差、28 日中位数误差及缺失值数量，不记录本机绝对路径或原始内容。

## 2024 预测验证结果

2024 年 12 个固定月度起点共评价 288 个目标小时，三个目标选择的 `alpha` 均为 100：

| 目标 | Ridge MAE / nMAE | 28 日中位数 MAE / nMAE | 判读 |
| --- | ---: | ---: | --- |
| 消费侧碳强度 | 0.104 / 0.156 | 0.115 / 0.172 | Ridge 较优 |
| 光伏出力 | 1324.654 / 0.245 | 1124.003 / 0.208 | 中位数较优 |
| 风电出力 | 5212.919 / 0.341 | 5248.783 / 0.343 | Ridge 略优 |

因此不得把默认模型的光伏预测性能写成论文创新。主实验保留统一 Ridge 作为预注册、因果且可复现的情景输入，并保留中位数对照；若后续替换光伏模型，必须沿用 48 小时保护、2024 选模和四个 2025 固定窗口。

## 生成命令

```powershell
conda run -n scip_env python scripts/prepare_paper_ercot_2025_spot_gpu_inputs.py --eia-history PATH_TO_EIA_HISTORY --ercot-2024-dam PATH_TO_2024_DAM --source eia_930_erco=PATH_TO_EIA_HISTORY --source ercot_dam_2024_np4_180_er=PATH_TO_2024_DAM --source shared_ercot_2025=data/energy/ercot_2025_houston_hourly.csv
```

该命令不修改共享的 `scripts/prepare_ercot_2025_houston_energy.py`。原始 EIA、ERCOT 和 Alibaba 文件不进入 Git；紧凑论文输入位于 `outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/`，且不作为求职线数据。
