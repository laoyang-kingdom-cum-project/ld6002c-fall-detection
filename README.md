# ld6002c-fall-detection

基于 **HiLink HLK-LD6002C 60GHz 毫米波跌倒检测雷达** 的老人跌倒检测课程项目。Python 负责协议解析、二次判断、日志和 WebSocket 服务；M5Stack StickS3 只负责状态显示、声音报警与人工取消。

> 本项目仅用于教学和演示，不是医疗诊断设备，也不能作为唯一的生命安全保障手段。模拟跌倒必须使用软垫并由同伴保护。

## 系统架构

```text
LD6002C --USB/serial--> Python --WebSocket/Wi-Fi--> StickS3
                           |
                           +-- parser -> FallDetector
                           +-- frame CSV / event CSV
                           +-- Streamlit dashboard

mock data ----+
raw .bin -----+--> 同一套 Python 状态机
```

项目支持三种输入模式：

- `mock`：没有雷达也可运行。默认 `empty` 场景为空房间，不会自动报警；需要课堂跌倒演示时显式使用 `--mock-scenario fall-demo`。
- `serial`：读取真实 LD6002C TinyFrame 数据。
- `replay`：回放之前原样保存的 `.bin`，无需重复真人跌倒测试。

## 安装

需要 Python 3.11 或更高版本。fish shell：

```fish
python -m venv .venv
source .venv/bin/activate.fish
pip install -e '.[dev]'
```

bash/zsh：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Mock 与 GUI

终端 1 先产生数据：

```fish
source .venv/bin/activate.fish
ld6002c-fall --mode mock
```

默认 mock 场景是空房间，用于确认系统启动后不会自己报警。常用场景：

```fish
# 空房间：无人、无跌倒、无报警
ld6002c-fall --mode mock --mock-scenario empty

# 正常有人：一直有人、无跌倒
ld6002c-fall --mode mock --mock-scenario normal

# 无人/有人切换：验证 Dashboard 的人体存在状态
ld6002c-fall --mode mock --mock-scenario presence-demo

# 跌倒演示：启动 10 秒后进入跌倒流程
ld6002c-fall --mode mock --mock-scenario fall-demo --suspect-seconds 1 --confirm-seconds 2
```

终端 2 启动页面：

```fish
source .venv/bin/activate.fish
streamlit run dashboard/app.py
```

浏览器打开 <http://localhost:8501>。主程序默认同时监听 `ws://0.0.0.0:8765`；暂时不接 StickS3 时可增加 `--disable-websocket`。

## 识别串口设备

不要依赖可能随插拔变化的 `/dev/ttyUSB0` 或 `/dev/ttyACM0`：

```fish
python tools/list_serial_ports.py
```

工具会显示 device、description、manufacturer、VID、PID、serial number 和 Linux `/dev/serial/by-id/` 稳定路径。当前联调硬件表现为：

- LD6002C 测试底板：Silicon Labs CP2104，通常为 `/dev/ttyUSB*`。
- StickS3：M5Stack USB CDC，通常为 `/dev/ttyACM*`。

serial 模式建议使用工具输出的 LD6002C 稳定路径：

```fish
ld6002c-fall --mode serial \
  --port /dev/serial/by-id/<LD6002C-stable-path> \
  --baudrate 115200
```

Linux 无权限时，先查看设备所属组；本机实测 CP2104 属于 `uucp`：

```fish
ls -l /dev/ttyUSB0
sudo usermod -aG uucp $USER
```

重新登录后组权限生效。

## 采集真实原始数据

采集工具不解释数据，只把串口 bytes 原封不动写入 `.bin`，并生成同名 `.json` metadata：

```fish
python tools/capture_ld6002c.py \
  --port /dev/serial/by-id/<LD6002C-stable-path> \
  --baudrate 115200 \
  --scenario standing \
  --output data/raw/standing.bin
```

跌倒场景只在软垫和保护人员到位后采集：

```fish
python tools/capture_ld6002c.py \
  --port /dev/serial/by-id/<LD6002C-stable-path> \
  --scenario fall \
  --duration 20 \
  --output data/raw/fall.bin
```

建议依次采集 `empty`、`standing`、`walking`、`sitting`、`lying`、`fall`、`recovery`。仓库不会提交伪造 `.bin` 或含隐私的现场样本。

## 离线回放

```fish
ld6002c-fall --mode replay \
  --input data/raw/fall.bin \
  --replay-chunk-size 64
```

`--replay-chunk-size` 可测试串口任意分块；`--replay-interval` 控制解析结果之间的等待时间。原始 `.bin` 不含时间戳，因此 replay 使用运行时刻作为 `RadarFrame.timestamp`。

