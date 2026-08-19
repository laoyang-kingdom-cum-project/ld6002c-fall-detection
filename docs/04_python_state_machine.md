# 04 Python 状态机和报警取消

项目不采用简单的 `if fall: alarm()`。`FallDetector` 根据连续跌倒信号的持续时间输出：

- 无人：无人且无跌倒信号。
- 正常有人：有人且无跌倒信号。
- 观察中：跌倒信号小于 `suspect_seconds`。
- 疑似跌倒：持续时间达到 `suspect_seconds`。
- 确认跌倒：持续时间达到 `confirm_seconds`。

默认值为 2 秒、5 秒和 30 秒报警冷却。跌倒信号恢复为 false 时，本次持续时间清零。

## 电脑语音报警

`SystemController` 将中文教学状态映射为 `NORMAL`、`OBSERVING`、`SUSPECTED_FALL` 和 `CONFIRMED_FALL`。只有 `DetectionResult.should_alarm` 为 true 时，`DesktopAudioAlarm` 才会非阻塞启动本机 `ffplay`，而不是每一帧 `fall_detected=true` 都重复播放。

确认跌倒后会记录 `ALARM_TRIGGERED`，默认 30 秒内不重复报警。音频播放是输出层，不会阻塞串口读取、AI 判断或 CSV 记录；即使音频文件缺失，状态机仍然继续运行并保留控制台告警。

帧日志记录每次传感器观察，事件日志只记录有业务意义的状态变化和设备连接。这两个概念应在课程中分开分析。
