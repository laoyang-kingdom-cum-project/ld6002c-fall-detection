# 01 项目背景和系统架构

本项目用于讲解毫米波雷达、串口协议、Python 状态机、日志、展示大屏和电脑本地语音如何组成一套可测试的跌倒报警系统。核心判断和报警输出都保留在 Python。

```text
mock / serial / replay
         |
         v
     RadarFrame
         |
         v
    FallDetector
         |
         +--> frame CSV / event CSV / Streamlit 展示大屏
         |
         +--> ffplay --> 电脑本地语音
```

模块边界：

- Reader 只负责取得 bytes 或模拟数据。
- `LD6002CParser` 只负责官方 TinyFrame 到 `RadarFrame` 的转换，包括状态帧和 3D 点云帧。
- `FallDetector` 只负责持续时间与报警冷却。
- `SystemController` 负责业务状态和有意义的状态变化事件。
- `DesktopAudioAlarm` 负责在确认跌倒时非阻塞播放电脑语音。

这种分层让无硬件测试、原始数据回放和真机联调使用同一套判断逻辑。

`mock` 模式只用于演示和测试，不代表真实雷达观测。默认 `empty` 场景用于验证系统启动后不自动报警；`fall-demo`、`normal` 和 `presence-demo` 分别用于跌倒流程、正常有人和人体存在切换演示。真实硬件到位后，现场状态应以 `serial` 模式解析出的 LD6002C 帧为准。

展示大屏将状态机、三轴点云投影、XYZ 质心轴线图、AI 判断流、原始数据流和 CSV 日志组合在同一页面。mock 点云用于课程讲解并始终标记为 `MOCK`；serial 页面只接受协议中的 `0x0A08` 坐标，不会将教学轨迹冒充真实雷达结果。
