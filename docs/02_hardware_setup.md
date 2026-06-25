# 02 硬件接入思路

计划硬件包括：

- HLK-LD6002C 60GHz 毫米波跌倒检测雷达
- 测试底板或转接板
- Type-C 数据线
- 运行 Python 程序的电脑

## 接入流程

1. 将 LD6002C 安装到测试底板。
2. 使用 Type-C 连接测试底板和电脑。
3. 在系统中确认串口设备名称：
   - Linux 常见为 `/dev/ttyUSB0` 或 `/dev/ttyACM0`
   - Windows 常见为 `COM3`、`COM4`
4. 根据模块文档确认波特率，项目默认使用 `115200`。
5. 使用 serial 模式启动程序。

```bash
ld6002c-fall --mode serial --port /dev/ttyUSB0 --baudrate 115200
```

当前版本的 serial 模式已经有读取框架，但真实协议解析需要等待设备和协议文档。
