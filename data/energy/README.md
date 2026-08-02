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
