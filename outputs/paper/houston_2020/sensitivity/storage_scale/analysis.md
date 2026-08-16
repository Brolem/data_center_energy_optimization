# 固定 3 小时延迟的储能规模敏感性分析

## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: validate
- Origin Date: 2026-08-16
- Verification Status: VERIFIED
- Version Label: validation_v1
- Source: `results/storage_scale_sensitivity.csv`、`run_metadata.json`
- Overall Confidence: CAUTION（本确定性算例内的数值关系已复算验证，能量与功率同步变化，不能分离两者的独立贡献）

## 结论摘要

当储能从 2 MWh / 0.5 MW 同步扩大到 6 MWh / 1.5 MW 时，联合运行成本由 1,094,637.0545 降至 1,067,962.8219 CNY；相对无储能、无时移基准的总节省由 43,289.2088 增至 69,963.4414 CNY。储能自身的成本节省随规模近似线性增长，但储能存在时负载时移的增量价值略低于无储能场景，表现为轻微资源替代。

## 实验设定与指标

- 全部算例固定 `max_delay_h=3`、`flex_ratio=0.30`。
- 储能能量、充电功率和放电功率按 2/0.5、4/1.0、6/1.5 三组同步变化。
- 每个规模独立运行 28 天四个正式算例。
- `operating_cost_cny` 包含 672 小时分析期与 3 小时结算尾段，不含预热成本。
- 储能基准节省 = `renewables_only - renewables_storage`。
- 无储能时移节省 = `renewables_only - renewables_shift`。
- 有储能时移节省 = `renewables_storage - joint`。
- 储能对时移价值的影响 = 有储能时移节省 − 无储能时移节省。

## 求解与数据完整性

- 汇总表 3 行、12 个状态字段全部为 `optimal`。
- 本次重算使用 `relative_gap=0.0`。
- 运行提交：`a796a0d3f0273d6b8673dd626ccdacc41184609c`。
- 三个规模均完整保留四算例结果；未使用显著性检验或置信区间。

## 结果汇总

| 储能规模 | 联合成本 (CNY) | 储能基准节省 (CNY) | 储能基准节省率 | 有储能时移节省 (CNY) | 储能对时移影响 (CNY) | 影响占无储能时移节省 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 MWh / 0.5 MW | 1,094,637.0545 | 14,170.4470 | 1.2453% | 29,118.7618 | -711.1716 | -2.3841% |
| 4 MWh / 1.0 MW | 1,081,216.0904 | 27,721.8835 | 2.4362% | 28,988.2895 | -841.6440 | -2.8215% |
| 6 MWh / 1.5 MW | 1,067,962.8219 | 41,136.4441 | 3.6150% | 28,826.9974 | -1,002.9361 | -3.3622% |

## 趋势与边际收益

1. **扩大储能持续降低联合成本。** 从第一档升至第二档，联合成本下降 13,420.9641 CNY；从第二档升至第三档，下降 13,253.2685 CNY，第二次扩容的增量收益仅小幅降低。
2. **储能自身节省近似线性增加。** 两次扩容分别增加 13,551.4365 和 13,414.5606 CNY 的储能基准节省，未在三档范围内出现明显饱和。
3. **联合优化总收益继续提高。** 相对 `renewables_only`，三档联合方案分别节省 43,289.2088、56,710.1730 和 69,963.4414 CNY，对应 3.8042%、4.9836% 和 6.1483%。
4. **储能与时移呈轻微替代。** 储能对时移价值的影响始终为负，且绝对值从 711.1716 增至 1,002.9361 CNY；其规模仅相当于无储能时移节省的 2.3841%–3.3622%，因此不能据此判定两者不应联合使用。

## 结论边界

- 容量与功率同步增加，当前三点扫描无法识别能量容量和功率上限的独立边际作用；该问题由容量×功率实验补充。
- 结果只适用于当前价格、可再生能源、负载和设备成本参数。
- 未计入储能投资成本、寿命折旧之外的资本约束及不确定性，因此不能直接作为储能选型的经济最优结论。

## 统计谬误检查

- Coverage: 11/11 checked

| 类型 | 级别 | 检查结果 |
| --- | --- | --- |
| Simpson's paradox | NOTE | 无分组汇总与子组反向趋势检验。 |
| Ecological fallacy | NOTE | 未从系统级结果推断单体设备行为。 |
| Berkson's paradox | NOTE | 不涉及按结果筛选样本；能源数据固定为单月。 |
| Collider bias | NOTE | 不含回归控制变量。 |
| Base-rate neglect | NOTE | 不涉及分类率或条件概率。 |
| Regression to the mean | NOTE | 不属于极端值选组的前后测设计。 |
| Survivorship bias | NOTE | 三个预设规模全部披露。 |
| Look-elsewhere effect | NOTE | 所有规模均报告，未只保留最低成本点。 |
| Garden of forking paths | CAUTION | 仅有三组同步缩放点，尚无更密集网格和跨情景稳健性检验。 |
| Correlation is not causation | CAUTION | 模型内参数比较不等同于真实系统的普遍因果效应。 |
| Reverse causality | NOTE | 不涉及横截面相关方向推断。 |

## 相关产物

- `figures/storage_scale_total_cost.png`
- `figures/storage_scale_shift_value.png`
