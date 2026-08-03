# 仓库重组实施与验收清单

## 已完成实施

1. 冻结 Houston 主实验、输入哈希和三张核心结果表作为只读基线。
2. 将正式代码整理为 `dc_energy_opt`，拆分配置、数据、优化、实验和报告职责。
3. 将正式数据分层到 `data/workload/` 与 `data/energy/`，并把 Phoenix 历史内容移入独立归档。
4. 将 LP 按算例和窗口分层保存，统一五张正式图片及结果文件名。
5. 抽取 `run_houston_2020_experiment`，实现输入快照、路径冲突校验、同级暂存、整体发布和失败恢复。
6. 建立正式 CLI 与旧参数兼容转换层；兼容层不导出模型、报告或事务内部接口。
7. 将正式测试按单元与集成职责重组；归档测试保持独立发现边界。
8. 将项目说明、数学模型和主实验复现说明整理到扁平文档结构。

## 最终验证命令

```powershell
conda run -n scip_env python -m unittest discover -s tests -t . -v
conda run -n scip_env python -m unittest discover -s archive/legacy_phoenix/tests -t . -v
conda run -n scip_env python -m compileall -q dc_energy_opt scripts run_day_ahead_experiment.py run_first_version.py
conda run -n scip_env python -m pip check
git diff --check dda43b3f79f2a221cb5b5d9d3e07187a74255c2e..HEAD
```

## 主实验复现

```powershell
conda run -n scip_env python run_day_ahead_experiment.py `
  --workload-data data/workload/google_2019_28d_5min.csv `
  --energy-data data/energy/houston_2020_may_hourly.csv `
  --output-dir outputs/houston_2020_main
```

验收输出根目录只能包含 `inputs/`、`results/`、`figures/`、`models/` 和 `run_metadata.json`。应生成 2,700 行小时调度、112 行日指标、4 行算例指标、232 个 LP 和 5 张图片。

## 数值等价检查

使用 `scripts/verify_reorganization_equivalence.py` 比较冻结基线与新结构的 `hourly_dispatch.csv`、`daily_metrics.csv` 和 `case_metrics.csv`：

- 字符串列和列顺序必须完全一致，文本与布尔字段不得缺失；
- 除计时字段外的数值列必须全部有限，并使用绝对容差 `1e-9`；
- 计时字段只验证有限且非负；
- 正式入口和兼容入口生成的三张核心结果表必须满足相同规则。

## 静态验收

- 正式包不导出归档模块；
- CLI 不包含模型构建、绘图或回滚实现；
- 优化模块不复制输入或发布文件；
- 数据模块不写实验输出；
- `docs/` 不含子目录；
- 工作区根目录和远程仓库名称保持不变；
- 所有提交只保留在本地分支，不推送。
