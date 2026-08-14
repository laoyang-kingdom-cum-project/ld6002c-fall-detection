# 04 Python 状态机和报警取消

项目不采用简单的 `if fall: alarm()`。`FallDetector` 根据连续跌倒信号的持续时间输出：

- 无人：无人且无跌倒信号。
- 正常有人：有人且无跌倒信号。
- 观察中：跌倒信号小于 `suspect_seconds`。
- 疑似跌倒：持续时间达到 `suspect_seconds`。
- 确认跌倒：持续时间达到 `confirm_seconds`。

默认值为 2 秒、5 秒和 30 秒报警冷却。跌倒信号恢复为 false 时，本次持续时间清零。

## 设备状态

`SystemController` 将中文教学状态映射为设备协议状态：`NORMAL`、`OBSERVING`、`SUSPECTED_FALL` 和 `CONFIRMED_FALL`。StickS3 断线时本地显示 `DISCONNECTED`。

确认跌倒后，StickS3 Button A 发送 `ALARM_CANCELLED`。Python 将当前连续跌倒标记为 `CANCELLED`、记录事件并广播。即使旧的跌倒信号仍为 true，也不会立即再次报警；只有信号先恢复为 false，后续跌倒才被视为新事件。

帧日志记录每次传感器观察，事件日志只记录有业务意义的状态变化和设备连接。这两个概念应在课程中分开分析。
