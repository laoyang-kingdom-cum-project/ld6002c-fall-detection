# 04 Python 状态机说明

本项目不是简单地 `if fall: alarm()`，而是在 Python 中加入二次判断状态机，减少短暂误触发造成的误报。

## 状态定义

- 无人：`human_present=False` 且 `fall_detected=False`
- 正常有人：`human_present=True` 且 `fall_detected=False`
- 观察中：`fall_detected=True`，但持续时间小于 `suspect_seconds`
- 疑似跌倒：`fall_detected=True` 持续时间达到 `suspect_seconds`
- 确认跌倒：`fall_detected=True` 持续时间达到 `confirm_seconds`

默认参数：

```python
suspect_seconds = 2
confirm_seconds = 5
alarm_cooldown = 30
```

## 防重复报警

进入“确认跌倒”后会触发报警。为了避免控制台每秒重复报警，状态机会记录上一次报警时间，在 `alarm_cooldown` 秒内不重复报警。

如果跌倒信号消失，状态机会清空本次跌倒计时，重新回到“无人”或“正常有人”。
