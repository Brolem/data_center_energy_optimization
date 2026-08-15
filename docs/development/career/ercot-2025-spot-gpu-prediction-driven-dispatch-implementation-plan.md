# ERCOT 2025 Spot GPU 预测驱动调度实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可复现的求职展示项目：对 ERCOT `LZ_HOUSTON` 日前价格、ERCO 光伏和风电信号做严格时间顺序的日前预测，以预测值驱动 Spot GPU 工作量的滚动调度，并以真实信号完成事后结算、对照与可解释结果输出。

**Architecture:** 共享层新增不含人民币运维项的市场结算窗口求解器；求职线在 `experiments/career/ercot_2025_spot_gpu/` 中实现能源输入契约、作业反事实重放、预测、滚动日前决策、事后结算和报告。论文线既有的 Houston 输入加载器、优化器和入口均不修改。公共年度能源表只是输入来源；求职线独立创建时间划分和输入快照。

**Tech Stack:** Python 3.13、NumPy 2.5.1、pandas 3.0.5、PySCIPOpt 6.2.1、unittest、现有原子产物发布工具。

---

## 0. 固定实验契约

本计划中的日期、列名、单位和重放规则在实现时写入代码常量与运行清单；不得根据运行结果自动改变。

| 项目 | 固定值 | 用途与边界 |
| --- | --- | --- |
| 公共能源输入 | `data/energy/ercot_2025_houston_hourly.csv` | 只读年度审计表，不读取论文线窗口快照。 |
| 严格列顺序 | `timestamp_utc`, `local_date`, `local_hour`, `local_time_end`, `delivery_date`, `hour_ending`, `repeated_hour_flag`, `dam_lz_houston_usd_per_mwh`, `erco_solar_generation_mwh`, `erco_wind_generation_mwh`, `erco_consumed_co2_intensity_lbs_per_kwh` | 必须逐项相等，拒绝重排、增列和缺列。 |
| 训练期 | 本地日期 `2025-01-01` 至 `2025-06-30`，4,343 小时 | 只用于拟合特征预测器和训练期归一化统计量。春令时当天仍依 `timestamp_utc` 保持连续。 |
| 验证期 | 本地日期 `2025-07-01` 至 `2025-07-30`，720 小时 | 评估朴素预测与特征预测；不参与该期首日的预测拟合。 |
| 测试期 | 本地日期 `2025-08-01` 至 `2025-08-30`，720 小时 | 每日滚动日前决策的分析期；价格波动强于原先的秋季测试期。 |
| 测试结算尾段 | `2025-08-31` 的前 3 小时，3 小时 | 仅完成测试期最后 3 小时到达的可延迟工作和储能终端状态；报告中单独标记为 `settlement_closure`。 |
| 预测目标 | `dam_lz_houston_usd_per_mwh`、`erco_solar_generation_mwh`、`erco_wind_generation_mwh` | 碳字段不进入第一阶段。 |
| 风光情景归一化 | 光伏 `29,503 MWh`；风电 `28,264 MWh` | 固定为 2025 公共年度表的各自最大观测值，只用于将系统级信号转换为无量纲可用性指数；不是 Houston 本地实测出力、装机容量或预测训练统计量。 |
| 作业重放块 | 相对秒 `[7,776,000, 10,368,000)`，即第 4 个完整 30 天块 | 块内有 8,437 个 `Spot` 作业。相对时间锚定到测试期起点，不声称其与 ERCOT 的历史日历相同。 |
| 工作量代理 | `gpu_request * worker_num * duration / 3600` | 逐小时聚合为 GPU-hour 工作量代理。它没有实测功耗含义。 |
| 工作量缩放 | `0.60 * hourly_gpu_hour_work / max(hourly_gpu_hour_work)` | 生成 `workload_arrival_pu`；`0.60` 是情景峰值利用率，完整保留相对形状，不能称为实际 MW 或实际集群利用率。 |
| 输出根目录 | `outputs/career/ercot_2025_spot_gpu_prediction_driven_dispatch/day_ahead` | 通过现有 `staged_run_directory` 原子发布；不写入 `outputs/paper/`。 |

