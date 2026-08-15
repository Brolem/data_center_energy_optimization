# USD 市场结算窗口：开发状态

## 当前状态

求职线实施已开始。本项共享底座改动仅新增通用的 USD/MWh 市场结算窗口；论文线不导入该窗口，也不改变其人民币分项成本语义。

## 边界

- 保持 `dc_energy_opt/optimization/window_model.py`、`dc_energy_opt/optimization/rolling_day_ahead.py` 和 `dc_energy_opt/data/energy.py` 原样；
- 新窗口只复用物理设备参数、柔性工作状态类型与求解器基础设施；
- 新窗口接受有限的正价、零价和负价，并以 `USD/MWh × MW × h` 结算；
- 不读取或换算任何现有人民币运维、退化或成本容差字段；
- 求职线以独立模块调用新窗口，论文实验与输出目录保持隔离。

## 验收记录

- `tests.shared.test_market_window`：3 项测试通过，覆盖负价 USD 结算、储能功率平衡与终端电量、输入长度拒绝；
- `tests/shared`：121 项测试通过；4 项符号链接测试因 Windows 当前权限跳过；
- `dc_energy_opt/optimization/market_window.py` 不包含 `_cny_` 输出或指标字段，且不读取现有人民币成本参数。
