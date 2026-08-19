# 归档说明

> 本仓库已冻结归档：保留历史工作用于复现与参考，不再新增功能。

## 状态

- 冻结时间：2026-08-19。
- `main` 保留：共享底座 `dc_energy_opt`、论文线 Houston 2020、求职线 ERCOT 2025、数据与测试。
- 归档 tag（不在 `main` 工作树）：
  - `archive/paper-spot-gpu`：ERCOT 2025 × Alibaba Spot GPU 论文线。
  - `archive/career-forecast-validation`：求职线预测模型选择协议。

## 目录命名说明

- `legacy/`：顶层遗留代码（旧入口与 Phoenix 场景，原 `archive/` 改名而来）。
- `docs/archive/`：更早的历史设计与实施记录。
- `archive/*`：Git 归档 tag 的命名空间（不是目录）。

## 新方向

新的研究已迁移到独立项目，主题为“数据中心算电协同调度（Alibaba cluster-trace-v2018 + PV/BESS + 分布鲁棒/鲁棒优化 + 双侧不确定）”，完整规格见新项目根目录 `README.md`。

## 回看历史

```powershell
git tag -n
git checkout archive/paper-spot-gpu
git show archive/career-forecast-validation
```