每个预测截止点只能使用该截止点之前的真实能源记录。价格预测允许为负值；风光预测裁剪到 `[0, 对应年度归一化常数]`。预测调度只读取预测的价格和风光；真实价格与真实风光只在事后结算函数中读取。

作业数据没有公开绝对日期、地点、时区和实测功耗。因此，本项目的名称和报告均使用“反事实重放”，并将服务指标称为“Spot 工作量服务”，不称为生产作业 SLA。

## 1. 实现前置核验与目录边界

**Files:**

- Create: `docs/development/shared/market-settlement-window.md`
- Modify: `docs/development/career/ercot-2025-spot-gpu-prediction-driven-dispatch.md`
- Create: `tests/career/__init__.py`
- Create: `tests/career/test_ercot_2025_input_contract.py`

- [ ] **Step 1: 为共享市场结算能力与求职线状态分别登记边界。**

  在 `docs/development/shared/market-settlement-window.md` 中明确：新增共享代码只提供通用 USD/MWh 市场结算窗口，论文线不导入它；现有 `dc_energy_opt/optimization/window_model.py`、`dc_energy_opt/optimization/rolling_day_ahead.py` 和 `dc_energy_opt/data/energy.py` 保持不变。在求职线开发状态中补入本计划的固定训练、验证、测试日期以及“实施中”状态。

- [ ] **Step 2: 先为公共表契约写失败测试。**

  在 `tests/career/test_ercot_2025_input_contract.py` 使用临时 CSV 构造测试，覆盖：

  ```python
  self.assertEqual(frame.columns.tolist(), ENERGY_COLUMNS)
  with self.assertRaisesRegex(ValueError, "字段顺序"):
      load_energy_table(reordered_path)
  with self.assertRaisesRegex(ValueError, "缺失"):
      build_energy_splits(frame_with_na)
  ```

  还要覆盖以下精确规则：`timestamp_utc` 必须唯一、升序且相邻相差一小时；年度表必须保留 EIA 发布的原始空值，固定训练、验证、测试与结算尾段内的三个目标则必须为有限数值；测试期加 3 小时尾段必须连续；负的 `dam_lz_houston_usd_per_mwh` 不得被拒绝。

- [ ] **Step 3: 运行失败测试，确认测试先红。**

  Run: `conda run -n scip_env python -m unittest tests.career.test_ercot_2025_input_contract -v`

  Expected: 因 `ENERGY_COLUMNS`、`load_energy_table` 与 `build_energy_splits` 尚未实现而失败。

- [ ] **Step 4: 提交本阶段文档与测试骨架。**

  Run: `git add docs/development/shared/market-settlement-window.md docs/development/career/ercot-2025-spot-gpu-prediction-driven-dispatch.md tests/career/__init__.py tests/career/test_ercot_2025_input_contract.py; git commit -m "test: define career energy input contract"`

## 2. 建立独立能源输入、时间切分和 Spot 重放

**Files:**

- Create: `experiments/career/ercot_2025_spot_gpu/__init__.py`
- Create: `experiments/career/ercot_2025_spot_gpu/config.py`
- Create: `experiments/career/ercot_2025_spot_gpu/data.py`
- Create: `experiments/career/ercot_2025_spot_gpu/replay.py`
- Create: `tests/career/test_ercot_2025_replay.py`
- Modify: `tests/career/test_ercot_2025_input_contract.py`

- [ ] **Step 1: 定义不可变的项目配置。**

  在 `config.py` 用 `dataclass(frozen=True)` 和元组保存公共路径、列顺序、日期范围、3 小时结算尾段、风光归一化常数、作业块和 `0.60` 峰值利用率。配置必须直接使用下列值，而不是搜索“较好”的窗口：

  ```python
  REPLAY_START_SECONDS = 7_776_000
  REPLAY_STOP_SECONDS = 10_368_000
  ANALYSIS_HOURS = 720
  SETTLEMENT_CLOSURE_HOURS = 3
  SOLAR_SIGNAL_MAX_MWH = 29_503.0
  WIND_SIGNAL_MAX_MWH = 28_264.0
  WORKLOAD_PEAK_PU = 0.60
  ```

  `CareerPaths` 只包含 `data/energy/ercot_2025_houston_hourly.csv`、`data/workload/alibaba_2026_spot_gpu_job_info_df.csv` 和上述输出根目录；不要创建或引用论文线输入路径。

