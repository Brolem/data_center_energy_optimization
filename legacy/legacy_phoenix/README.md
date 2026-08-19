# Phoenix/Qinghai 历史能源场景

本目录保存早期 Phoenix 气象源、基于简化功率曲线构造的 24 小时能源场景，以及对应实现和测试。它仅用于追溯旧版实验与验证历史数值行为，不再作为 Houston 2020 正式主实验的数据或代码入口。

- `data/phoenix_nasa_power_20190501_20190528_hourly.csv`：2019-05-01 00:00 至 2019-05-28 23:00 的 672 小时 Phoenix 气象源。
- `data/provisional_phoenix_weather_qinghai_tou_scenario.csv`：由上述气象源按小时聚合并叠加论文分段电价得到的历史 24 小时场景。
- `legacy_energy_data.py`：历史 Phoenix 数据校验、简化光伏/风电出力和场景重建实现。
- `tests/test_legacy_energy_data.py`：历史实现的独立回归测试。

单独运行历史测试：

```powershell
python -m unittest discover -s archive/legacy_phoenix/tests -t . -v
```
