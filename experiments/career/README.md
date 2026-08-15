# 求职线

本目录提供一个独立于论文线的求职展示闭环：ERCOT 2025 能源信号的日前预测，驱动 Spot GPU 作业反事实重放下的滚动调度，并以真实信号进行事后结算。

在项目根目录运行：

```powershell
conda run -n scip_env python -m experiments.career ercot-2025-spot-gpu-day-ahead
```

结果通过原子发布写入 `outputs/career/ercot_2025_spot_gpu_prediction_driven_dispatch/day_ahead/`，其中包含输入清单、验证集预测指标、测试预测、三组调度、实际结算、决策指标和两张图。可用 `--energy-path`、`--spot-job-path`、`--output-dir` 指定已审计的输入或替代输出位置。

边界：这是反事实重放，不代表 Alibaba 在 ERCOT 或 Houston 的真实运行；ERCO 风光是系统级情景信号而非本地数据中心实测发电；GPU-hour 到利用率的映射是代理而非实测功耗。