## StickS3 固件

固件位于 `firmware/sticks3_alarm`，使用 PlatformIO、Arduino、M5Unified、WebSockets 和 ArduinoJson。

```fish
pip install -e '.[firmware]'
```

```fish
cd firmware/sticks3_alarm
cp include/secrets.example.h include/secrets.h
```

编辑被 Git 忽略的 `include/secrets.h`：

```cpp
constexpr char WIFI_SSID[] = "your-2.4g-wifi";
constexpr char WIFI_PASSWORD[] = "your-password";
constexpr char SERVER_HOST[] = "192.168.1.100";
constexpr unsigned int SERVER_PORT = 8765;
```

`SERVER_HOST` 必须是运行 Python 的电脑局域网 IP，不能填 `0.0.0.0` 或 `localhost`。Linux 可用 `ip -4 -o addr show scope global` 查看，并选择 Wi-Fi 网卡地址。

构建：

```fish
pio run --project-dir firmware/sticks3_alarm
```

烧录会覆盖 StickS3 当前的 UiFlow2 固件，确认 secrets 后再执行：

```fish
pio run --project-dir firmware/sticks3_alarm \
  --target upload \
  --upload-port /dev/serial/by-id/<StickS3-stable-path>
```

StickS3 显示 `DISCONNECTED`、`NORMAL`、`OBSERVING`、`SUSPECTED_FALL`、`CONFIRMED_FALL`、`CANCELLED`。确认跌倒时循环蜂鸣；按 Button A 会立即静音并向 Python 发送 `ALARM_CANCELLED`。

提示音和音量可在 `firmware/sticks3_alarm/include/secrets.h` 中通过 `SPEAKER_VOLUME`、`ALARM_LOW_TONE_HZ`、`ALARM_HIGH_TONE_HZ`、`ALARM_TONE_MS` 和 `ALARM_TONE_INTERVAL_MS` 调整。`SPEAKER_VOLUME` 范围为 0 到 255。

## 完整联调流程

1. 插入 LD6002C 测试底板和 StickS3。
2. 用 `python tools/list_serial_ports.py` 确认两条稳定路径。
3. 启动 Python `serial` 模式，监听默认 WebSocket 端口 8765。
4. StickS3 连接同一个 2.4 GHz Wi-Fi，并连接 Python 主机局域网 IP。
5. Python 将 `FallDetector` 状态广播给 StickS3。
6. StickS3 显示状态并在确认跌倒时报警。
7. Button A 取消本次报警；只有真实跌倒信号先恢复为 false，下一次跌倒才会重新进入报警流程。

雷达不在现场时，可以用 `--mode mock --mock-scenario fall-demo` 完整验证 StickS3 联动。真实 LD6002C 插上后，日常监测应使用 `--mode serial`，不要用 `mock` 判断现场是否有人。

## 协议与日志

`LD6002CParser` 依据海凌科官方《LD6002C 跌倒检测串口协议文档》实现 TinyFrame 帧头、长度、消息类型和校验，不使用其他 LD6002 型号协议，也不从样本猜字段。当前课程使用：

- `0x0E02`：跌倒状态。
- `0x0F09`：人体存在状态。

帧日志默认写入 `data/fall_log.csv`；状态变化和设备交互事件写入 `data/events.csv`。事件包括 `FALL_SUSPECTED`、`FALL_CONFIRMED`、`ALARM_STARTED`、`ALARM_CANCELLED`、`DEVICE_CONNECTED`、`DEVICE_DISCONNECTED`。

`fall_log.csv` 中的 `source` 字段用于区分数据来源：`mock` 是程序生成的教学数据，`serial` 是从 LD6002C 串口实时读取的数据，`replay` 是历史 `.bin` 回放。排查现场状态时优先确认 Dashboard 的“数据来源”是否为 `serial`。

## 项目结构

```text
src/ld6002c_fall/      Python 数据源、parser、状态机、日志和 WebSocket
tools/                 串口发现与原始数据采集
dashboard/app.py       Streamlit 页面
firmware/sticks3_alarm StickS3 PlatformIO 固件
data/raw/              本地真实采样目录
docs/                  课程说明文档
tests/                 pytest 自动化测试
```

## 验证

```fish
pytest
ld6002c-fall --help
python tools/list_serial_ports.py
pio run --project-dir firmware/sticks3_alarm
```

扩展点云、距离或更多状态字段前，应继续提供官方字段定义和带场景 metadata 的真实 `.bin`，不要仅凭十六进制样本反推并写死业务含义。