- [ ] **Step 2: 实现严格读取与时间顺序切分。**

  在 `data.py` 实现 `load_energy_table(path: Path) -> pd.DataFrame`、`build_energy_splits(frame: pd.DataFrame) -> EnergySplits` 和 `map_generation_signal_to_available_mw(...)`。读取器应严格核对完整列顺序、UTC 小时连续性、DAM 价格数值有效性，并保留 EIA 发布的原始风光空值及其余审计列；不得填补年度表。切分函数按 `local_date` 过滤固定日期，并在每个训练、验证、测试与结算尾段内断言三个预测目标为有限数值，训练、验证、测试分别为 181 个、30 个、30 个本地日期，训练期为 4,343 小时，验证和测试各为 720 小时，测试尾段为 3 小时且紧随测试期。

  风光映射采用下式，并在元数据中写明 `scenario_normalization`：

  ```python
  solar_available_mw = (
      solar_generation_mwh / SOLAR_SIGNAL_MAX_MWH
  ) * params.solar_inverter_capacity_mw
  wind_available_mw = (
      wind_generation_mwh / WIND_SIGNAL_MAX_MWH
  ) * params.wind_capacity_mw
  ```

  若风光原始值超出固定归一化常数或映射后超出对应容量，抛出异常，不能静默裁剪真实值。预测值的裁剪只在预测模块完成。

- [ ] **Step 3: 实现可审计的相对时间 Spot 重放。**

  `replay.py` 只接受列顺序精确为 `job_name`, `organization`, `gpu_model`, `cpu_request`, `gpu_request`, `worker_num`, `submit_time`, `duration`, `job_type` 的作业表。先筛选 `job_type == "Spot"` 与固定半开区间；再按以下规则输出 720 行的逐小时表：

  ```python
  replay_hour = (submit_time - REPLAY_START_SECONDS) // 3600
  gpu_hour_work = gpu_request * worker_num * duration / 3600.0
  hourly_gpu_hour_work = grouped.reindex(range(ANALYSIS_HOURS), fill_value=0.0)
  workload_arrival_pu = (
      WORKLOAD_PEAK_PU
      * hourly_gpu_hour_work
      / hourly_gpu_hour_work.max()
  )
  ```

  输入列应先转为数值并拒绝负数、非有限数值、块外小时和零峰值。输出还应保存每小时 `spot_job_count`、`hourly_gpu_hour_work`、`workload_arrival_pu`，以及运行清单需要的块范围和块内作业数。这里的 `workload_arrival_pu` 是聚合工作量代理，不得命名为 `gpu_power_mw`。

- [ ] **Step 4: 补齐数据与重放测试后实现，使测试转绿。**

  `test_ercot_2025_input_contract.py` 必须检验精确日期切分、连续的 723 小时测试结算输入、允许负价格、拒绝风光缺失。`test_ercot_2025_replay.py` 用小型 DataFrame 检验区间下界包含、上界排除、GPU-hour 聚合、缺失小时补零、峰值为 `0.60` 以及列顺序变动被拒绝。

  Run: `conda run -n scip_env python -m unittest discover -s tests/career -t . -v`

  Expected: 所有求职线输入与重放测试通过。

- [ ] **Step 5: 提交输入与重放实现。**

  Run: `git add experiments/career/ercot_2025_spot_gpu tests/career; git commit -m "feat: add career data contract and spot replay"`

## 3. 实现无单位混用的市场结算窗口求解器

**Files:**

- Create: `dc_energy_opt/optimization/market_window.py`
- Create: `tests/shared/test_market_window.py`
- Modify: `docs/development/shared/market-settlement-window.md`

