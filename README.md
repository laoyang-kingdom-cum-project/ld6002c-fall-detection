# ld6002c-fall-detection

基于 **HiLink HLK-LD6002C 60GHz 毫米波跌倒检测雷达** 的老人跌倒检测课程项目。

第一版先支持 `mock` 模式，让项目在没有真实雷达的情况下也能运行、测试和展示。真实设备到货后，再通过串口读取 LD6002C 数据，并根据官方串口协议补充解析逻辑。

> 注意：本项目是教学/演示用途，不作为医疗诊断设备或安全生命保障设备。

## 为什么先使用 mock 模式

课程项目通常会遇到硬件到货晚、协议文档不完整、串口数据暂时无法采集等问题。`mock` 模式可以先把这些部分做起来：

- Python 状态机：无人、正常有人、观察中、疑似跌倒、确认跌倒
- CSV 日志记录
- 控制台报警
- Streamlit 可视化页面
- pytest 自动化测试

这样真实 LD6002C 到货后，只需要重点补齐串口协议解析，而不用从零搭建软件结构。

## 安装方法

建议使用 Python 3.11 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Windows PowerShell 可使用：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## mock 模式运行

```bash
ld6002c-fall --mode mock
```

模拟流程：

- 前 10 秒：正常有人，未跌倒
- 第 10 到 16 秒：模拟跌倒，`fall_detected=True`
- 之后：恢复正常

日志默认保存到：

```text
data/fall_log.csv
```

## serial 模式运行

真实设备到货后，可使用：

```bash
ld6002c-fall --mode serial --port /dev/ttyUSB0 --baudrate 115200
```

Windows 串口示例：

```bash
ld6002c-fall --mode serial --port COM3 --baudrate 115200
```

当前版本只保留串口读取框架和解析器扩展点，不会猜测 LD6002C 的真实协议格式。

## Streamlit 页面运行

先运行主程序生成 CSV 日志：

```bash
ld6002c-fall --mode mock
```

再打开可视化页面：

```bash
streamlit run dashboard/app.py
```

页面会读取 `data/fall_log.csv`，显示当前系统状态和最近 50 条日志。

## 项目结构

```text
ld6002c-fall-detection/
├── src/ld6002c_fall/
│   ├── main.py              # 命令行入口
│   ├── radar_model.py       # 雷达帧数据结构
│   ├── mock_reader.py       # 模拟数据源
│   ├── serial_reader.py     # 串口读取框架
│   ├── ld6002c_parser.py    # LD6002C 协议解析扩展点
│   ├── fall_detector.py     # 二次判断状态机
│   ├── logger.py            # CSV 日志
│   ├── alarm.py             # 控制台报警
│   └── config.py            # 默认配置
├── dashboard/app.py         # Streamlit 页面
├── docs/                    # 课程说明文档
├── data/                    # 日志目录
└── tests/                   # pytest 测试
```

## 后续接入 HLK-LD6002C 的步骤

1. 使用测试底板和 Type-C 连接 LD6002C。
2. 确认系统识别到串口设备，例如 `/dev/ttyUSB0`、`/dev/ttyACM0` 或 `COM3`。
3. 获取《LD6002C 跌倒检测串口协议文档》。
4. 采集真实原始帧，保存样例数据。
5. 在 `ld6002c_parser.py` 中补充帧头、长度、命令字、数据区、校验逻辑。
6. 将解析结果转换为 `RadarFrame`。
7. 复用现有 `FallDetector`、CSV 日志、报警和 Streamlit 页面。

## 测试

```bash
pytest
```

测试覆盖：

- 连续跌倒信号达到确认时间后进入“确认跌倒”
- 短暂跌倒信号不会直接确认
- mock reader 能输出 `RadarFrame`
- mock 流程中会出现 `fall_detected=True`
