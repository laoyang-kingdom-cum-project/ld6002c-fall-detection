# 02 硬件接入

硬件包括 HLK-LD6002C、官方测试底板、数据 Type-C 线、电脑，以及 M5Stack StickS3。LD6002C 和 StickS3 是两个独立 USB 设备，不要按 `/dev/ttyUSB0` 或 `/dev/ttyACM0` 的编号猜设备身份。

```bash
python tools/list_serial_ports.py
```

项目实测识别信息：

- LD6002C 测试底板：Silicon Labs CP2104，VID:PID `10c4:ea60`。
- StickS3：M5Stack USB CDC，VID:PID `303a:832b`。

Linux 长期运行建议使用工具显示的 `/dev/serial/by-id/` 路径。若 CP2104 设备属于 `uucp` 组，可把当前用户加入该组，重新登录后生效。

## 安装与安全

- 雷达安装高度、俯角和覆盖范围必须以 LD6002C 硬件资料及现场验证为准。
- 先采集无人、站立、行走、坐下和主动躺下，再进行跌倒场景。
- 跌倒测试使用厚软垫、保护人员和低风险动作；老人不得参与危险模拟。
- 测试底板 USB 线不够长时，优先使用符合数据传输规范的有源 USB 延长线或把采集电脑靠近设备，不要自行加长模块高速/供电线。
- StickS3 与 Python 主机需处于可互访的 2.4 GHz Wi-Fi 局域网。

刷入本项目固件会覆盖 StickS3 当前 UiFlow2 固件。编译本身不会写设备，只有执行 PlatformIO `upload` target 才会烧录。