- [ ] **Step 1: 为美元结算与负电价写窗口级测试。**

  在 `tests/shared/test_market_window.py` 建立 3 至 27 小时的小型可行场景。测试应验证：

  ```python
  self.assertAlmostEqual(
      metrics["grid_settlement_usd"],
      (result["price_usd_per_mwh"] * result["grid_power_mw"]).sum(),
  )
  self.assertLess(result.loc[negative_price_hour, "price_usd_per_mwh"], 0.0)
  self.assertLessEqual(metrics["maximum_work_delay_h"], params.max_delay_h)
  ```

  还要验证功率平衡、工作量守恒、储能不能同时充放电、终端 SOC 约束、输入长度不一致被拒绝，以及结果和指标中没有 `_cny_` 字段。

- [ ] **Step 2: 实现共享的 `build_and_solve_market_window`。**

  新函数只接收 `workload_arrival_pu`、`solar_available_mw`、`wind_available_mw`、`price_usd_per_mwh`、`Parameters`、窗口状态与 24 小时提交长度。它复用 `Parameters` 的物理设备参数与 `PendingFlexibleTask`/`WindowSolveState` 类型，但绝不读取以下人民币成本字段：`solar_om_cost_cny_per_kwh`、`wind_om_cost_cny_per_kwh`、`battery_om_cost_cny_per_kwh`、`battery_degradation_cost_cny_per_kwh`、`primary_cost_tolerance_cny`。

  主目标必须精确为：

  ```python
  grid_settlement_usd = quicksum(
      float(price_usd_per_mwh[t])
      * grid_power[t]
      * params.time_step_h
      for t in hours
  )
  ```

  因此 `USD/MWh × MW × h = USD`，不乘 `1000`，且 `price_usd_per_mwh` 只要求有限，不要求非负。保持与现有窗口模型一致的负荷守恒、最大延迟、IT 功率映射、PUE、风光分配、储能状态和充放电互斥约束。

  为消除同成本解的任意性，按以下字典序求解，每一步都以 `1e-6` 的对应单位容差约束前一步最优值：

  1. 最小化 `grid_settlement_usd`；
  2. 最小化总 Spot 工作量延迟；
  3. 最小化可再生能源弃电量；
  4. 最小化电池充放电吞吐量。

  输出字段统一使用 `workload_arrival_pu`、`workload_scheduled_pu`、`price_usd_per_mwh`、`hourly_grid_settlement_usd`、`grid_power_mw`、`solar_*_mw`、`wind_*_mw`、`charge_mw`、`discharge_mw` 和 `stored_energy_*_mwh`。四个求解阶段分别写入窗口内的 `stage_1_settlement.lp`、`stage_2_delay.lp`、`stage_3_curtailment.lp`、`stage_4_throughput.lp`。

- [ ] **Step 3: 运行共享窗口测试与既有共享回归。**

  Run: `conda run -n scip_env python -m unittest tests.shared.test_market_window -v`

  Run: `conda run -n scip_env python -m unittest discover -s tests/shared -t . -v`

  Expected: 新窗口测试通过；现有 `window_model.py` 与 Houston 数据加载测试保持通过，证明没有改变论文线成本语义。

- [ ] **Step 4: 在共享开发状态中记录验收结论并提交。**

  Run: `git add dc_energy_opt/optimization/market_window.py tests/shared/test_market_window.py docs/development/shared/market-settlement-window.md; git commit -m "feat: add usd market settlement window"`

## 4. 实现不泄漏的日前预测与验证选择

**Files:**

- Create: `experiments/career/ercot_2025_spot_gpu/forecasting.py`
- Create: `tests/career/test_ercot_2025_forecasting.py`

- [ ] **Step 1: 为逐日截止点与未来隔离写测试。**

  在 `test_ercot_2025_forecasting.py` 构造带价格负值、日周期和风光非负值的小时序列。测试 `previous_day_forecast` 返回同一小时前 24 小时值；测试特征预测器只用 `forecast_origin` 之前的行；把截止点之后的真实值改成极大值后，截止点预测必须逐元素完全相同。

