# ERCOT 2025 Spot GPU 预测驱动调度：开发状态

## 当前状态

预测、Spot GPU 反事实重放、27 小时滚动日前调度、真实信号事后结算和原子结果包均已实现。求职线仅写入 `outputs/career/`，论文线入口、固定窗口输入快照和输出目录未被改写。

## 本次验收运行

- 命令：`conda run -n scip_env python -m experiments.career ercot-2025-spot-gpu-day-ahead --spot-job-path D:\Users\Desktop\data_center_energy_optimization\data\workload\alibaba_2026_spot_gpu_job_info_df.csv`
- 结果包：`outputs/career/ercot_2025_spot_gpu_prediction_driven_dispatch/day_ahead/`
- 结果内容：固定时间划分输入快照、8,437 个 Spot 作业的 720 小时重放、验证集指标、720 小时测试日前预测、三个 723 小时调度、2,169 行实际结算、决策指标和两张 PNG 图。
- 验证判据：基线验证汇总 NMAE 为 `0.3294212438148784`；特征模型为 `0.3512603801165956`，因此 `feature_model_deployable=false`。特征模型调度保留为对照，不能称为验证通过或可部署。
- 已运行测试：输入契约、重放、预测、滚动调度与结算共 22 项通过；完整 CLI 结果包测试使用临时 Spot 作业表完成整套求解并发布全部必需文件。

## 已完成前置核验

- 原始 ERCOT 价格、EIA ERCO 能源信号和 Alibaba Spot GPU 作业数据已放入共享 `data/` 目录；
- `LZ_HOUSTON` 价格在 2025 年有完整 8,760 小时记录；
- EIA ERCO 风电、光伏原始值各有 48 个缺失时点，不能直接作为全部测试窗口；
- Alibaba Spot GPU 作业没有绝对时间、地点、时区和实测功耗，求职线只能进行明确标注的反事实重放。
- 求职线固定使用本地日期 `2025-01-01` 至 `2025-06-30` 训练、`2025-07-01` 至 `2025-07-30` 验证、`2025-08-01` 至 `2025-08-30` 测试，并以 `2025-08-31` 前 3 小时完成结算闭环。

## 实现闭环

1. 求职线从公共年度表创建独立的训练、验证、测试和三小时结算尾段输入快照；
2. 固定 Spot 相对秒区间、GPU-hour 代理公式和利用率缩放已写入输入清单；
3. 朴素前一日基线与 Ridge 特征模型均按日滚动，只使用各截止点之前的历史；
4. 预测场景与完全信息参考均使用同一物理参数和滚动窗口，并以实际价格与实际风光信号结算；
5. 结果通过 `staged_run_directory` 原子发布，输入 SHA-256 和运行元数据一并保存。

## 隔离规则

- 不读取论文线的固定窗口输入快照作为求职线训练或测试数据；
- 不修改论文线实验入口、模型结论或输出目录；
- 求职线运行产物只写入 `outputs/career/`；
- 共享底座变化另建 `docs/development/shared/` 状态文档，不写入本文件。
