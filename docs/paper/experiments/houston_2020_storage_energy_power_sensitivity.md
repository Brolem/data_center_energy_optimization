# 固定 3 小时时移的储能能量×功率敏感性分析

## 目的

在固定任务时移能力的条件下，分别改变储能能量和充、放电功率，识别容量与功率对联合运行成本、以及储能对时移价值影响的差异。这样避免了仅按固定能量/功率比放大储能时，无法区分到底是容量还是功率产生作用的问题。

## 实验设置

- 负载、风光、电价和其余模型参数均沿用 Houston 2020 主实验。
- `max_delay_h=3`、`flex_ratio=0.30` 固定不变。
- 电池能量扫描为 2、4、6 MWh；充电功率与放电功率相同，并独立扫描为 0.5、1、1.5 MW。
- 共 9 个网格点；每个网格点独立求解 `renewables_only`、`renewables_shift`、`renewables_storage` 和 `joint` 四个正式算例。
- `operating_cost_cny` 为 672 小时分析期成本与第 28 天 3 小时结算尾段成本之和，不计预热期成本。

## 运行

```powershell
conda run -n scip_env python -m experiments.paper sensitivity storage-energy-power
```

默认输出到 `outputs/paper/houston_2020/sensitivity/storage_energy_power/`。可使用 `--workload-data`、`--energy-data`、`--output-dir` 和 `--show-solver-log` 修改输入、输出和求解日志。

终端只打印联合成本最低的储能组合与“储能对时移价值影响”的取值范围，完整的九格指标写入结果 CSV 和两张热图。

## 指标

对每个网格点：

\[
S_{\text{no storage}} = C_{\text{renewables only}} - C_{\text{renewables shift}}
\]

\[
S_{\text{with storage}} = C_{\text{renewables storage}} - C_{\text{joint}}
\]

\[
\Delta S = S_{\text{with storage}} - S_{\text{no storage}}
\]

`joint_cost_cny` 是主要成本指标；`storage_effect_on_shift_cny` 即 \(\Delta S\)。正值表示储能增强了时移节省，负值表示储能削弱了时移节省。

## 输出结构

```text
outputs/paper/houston_2020/sensitivity/storage_energy_power/
├── experiments/
│   ├── energy_2p0_mwh_power_0p5_mw/
│   ├── …（共 9 个独立项目）
│   └── energy_6p0_mwh_power_1p5_mw/
├── results/storage_energy_power_sensitivity.csv
├── figures/storage_energy_power_joint_cost.png
├── figures/storage_energy_power_shift_effect.png
├── analysis.md
└── run_metadata.json
```

两张热图的横轴为电池功率、纵轴为电池能量。每个格点均标记数值，以便同时比较整个敏感性空间和具体组合。