- [ ] **Step 2: 实现两个 24 小时日前预测器。**

  `previous_day_forecast(history, target_columns)` 为固定基线，直接取每个预测小时的 `t - 24` 实测值。`DirectRidgeDayAheadForecaster` 只用 NumPy 实现，避免新增依赖：对每一目标、每一小时用可用历史构造 `lag_24`、`lag_168`、本地小时的正弦/余弦和星期几 one-hot 特征；在拟合数据内部标准化特征，以 `np.linalg.solve(X.T @ X + alpha * I, X.T @ y)` 求解，截距列不正则化，`alpha=1.0`。拟合行与预测目标之间至少相隔一个小时，且所有滞后均位于截止点前。

  对风光预测执行：

  ```python
  predicted_solar = np.clip(predicted_solar, 0.0, SOLAR_SIGNAL_MAX_MWH)
  predicted_wind = np.clip(predicted_wind, 0.0, WIND_SIGNAL_MAX_MWH)
  ```

  价格预测不裁剪，以保留负价与尖峰的预测误差。输出的预测表应包含 `forecast_origin_utc`、`timestamp_utc`、三个 `actual_*` 列、三个 `baseline_*` 列和三个 `feature_model_*` 列。

- [ ] **Step 3: 定义验证指标和是否可部署的判据。**

  对每个目标分别计算 MAE 与 RMSE。验证选择分数为三目标 NMAE 的算术平均，目标的 NMAE 分母是训练期该目标的总体标准差（`ddof=0`）；若任一分母不为正，运行直接失败。只有当 `feature_model_validation_score < baseline_validation_score` 时，清单字段 `feature_model_deployable` 才为 `true`。无论这一布尔值如何，报告均输出两种预测和后续三组调度对照；若为 `false`，报告首页必须标明特征模型没有通过验证、不得作为项目结论。

- [ ] **Step 4: 运行预测测试。**

  Run: `conda run -n scip_env python -m unittest tests.career.test_ercot_2025_forecasting -v`

  Expected: 基线、特征模型、风光裁剪和“修改未来不改变当期预测”均通过。

- [ ] **Step 5: 提交预测层。**

  Run: `git add experiments/career/ercot_2025_spot_gpu/forecasting.py tests/career/test_ercot_2025_forecasting.py; git commit -m "feat: add leakage-safe day-ahead forecasts"`

## 5. 实现滚动日前决策、真实结算与三组对照

**Files:**

- Create: `experiments/career/ercot_2025_spot_gpu/rolling.py`
- Create: `experiments/career/ercot_2025_spot_gpu/settlement.py`
- Create: `tests/career/test_ercot_2025_rolling_settlement.py`

- [ ] **Step 1: 写清决策与结算的因果接口，并先用玩具数据测试。**

  测试应使用 30 小时小型数组，比较“预测调度”与“完全信息调度”。对预测调度，断言优化器收到的是 `forecast_*`，结算器收到的是 `actual_*`；改变某小时真实价格只改变事后结算成本，不能改变该日已经生成的工作量、充放电和风光使用计划。

  结算使用下式，且只使用调度已计划的风光利用量：

  ```python
  actual_solar_used_mw = np.minimum(
      planned["solar_used_mw"], actual_solar_available_mw
  )
  actual_wind_used_mw = np.minimum(
      planned["wind_used_mw"], actual_wind_available_mw
  )
  actual_grid_power_mw = (
      planned["dc_power_mw"]
      + planned["charge_mw"]
      - planned["discharge_mw"]
      - actual_solar_used_mw
      - actual_wind_used_mw
  )
  actual_grid_settlement_usd = (
      actual_price_usd_per_mwh * actual_grid_power_mw * params.time_step_h
  )
  ```

  测试还必须断言 `actual_grid_power_mw >= 0`、最终测试结算包含恰好 723 小时、最后三小时的 `period_role == "settlement_closure"`，以及相同输入得到相同结果。

