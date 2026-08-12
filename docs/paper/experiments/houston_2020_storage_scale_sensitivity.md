# 固定 3 小时延迟的储能规模敏感性分析

## 目的

在不改变任务时移能力的条件下，检验储能功率和容量扩大后，储能自身的降本效果以及储能对时移价值的影响。所有实验固定 max_delay_h=3，因此不同结果之间不混入更长延迟窗口带来的电价或风光匹配机会。

## 储能档位

| 独立项目目录 | 电池能量 | 充电功率 | 放电功率 |
| --- | ---: | ---: | ---: |
| energy_2p0_mwh_power_0p5_mw | 2.0 MWh | 0.5 MW | 0.5 MW |
| energy_4p0_mwh_power_1p0_mw | 4.0 MWh | 1.0 MW | 1.0 MW |
| energy_6p0_mwh_power_1p5_mw | 6.0 MWh | 1.5 MW | 1.5 MW |

每个档位都独立求解 renewables_only、renewables_shift、renewables_storage 和 joint 四个算例，并保留完整输入快照、结果表、图像、模型文件和元数据。

## 运行

~~~powershell
conda run -n scip_env python -m experiments.paper sensitivity storage-scale
~~~

默认输出目录为 outputs/houston_2020_storage_scale_sensitivity/。可使用 --workload-data、--energy-data、--output-dir 和 --show-solver-log 指定输入、输出和求解日志。

## 比较指标

对每个储能档位，使用总运行成本 operating_cost_cny 计算：

\[
S_{\text{no storage}} =
C_{\text{renewables only}} - C_{\text{renewables shift}}
\]

\[
S_{\text{with storage}} =
C_{\text{renewables storage}} - C_{\text{joint}}
\]

\[
\Delta S =
S_{\text{with storage}} - S_{\text{no storage}}
\]

其中，storage_base_savings_cny 衡量储能自身在零时移条件下的降本；storage_effect_on_shift_cny 即 \(\Delta S\)。正值表示储能增强时移价值，负值表示储能削弱时移价值。

## 输出结构

~~~text
outputs/houston_2020_storage_scale_sensitivity/
├── experiments/
│   ├── energy_2p0_mwh_power_0p5_mw/
│   ├── energy_4p0_mwh_power_1p0_mw/
│   └── energy_6p0_mwh_power_1p5_mw/
├── results/storage_scale_sensitivity.csv
├── figures/storage_scale_total_cost.png
├── figures/storage_scale_shift_value.png
├── analysis.md
└── run_metadata.json
~~~

每个 experiments/<档位>/ 都是一个可独立查看和复核的完整项目。父目录的 CSV、两张汇总图和 analysis.md 用于横向比较三档储能规模。
