# Google 2019 工作负载数据

`google_2019_28d_5min.csv` 包含 8,064 行连续五分钟聚合值，即 28 天 × 288 点/天。文件没有时间戳；行序从第 1 天第 1 个五分钟点连续排列至第 28 天最后一个五分钟点。

字段与单位：

| 字段 | 含义 | 单位 |
| --- | --- | --- |
| `avg_cpu` | 平均 CPU 使用量 | 归一化比例，无量纲 |
| `avg_mem` | 平均内存使用量 | 归一化比例，无量纲 |
| `avg_assigned_mem` | 平均已分配内存 | 归一化比例，无量纲 |
| `avg_cycles_per_instruction` | 平均每指令周期数 | cycles/instruction |

来源是 Google 2019 Cluster Trace 的第三方聚合文件；原始格式说明见 Google `cluster-data` 仓库的 `ClusterData2019.md` 和 `clusterdata_trace_format_v3.proto`。本仓库未包含从原始任务表生成该第三方聚合 CSV 的脚本。

正式读取与小时聚合由 `dc_energy_opt/data/workload.py` 的 `load_and_prepare` 完成：每 12 个五分钟点取均值得到 672 个连续小时，并从 28 天中确定代表日与压力日。

原始字节 SHA256：`3F2A240BCBCC97FE74D3609381029C03AAD97D4ADF28B753D2B058CBD448D20D`。