- [ ] **Step 2: 实现每日 27 小时滚动日前调度。**

  `rolling.py` 对测试期的每个本地日执行一次窗口求解：当日 24 小时加后续 3 小时前视；仅前 24 小时成为 `analysis` 已提交动作。前三小时前视不创建新柔性工作，来自当天最后三小时的柔性工作可在其中完成。`PendingFlexibleTask` 逐日传递，储能状态由上一日已提交末状态传递。最后一个日窗口把储能终端状态约束回初始 SOC，并将 3 小时前视提交为 `settlement_closure`。

  运行三种输入完全相同、仅能源信息不同的情景：

  1. `oracle_actual`：每个 27 小时窗口使用真实价格、真实风光；
  2. `baseline_forecast`：每个窗口使用朴素预测；
  3. `feature_model_forecast`：每个窗口使用特征预测。

  作业重放工作量是日前已知的反事实情景输入；第一阶段不增加工作量预测。每个情景都通过同一市场窗口求解器运行，不能将预测结果替换为真实值。

- [ ] **Step 3: 实现事后结算与指标表。**

  `settlement.py` 对三个情景按真实价格和真实风光结算，输出 `actual_hourly_settlement.csv` 与一行一情景的 `decision_metrics.csv`。后者至少包含：

  - `actual_grid_settlement_usd` 与 `actual_grid_purchase_energy_mwh`；
  - `actual_renewable_curtailment_energy_mwh`；
  - `battery_charged_energy_mwh`、`battery_discharged_energy_mwh`；
  - `spot_work_arrived_pu_hours`、`spot_work_scheduled_pu_hours`、`spot_work_completion_rate`、`average_flexible_work_delay_h`、`maximum_work_delay_h`；
  - `decision_regret_usd`，精确定义为该情景 `actual_grid_settlement_usd - oracle_actual` 的同口径值。

  对 `oracle_actual` 的遗憾值断言为零（允许绝对误差 `1e-6`）。总成本在第一阶段等于市场结算成本；不要引入或换算任何人民币运维、折旧或退化费用。

- [ ] **Step 4: 运行滚动与结算测试。**

  Run: `conda run -n scip_env python -m unittest tests.career.test_ercot_2025_rolling_settlement -v`

  Run: `conda run -n scip_env python -m unittest discover -s tests/career -t . -v`

  Expected: 所有情景严格区分预测输入和真实结算输入；工作量和电池状态跨日连续；遗憾定义可复算。

- [ ] **Step 5: 提交滚动调度与结算层。**

  Run: `git add experiments/career/ercot_2025_spot_gpu/rolling.py experiments/career/ercot_2025_spot_gpu/settlement.py tests/career/test_ercot_2025_rolling_settlement.py; git commit -m "feat: add forecast-driven rolling settlement"`

## 6. 提供可运行入口、原子结果包与求职展示报告

**Files:**

- Create: `experiments/career/cli.py`
- Create: `experiments/career/__main__.py`
- Create: `experiments/career/ercot_2025_spot_gpu/run.py`
- Create: `experiments/career/ercot_2025_spot_gpu/reporting.py`
- Create: `tests/career/test_ercot_2025_cli.py`
- Modify: `experiments/career/README.md`
- Modify: `docs/career/ercot-2025-spot-gpu-prediction-driven-dispatch.md`
- Modify: `docs/development/career/ercot-2025-spot-gpu-prediction-driven-dispatch.md`

- [ ] **Step 1: 先写 CLI 与结果包测试。**

  `test_ercot_2025_cli.py` 在 `TemporaryDirectory()` 中构造输出目录，并调用 `main(["ercot-2025-spot-gpu-day-ahead", "--output-dir", str(output_path)])`。测试应检查：CLI 返回 0；已发布目录只含完整结果包；结果包有 `inputs/`、`models/`、`results/`、`figures/`；失败的运行不覆盖原有完整输出；不创建 `outputs/paper/` 下的任何路径。

