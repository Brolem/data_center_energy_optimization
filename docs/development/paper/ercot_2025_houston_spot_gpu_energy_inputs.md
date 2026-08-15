# ERCOT 2025 共享能源表与论文窗口输入

## 当前状态

已生成并核验 2025 年共享 ERCOT Houston 小时能源表，以及论文线四个固定 30 天窗口和 3 小时结算闭合期的能源输入快照。尚未实现 Alibaba Spot GPU 作业重放、GPU 资源到功率的映射或新的优化实验；本次不修改现有 Houston 2020 模型与结果。

## 已完成

- 原始 ERCOT 2025 `LZ_HOUSTON` DAM 价格与 EIA ERCO 小时工作簿已存于 `data/energy/`，并在生成前校验 SHA-256；
- `data/energy/ercot_2025_houston_hourly.csv` 已生成：8,760 行，UTC 主键从 `2025-01-01T07:00:00Z` 连续至 `2026-01-01T06:00:00Z`；
- ERCOT 与 EIA 以当地日期分组并逐日顺序配对，完整保留春季 23 小时和秋季 25 小时的 DST 记录；
- 下列论文专用能源快照各含 720 个主实验小时和 3 个结算闭合小时：
  - `outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/2025-01-01_30d_h3h_energy.csv`
  - `outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/2025-04-01_30d_h3h_energy.csv`
  - `outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/2025-07-01_30d_h3h_energy.csv`
  - `outputs/paper/ercot_2025_houston_spot_gpu/day_ahead/inputs/2025-10-01_30d_h3h_energy.csv`
- `inputs_manifest.json` 已记录原始能源文件和上述五个生成 CSV 的 SHA-256；
- 已新增 DST 配对、年度筛选、空值保留、窗口边界和最小 XLSX XML 读取器测试。

## 数据完整性边界

源 EIA 工作簿的 2025 年末存在未发布数值。共享年度表将它们保留为空：

- 消费侧碳强度：72 小时，`2025-12-03T07:00:00Z` 至 `2025-12-06T06:00:00Z`；
- 风电和光伏：各 48 小时，`2025-12-04T07:00:00Z` 至 `2025-12-06T06:00:00Z`。

四个论文窗口没有这些空值。任何覆盖上述年末时段的后续实验都必须先取得有来源的完整数据或拒绝该时段，不得填零、均值填补或插值。

## 验证记录

- `tests.shared.test_ercot_2025_energy`：15 项通过；
- 独立 CSV 质量检查：年度表 8,760 行，四个窗口各 723 行且各有 3 行闭合期；
- 清单中五个输出文件 SHA-256 均与实际文件相等；
- 四个论文窗口的风、光和消费侧碳字段均无空值。

## 后续前置条件

生成时不推断 Alibaba Spot GPU 作业的截止期、功率或四季重放片段。开始论文优化实验前，需单独固化并测试作业筛选、相对时间锚定、GPU 资源到 IT 负荷的标定和 H 小时延迟语义。其设计不得与本次已生成的能源输入口径相互混淆。
