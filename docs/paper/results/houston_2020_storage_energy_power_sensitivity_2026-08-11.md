# 固定 3 小时时移的储能能量×功率敏感性分析结果

## 设置与口径

使用 Google 2019 聚合工作负载、Houston 2020 年 5 月风光数据和外生分时电价。所有网格点固定 `flex_ratio=0.30` 与 `max_delay_h=3`；成本包含 672 小时分析期和第 28 天 3 小时结算尾段，不计预热期成本。

电池能量取 2、4、6 MWh，充放电功率相同且取 0.5、1、1.5 MW。九个组合各自独立求解四个正式算例，共 36 次求解。

```powershell
conda run -n scip_env python -m experiments.paper sensitivity storage-energy-power
```

## 结果

| 能量（MWh） | 功率（MW） | 联合成本（CNY） | 储能对时移价值的影响（CNY） |
| ---: | ---: | ---: | ---: |
| 2 | 0.5 | 1,094,637.05 | -711.17 |
| 2 | 1.0 | 1,094,631.78 | -829.29 |
| 2 | 1.5 | 1,094,631.77 | -829.27 |
| 4 | 0.5 | 1,081,595.57 | -642.48 |
| 4 | 1.0 | 1,081,216.09 | -841.64 |
| 4 | 1.5 | 1,081,215.15 | -845.92 |
| 6 | 0.5 | 1,076,790.83 | -711.36 |
| 6 | 1.0 | 1,068,043.47 | -984.36 |
| 6 | 1.5 | 1,067,962.82 | -1,002.94 |

最低联合成本出现在 6 MWh / 1.5 MW，为 1,067,962.82 CNY。储能对时移价值的影响在 -1,002.94 至 -642.48 CNY 之间，九个组合均为负，说明在该固定 3 小时窗口与这组输入下，储能与时移表现为轻微替代，而非互补。

容量扩展带来的成本下降整体大于低容量下的功率扩展：在 2 MWh 时，将功率从 0.5 MW 提升至 1.5 MW 只降低 5.28 CNY；在 6 MWh 时，相同功率扩展降低 8,828.01 CNY。功率提升到 1 MW 后，继续提升至 1.5 MW 的增益均较小，表明本场景的高功率收益已接近饱和。此结论只适用于当前 3 小时延迟、28 天输入与成本参数，不应外推到其他延迟窗口或能源场景。

## 求解状态

36 个结果中 35 个为 `optimal`。4 MWh / 1.5 MW 的 `renewables_storage` 算例为 `gaplimit`，记录的 `mip_gap=2.04e-8`，小于配置的 `relative_gap=1e-6`；其余结果均为 `optimal`。汇总脚本将两种状态均作为可接受结果，因此表中保留该组合，并明确记录该差异。

## 可复核产物

- [汇总指标 CSV](../../outputs/houston_2020_storage_energy_power_sensitivity/results/storage_energy_power_sensitivity.csv)
- [联合成本热图](../../outputs/houston_2020_storage_energy_power_sensitivity/figures/storage_energy_power_joint_cost.png)
- [储能对时移价值影响热图](../../outputs/houston_2020_storage_energy_power_sensitivity/figures/storage_energy_power_shift_effect.png)
- [运行元数据](../../outputs/houston_2020_storage_energy_power_sensitivity/run_metadata.json)
- [九个独立项目目录](../../outputs/houston_2020_storage_energy_power_sensitivity/experiments/)
