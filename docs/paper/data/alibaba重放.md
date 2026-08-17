# Alibaba 2026 Spot GPU 重放口径

## 数据角色

算力侧使用 Alibaba 公开的 [cluster-trace-v2026-spot-gpu](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2026-spot-gpu)，固定到提交 `0d0f3f1efdbf1add6a7bcc63676eafbd1eb11f71`。官方说明将作业分为具有严格 SLO 的 HP 作业和使用机会资源的 Spot 作业，并给出型号、请求量、实例数、相对提交时间及持续时间；但没有公开地点、绝对日期、时区、HP 的具体 SLO 或截止期。因此本文把它作为真实到达模式的**反事实算力重放**，不称为 Houston 本地负载，也不从 HP 标签虚构截止期。[GFS 预印本](https://arxiv.org/abs/2509.11134)仅用于解释数据产生背景，不把其预测器或调度结果当作本文输入。

## 规范化

每条记录保留原始 `gpu_model` 和完整 gang：

- `gpu_count = gpu_request × worker_num`，允许分数 GPU，不取整；
- `release_hour = floor(submit_time / 3600)`；
- `required_run_hours = ceil(duration / 3600)`；
- HP 使用观测持续时间形成实现占用，`deadline = null`；
- Spot 仅保留 `required_run_hours ≤ 168` 的作业，并在反事实实验中设 `deadline = release + required_run_hours + 3`。

最后一条中的 3 小时是本文的结算宽限假设，不是数据集观测到的 SLA。逐型号物理容量直接对节点表的 `gpu_capacity_num` 求和：A10 2,494、A100-SXM4-80GB 3,456、A800-SXM4-80GB 176、GPU-series-1 1,558、GPU-series-2 976、H800 1,752 张。六类型号均有独立容量和功率映射，不进行跨型号替代。

## 代表 30 天核心

trace 首尾不是自然月，因而不按日期命名。对每个**观测完整**的连续 720 小时候选核心，计算核心内满足 168 小时上限的 Spot 精确 GPU·h；选择与所有候选中位数绝对距离最小者，平局取最早起点。末尾不完整小时不作为完整候选小时。

冻结结果为：

| 项目 | 数值 |
| --- | ---: |
| trace 核心 | 第 933–1,652 小时 |
| 起止秒 | 3,358,800–5,950,800（右端不含） |
| 核心长度 | 720 小时 |
| 核心内全部作业 | 87,083 |
| 满足上限的 Spot 作业 | 7,104 |
| 排除的超长 Spot 作业 | 11 |
| Spot 精确工作量 | 122,785.516250 GPU·h |
| 按小时上取整的调度工作量 | 143,918 GPU·h |

每个 ERCOT 季节窗口都重放同一个冻结算力核心，从而只改变能源市场和系统风光/碳条件，不混入不同工作负载样本。选择清单见 `workload_selection.json`；原始作业行不提交。

## 边界与审计

HP、Spot 都必须在指定 GPU 型号容量内运行；Spot 可按小时检查点抢占，但每个运行小时必须完整分配其 gang。核心结束后停止新 Spot 到达，既有作业可进入结算闭合期。任何缺少容量或功率映射、或单个 gang 超过该型号总容量的记录都按原因计数并排除；当前固定数据的这三类映射排除均为零。
