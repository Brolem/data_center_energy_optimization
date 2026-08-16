# 可移峰负载比例敏感性分析

## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: validate
- Origin Date: 2026-08-16
- Verification Status: VERIFIED
- Version Label: validation_v1
- Source: `results/flex_ratio_sensitivity.csv`、`run_metadata.json`
- Overall Confidence: CAUTION（本确定性算例内的数值关系已复算验证，跨月份、跨地区外推仍需额外实验）

## 结论摘要

在 Houston 2020 年 5 月、28 天滚动日前调度算例中，提高可移峰负载比例会单调降低运行成本，同时单调增加任务延迟。`flex_ratio=1.0` 时，无储能时移场景节省 96,367.3395 CNY（8.4687%），联合场景节省 95,523.9057 CNY（8.5004%）。两条曲线在 0.0–1.0 范围内均未出现设定阈值下的饱和点，但单位可移峰比例的边际节省有所下降。

## 实验设定与指标

- 模型：确定性滚动 `24+3` 小时日前调度。
- 数据：28 天、672 小时分析期；末日另含 3 小时结算尾段。
- 扫描范围：`flex_ratio=0.0, 0.1, ..., 1.0`。
- 对照关系：`renewables_shift` 对比 `renewables_only`；`joint` 对比 `renewables_storage`。
- `operating_cost_cny` 为 672 小时分析期成本与 3 小时结算尾段成本之和，不含预热成本。
- `marginal_cost_savings_cny_per_flex_ratio` 表示相邻两个比例点之间，单位可移峰比例对应的成本下降。

## 求解与数据完整性

- 汇总表共 22 行，全部状态为 `optimal`。
- 本次重算使用 `relative_gap=0.0`。
- 运行提交：`0264ad6c34facbb090370adf7199ba6a444226d4`。
- 两个场景的成本均随 `flex_ratio` 单调下降，累计延迟均单调上升。
- 未使用 p 值、置信区间或样本效应量；这些指标不适用于本次单一确定性网格实验。

## 关键结果

| 场景 | 可移峰比例 | 运行成本 (CNY) | 累计节省 (CNY) | 节省比例 | 总延迟 (CPU·h) | 平均灵活任务延迟 (h) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| renewables_shift | 0.30 | 1,108,096.3299 | 29,829.9335 | 2.6214% | 63.8959 | 0.6670 |
| renewables_shift | 0.50 | 1,088,899.6387 | 49,026.6247 | 4.3084% | 119.6481 | 0.7494 |
| renewables_shift | 1.00 | 1,041,558.9239 | 96,367.3395 | 8.4687% | 303.8784 | 0.9516 |
| joint | 0.30 | 1,094,637.0545 | 29,118.7618 | 2.5912% | 63.1928 | 0.6596 |
| joint | 0.50 | 1,075,473.4645 | 48,282.3518 | 4.2965% | 119.5266 | 0.7486 |
| joint | 1.00 | 1,028,231.9107 | 95,523.9057 | 8.5004% | 305.9962 | 0.9582 |

## 趋势与边际收益

1. **成本收益稳定但略有递减。** `renewables_shift` 的边际节省从首段的 100,448.2461 降至末段的 94,229.7975 CNY/单位比例，下降 6.1907%；`joint` 从 97,891.7876 降至 93,526.8149，下降 4.4590%。末段边际收益仍远高于饱和判定阈值，因此两个场景均未检测到 `saturation_onset`。
2. **延迟是主要权衡。** 比例从 0.30 提高到 1.00 时，无储能时移场景的平均灵活任务延迟由 0.6670 增至 0.9516 小时，联合场景由 0.6596 增至 0.9582 小时；所有非零比例点的最大延迟均达到 3 小时上限。
3. **储能与负载时移存在轻微替代。** 在 `flex_ratio=0.30` 时，无储能时移节省比联合场景多 711.1716 CNY；到 1.00 时差额为 843.4338 CNY。该差额只说明本模型内两种灵活性资源的边际价值部分重叠，不代表真实系统中的普遍因果关系。
4. **结算尾段成本随比例上升。** `flex_ratio=1.0` 时，两个场景的结算尾段成本分别为 3,328.8666 和 3,493.4139 CNY；总成本仍保持下降，说明尾段成本已被完整计入上述节省结果。

## 结论边界

- 结果只适用于当前负载、Houston 2020 年 5 月能源情景、设备参数和 3 小时最大延迟。
- 扫描改变的是可移峰负载比例，不等同于改变预测误差、用户服务等级或真实任务完成率。
- 单次确定性运行不能给出统计显著性或跨情景稳健性；后续需要跨月份、不同价格与可再生能源轨迹验证。

## 统计谬误检查

- Coverage: 11/11 checked

| 类型 | 级别 | 检查结果 |
| --- | --- | --- |
| Simpson's paradox | NOTE | 未设置分组变量，当前汇总无法检验分组趋势反转。 |
| Ecological fallacy | NOTE | 未从聚合算例推断单个服务器或单个任务行为。 |
| Berkson's paradox | NOTE | 不涉及按结果筛选样本；但能源数据固定为单月。 |
| Collider bias | NOTE | 不含回归控制变量。 |
| Base-rate neglect | NOTE | 不涉及分类率、患病率或条件概率。 |
| Regression to the mean | NOTE | 不属于按极端值选组的前后测设计。 |
| Survivorship bias | NOTE | 所有 22 个预设格点均报告，无退出样本。 |
| Look-elsewhere effect | NOTE | 全部扫描点均披露，未只选择成本最低点。 |
| Garden of forking paths | CAUTION | 当前参数路径固定，但尚无预注册或跨参数稳健性检验。 |
| Correlation is not causation | CAUTION | 结果是模型内反事实比较，不能直接解释为真实运行中的因果效应。 |
| Reverse causality | NOTE | 不涉及横截面相关方向推断。 |

## 相关产物

- `figures/flex_ratio_total_cost.png`
- `figures/flex_ratio_cost_savings.png`
- `figures/flex_ratio_marginal_savings.png`
