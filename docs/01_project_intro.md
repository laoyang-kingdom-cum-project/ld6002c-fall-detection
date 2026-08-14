# 01 项目背景和系统架构

本项目用于讲解毫米波雷达、串口协议、Python 状态机、日志、WebSocket 和嵌入式终端如何组成一套可测试的跌倒报警系统。核心判断保留在 Python，StickS3 不直接解释雷达数据。

```text
mock / serial / replay
         |
         v
     RadarFrame
         |
         v
    FallDetector
         |
         +--> frame CSV / event CSV / Streamlit
         |
         +--> WebSocket --> StickS3 显示、声音、按键
```

模块边界：

- Reader 只负责取得 bytes 或模拟数据。
- `LD6002CParser` 只负责官方 TinyFrame 到 `RadarFrame` 的转换。
- `FallDetector` 只负责持续时间与报警冷却。
- `SystemController` 负责设备状态、业务事件和人工取消。
- StickS3 只接收 JSON 状态并返回人工事件。

这种分层让无硬件测试、原始数据回放和真机联调使用同一套判断逻辑。

`mock` 模式只用于演示和测试，不代表真实雷达观测。默认 `empty` 场景用于验证系统启动后不自动报警；`fall-demo`、`normal` 和 `presence-demo` 分别用于跌倒流程、正常有人和人体存在切换演示。真实硬件到位后，现场状态应以 `serial` 模式解析出的 LD6002C 帧为准。