- [ ] **Step 2: 实现唯一的求职线命令与原子发布。**

  `experiments/career/__main__.py` 调用 `experiments.career.cli.main`。CLI 只提供一个一级命令：

  ```powershell
  conda run -n scip_env python -m experiments.career ercot-2025-spot-gpu-day-ahead
  ```

  `run.py` 使用 `dc_energy_opt.artifacts.staged_run_directory` 与 `build_run_provenance`，并将以下文件写入临时目录后再一次发布：

  ```text
  inputs/energy_splits.csv
  inputs/spot_replay_720h.csv
  inputs/input_manifest.json
  models/forecast_validation_metrics.csv
  models/test_day_ahead_predictions.csv
  results/oracle_actual_hourly_schedule.csv
  results/baseline_forecast_hourly_schedule.csv
  results/feature_model_forecast_hourly_schedule.csv
  results/actual_hourly_settlement.csv
  results/decision_metrics.csv
  figures/forecast_actual_vs_prediction.png
  figures/actual_settlement_comparison.png
  run_metadata.json
  ```

  `input_manifest.json` 必须含输入 SHA-256、严格列顺序、训练/验证/测试日期、测试尾段、预测器配置、风光情景归一化常数、Spot 块范围、工作量缩放式和“反事实重放”说明。`run_metadata.json` 由现有 provenance 工具生成，并补充 `feature_model_deployable`。

- [ ] **Step 3: 生成只陈述已计算结果的报告。**

  `reporting.py` 生成两张 PNG：三目标的测试实际值/基线/特征预测图，以及三情景实际结算成本和遗憾对比图。图标题和 `docs/career/...` 的最终项目说明必须包含下列限定：

  - Alibaba Spot 轨迹被反事实重放到 ERCOT 2025 信号；
  - ERCO 风光是系统级生成信号，经情景归一化后使用，不是 Houston 本地实测发电；
  - GPU 工作量到利用率的转换是代理，不是实测功耗；
  - 只有在 `feature_model_deployable == true` 时，才可将特征预测调度作为验证通过的展示结论。

  文档不要填写尚未运行得到的 MAE、RMSE、成本、遗憾或节约百分比；这些数值只由结果表和图在正式运行后产生。

- [ ] **Step 4: 执行完整验证与正式最小运行。**

  Run: `conda run -n scip_env python -m unittest discover -s tests/career -t . -v`

  Run: `conda run -n scip_env python -m unittest discover -s tests/shared -t . -v`

  Run: `conda run -n scip_env python -m experiments.career ercot-2025-spot-gpu-day-ahead`

  Run: `conda run -n scip_env python -m unittest discover -s tests -t . -v`

  Run: `git diff --check`

  Expected: 生成完整且原子发布的求职线结果包；所有测试通过；论文线路径无改写；不报告没有由本次运行输出支撑的数值结论。

- [ ] **Step 5: 记录验收结果并提交。**

  在 `docs/development/career/ercot-2025-spot-gpu-prediction-driven-dispatch.md` 中写入实际命令、实际结果包路径、测试结果和验证部署判据的真实状态；更新长期求职线说明的运行命令与边界。

  Run: `git add experiments/career tests/career docs/career/ercot-2025-spot-gpu-prediction-driven-dispatch.md docs/development/career/ercot-2025-spot-gpu-prediction-driven-dispatch.md; git commit -m "feat: publish career forecasting dispatch project"`

## 7. 实施完成后的验收清单

- [ ] 论文线共享年度表通过其独立的 `tests/shared/test_ercot_2025_energy.py`，且求职线没有修改其生成脚本、固定窗口或论文输出。
- [ ] 输入契约拒绝任何列顺序、时间连续性、目标缺失和值域违规；负的市场价格被允许进入市场结算求解器。
- [ ] 验证和测试预测均按日滚动生成；未来真实值的变动不能改变此前截止点的预测或调度决策。
- [ ] 三个调度情景使用同一工作量、物理参数、窗口长度和真实结算函数；只有上游能源信息不同。
- [ ] `decision_regret_usd` 可由结果表复算，且 `oracle_actual` 的遗憾为零。
- [ ] 输出、图表和简历材料不把反事实重放说成 Alibaba 在 Houston/ERCOT 的真实运行，不把系统级风光说成数据中心实测发电，也不把代理利用率说成实测 MW。
