# 固定 3 小时时移下的储能规模敏感性分析结果

## 目的

在不改变任务时移能力的前提下，量化扩大储能功率和容量对总运行成本的影响，并衡量储能是否改变时移的成本价值。

## 复现设置

```powershell
conda run -n scip_env python -m experiments.paper sensitivity storage-scale
```

- 负载：Google 2019 聚合工作负载，28 天。
- 能源：Houston 2020 年 5 月风光数据与外生分时电价。
- 共同参数：`flex_ratio=0.30`，`max_delay_h=3`。
- 成本口径：672 小时分析期加第 28 天 3 小时结算尾段；不计预热期成本。
- 每档分别求解 `renewables_only`、`renewables_shift`、`renewables_storage` 与 `joint` 四个算例。

三档储能分别为 2 MWh / 0.5 MW、4 MWh / 1 MW 和 6 MWh / 1.5 MW。每档完整输入快照、模型、图和结果均保存在各自的独立项目目录中。

## 指标

\[
S_{\mathrm{no\ storage}} = C_{\mathrm{renewables\ only}} - C_{\mathrm{renewables\ shift}}
\]

\[
S_{\mathrm{with\ storage}} = C_{\mathrm{renewables\ storage}} - C_{\mathrm{joint}}
\]

\[
\Delta S = S_{\mathrm{with\ storage}} - S_{\mathrm{no\ storage}}
\]

其中，储能基准节省为 `renewables_only` 与 `renewables_storage` 的成本差；\(\Delta S\) 为储能对时移价值的影响。负值表示储能使时移的边际节省略有下降。

## 结果

所有 12 个模型均返回 `optimal`。

| 储能规模 | 储能基准节省（CNY） | 无储能时移节省（CNY） | 有储能时移节省（CNY） | 储能对时移价值的影响（CNY） |
| --- | ---: | ---: | ---: | ---: |
| 2 MWh / 0.5 MW | 14,170.45 | 29,829.93 | 29,118.76 | -711.17 |
| 4 MWh / 1 MW | 27,721.88 | 29,829.93 | 28,988.29 | -841.64 |
| 6 MWh / 1.5 MW | 41,136.44 | 29,829.93 | 28,827.00 | -1,002.94 |

扩大储能后，储能本身的成本节省从 14,170.45 CNY 增至 41,136.44 CNY，联合优化的总成本也持续下降。与此同时，有储能时移节省相对无储能基准仅下降 2.4%–3.4%。因此，在这一固定 3 小时窗口和该 28 天场景中，储能与时移存在轻微替代关系，但耦合强度有限；这一结论不应直接外推至更长延迟窗口、不同电价或不同风光条件。

## 可复核产物

- [汇总指标 CSV](../../outputs/houston_2020_storage_scale_sensitivity/results/storage_scale_sensitivity.csv)
- [总运行成本对比图](../../outputs/houston_2020_storage_scale_sensitivity/figures/storage_scale_total_cost.png)
- [时移价值对比图](../../outputs/houston_2020_storage_scale_sensitivity/figures/storage_scale_shift_value.png)
- [运行元数据](../../outputs/houston_2020_storage_scale_sensitivity/run_metadata.json)
- [2 MWh / 0.5 MW 独立项目](../../outputs/houston_2020_storage_scale_sensitivity/experiments/energy_2p0_mwh_power_0p5_mw/)
- [4 MWh / 1 MW 独立项目](../../outputs/houston_2020_storage_scale_sensitivity/experiments/energy_4p0_mwh_power_1p0_mw/)
- [6 MWh / 1.5 MW 独立项目](../../outputs/houston_2020_storage_scale_sensitivity/experiments/energy_6p0_mwh_power_1p5_mw/)
