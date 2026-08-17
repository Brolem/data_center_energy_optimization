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

## Alibaba 2026 Spot GPU 原始工作负载

以下两个文件来自 Alibaba Cluster Trace Program，在 2026-08-15 下载。来源说明与字段定义见 [cluster-trace-v2026-spot-gpu README](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2026-spot-gpu)。研究固定到提交 `0d0f3f1efdbf1add6a7bcc63676eafbd1eb11f71`，不随 `master` 后续变化漂移。

| 文件 | 内容 | 数据行数 | 本地输入 SHA256 | 固定提交上游 SHA256 |
| --- | --- | ---: | --- | --- |
| `alibaba_2026_spot_gpu_job_info_df.csv` | GPU 作业提交、资源请求、持续时间与优先级 | 466,867 | `5A0C828A1C9CAE9D9AE73677371D59B4F3F0C55F25FE2E7CD06BC12DAF79648D` | `113CCEE4C28F5C3BBAACA974CD164B9280B7D4C39E53B745443B28EEA05E03DD` |
| `alibaba_2026_spot_gpu_node_info_df.csv` | GPU 节点型号、容量和 CPU 核数 | 4,278 | `1ABA161961A5A4A1A61AA581383C5E5ABE3400B59F8597BA8C4EEF7597BC9D18` | 同本地输入 |

这两个公开 CSV 只保存在本地 `data/workload/`，由 `.gitignore` 明确排除，不进入 Git 提交。作业表的本地副本仅把上游 `submit_time`、`duration` 的浮点文本序列化改为整数；2026-08-17 已逐行核验 9 个字段值与固定提交完全等价，因此同时记录本地输入和上游原始字节哈希。节点表与上游原始字节一致。重新下载时应先核验“固定提交上游 SHA256”；若再次做无损文本规范化，还必须记录实际输入 SHA256，不能用上游哈希冒充本地文件哈希。

作业表字段为 `job_name`、`organization`、`gpu_model`、`cpu_request`、`gpu_request`、`worker_num`、`submit_time`、`duration`、`job_type`；节点表字段为 `gpu_model`、`gpu_capacity_num`、`cpu_num`、`node_name`。下载时两个文件均无空值；作业表有 415,713 个 `HP` 作业和 51,154 个 `Spot` 作业。

`submit_time` 是相对第一份提交作业的秒数，而非日历时间戳。该数据集未公开运行地点、绝对日期或时区。因此它只用于构造真实 GPU 作业到达、资源请求和持续时间的算力侧重放负荷；不得称为 Houston 或 ERCOT 的本地工作负载。

可提交的选择结果只有 `docs/paper/data/workload_selection.json`：它记录源哈希、规范化规则、代表核心、排除计数、逐型号容量和功率情景，不包含任何原始作业行。原始 CSV、逐作业完整重放结果和缓存均不纳入 Git。
