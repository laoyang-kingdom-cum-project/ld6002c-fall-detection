# ld6002c-fall-detection

基于 **HiLink HLK-LD6002C 60GHz 毫米波跌倒检测雷达** 的老人跌倒检测课程项目。Python 负责协议解析、二次判断、日志、展示大屏和电脑本地语音报警。

> 本项目仅用于教学和演示，不是医疗诊断设备，也不能作为唯一的生命安全保障手段。模拟跌倒必须使用软垫并由同伴保护。

## 系统架构

```text
LD6002C --USB/serial--> Python parser -> Ollama/Qwen3 -> FallDetector
                                             |
                                             +-- frame CSV / event CSV
                                             +-- Streamlit dashboard
                                             +-- ffplay -> 电脑本地语音

mock data ----+
raw .bin -----+--> 同一套 Python 状态机
```

## 本地 Ollama AI 判断层

本课程使用本地 Ollama 与 Qwen3 0.6B 演示边缘 AI 模型调用流程。毫米波雷达提供基础跌倒状态数据，Python 将 `is_fall=0/1` 发送至本地语言模型，模型返回经过严格校验的结构化判断，再由状态机控制日志、Dashboard 和电脑语音报警。

AI 模块用于演示本地模型部署、API 调用和 AIoT 系统集成，不声明它能够提升雷达自身的跌倒检测精度。模型必须保持 LD6002C 的原始语义；若 Ollama 超时、未启动、模型缺失或返回非法结果，系统明确记录 `AI_FALLBACK`，并使用雷达原始结果继续运行。

确认本地服务和模型：

```fish
ollama --version
ollama list
ollama run qwen3:0.6b
```

AI 默认启用。系统在首次雷达状态、`0→1`、`1→0` 时立即请求 Ollama，输入不变时默认每 3 秒重新请求一次；两个请求之间的雷达帧复用最近一次校验结果，避免每秒重复推理。启动 mock 跌倒演示：

```fish
ld6002c-fall --mode mock \
  --mock-scenario fall-demo \
  --enable-ai \
  --suspect-seconds 1 \
  --confirm-seconds 2
```

临时禁用 AI：

```fish
ld6002c-fall --mode mock --disable-ai
```

配置可通过 `--ollama-base-url`、`--ollama-model`、`--ollama-timeout`、`--ai-periodic-interval` 覆盖，也可在进程环境中设置 `OLLAMA_BASE_URL`、`OLLAMA_MODEL`、`OLLAMA_TIMEOUT`、`AI_PERIODIC_INTERVAL`、`AI_ENABLED`。仓库中的 `.env.example` 是配置示例，项目不会自动读取 `.env`。

可选创建课程模型别名：

```fish
ollama create fall-detection-ai -f ollama/Modelfile
ld6002c-fall --mode mock --enable-ai --ollama-model fall-detection-ai
```

这只是固定 Prompt 和低随机性参数，不涉及训练或微调。

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

## 实时监测展示大屏

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

浏览器打开 <http://localhost:8501>。项目自带页面是课程展示和正式联调入口，无需启动 Open WebUI。页面采用暖白、炭黑和陶土橙的展示大屏风格；实时区默认每 2 秒刷新，日志表格每 5 秒刷新，并显示：

页面使用 Streamlit 右上角菜单自带的 `System / Light / Dark` 主题切换。切换时页面面板、状态色、日志终端、点云投影和 XYZ 轴线图会读取原生主题并同步更新。

- Radar 链路、点云链路、人体存在、当前业务状态、AI 引擎和数据来源。
- X/Z 正视、X/Y 俯视、Y/Z 侧视三张同步点云投影，以及最近 40 帧质心的 X/Y/Z 实时轴线图。
- 真实 `AI_REQUEST`、`AI_RESPONSE`、`AI_ERROR`、`AI_FALLBACK` 判断流。
- `ANALYZING`、`MONITORING`、`COMPLETED`、`FALL_DETECTED` 等 AI 工作状态。
- 最近最多 100 条雷达、AI、报警和取消事件，保留可靠的原始数据。
- 雷达输入、AI 输出、最终结果、推理耗时和触发方式。

刷新频率可通过 `DASHBOARD_REFRESH_SECONDS` 和 `DASHBOARD_LOG_REFRESH_SECONDS` 调整，`DASHBOARD_MAX_ROWS` 控制大屏保留的最近 CSV 快照行数（默认 600）。页面使用独立 fragment 更新实时区和日志区，两个 fragment 共享按文件版本缓存的有界快照，不会随日志无限增长而反复全量扫描；刷新时保持当前滚动位置，手动重新加载浏览器页面时回到顶部。

`mock` 模式会产生明确标注的教学点云轨迹，方便没有真机数据时演示大屏。`serial` 模式只展示官方 `0x0A08` 点云帧；雷达未发送点云时显示 `WAITING`，不会用 mock 坐标填充真实设备页面。

主程序默认不再启动 StickS3 WebSocket，因此不会占用 8765 端口。页面会醒目标注 `MOCK`、`HLK-LD6002C` 或 `REPLAY`，演示真实硬件时必须确认数据源是 `HLK-LD6002C`。

推荐课堂演示顺序：

1. 启动 Ollama，并用 `ollama list` 确认 `qwen3:0.6b` 已安装。
2. 终端 1 运行 `fall-demo`，观察启动后的正常阶段。
3. 终端 2 启动 Streamlit，打开实时监测展示大屏。
4. 等待 mock 在第 10 秒进入跌倒信号，观察 `ANALYZING → SUSPECTED_FALL → CONFIRMED_FALL`。
5. 展示人体点云由直立分布切换为低位横向分布，以及 `FALL_DETECTED`、`ALARM_TRIGGERED` 和原始数据。

## 识别串口设备

不要依赖可能随插拔变化的 `/dev/ttyUSB0` 或 `/dev/ttyACM0`：

```fish
python tools/list_serial_ports.py
```

工具会显示 device、description、manufacturer、VID、PID、serial number 和 Linux `/dev/serial/by-id/` 稳定路径。当前联调硬件表现为：

- LD6002C 测试底板：Silicon Labs CP2104，通常为 `/dev/ttyUSB*`。

serial 模式建议使用工具输出的 LD6002C 稳定路径：

```fish
ld6002c-fall --mode serial \
  --port /dev/serial/by-id/<LD6002C-stable-path> \
  --baudrate 115200 \
  --enable-ai
```

`serial` 模式默认发送官方 `0x010E` 命令打开 User log，雷达随后主动上报 `0x0A08` 真实 3D 点云。启动日志出现 `[Radar] 已发送 0x010E` 后，Dashboard 的 Point Cloud 会从 `WAITING` 变为 `TRACKING`；不需要点云时可传入 `--disable-point-cloud`。

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

## 电脑语音报警

确认跌倒后，`DesktopAudioAlarm` 会在控制台输出报警，并通过本机 `ffplay` 非阻塞播放项目根目录的 `studio_video_1778294323944.mp3`。该文件实际为 M4A/MP4 容器，`ffplay` 会根据内容自动识别。

需要本机安装 FFmpeg：

```fish
ffplay -version
```

指定音频和音量：

```fish
ld6002c-fall --mode mock \
  --mock-scenario fall-demo \
  --suspect-seconds 1 \
  --confirm-seconds 2 \
  --alarm-sound studio_video_1778294323944.mp3 \
  --alarm-volume 100
```

`--alarm-volume` 范围为 0 到 100，默认为 100：程序不再额外衰减，实际响度跟随电脑系统音量和当前输出设备。暂时只需控制台报警时使用 `--disable-audio-alarm`。也可使用 `ALARM_SOUND_PATH`、`ALARM_VOLUME` 和 `AUDIO_ALARM_ENABLED` 环境变量。若文件不存在或未找到 `ffplay`，系统会明确提示并继续运行，不会中断雷达采集。

`firmware/sticks3_alarm` 仅作为旧版课程参考保留，当前交付和演示不使用 StickS3。如需兼容旧终端，可显式传入 `--enable-websocket`。

## 完整联调流程

1. 插入 LD6002C 测试底板，用 `python tools/list_serial_ports.py` 确认稳定路径。
2. 用 `ffplay -version` 确认电脑播放器可用，并检查系统输出音量。
3. 启动 Python `serial` 模式和 Streamlit 大屏。
4. 正常走动时确认点云、轴线图、CSV 和 AI 状态同步更新。
5. 进入确认跌倒后，核对控制台、`ALARM_TRIGGERED` 事件、Dashboard 和电脑语音。
6. 信号恢复为 false 后再测试下一次跌倒，验证 30 秒冷却时间。

雷达不在现场时，可以用 `--mode mock --mock-scenario fall-demo` 完整验证电脑语音联动。真实 LD6002C 插上后，日常监测应使用 `--mode serial`，不要用 `mock` 判断现场是否有人。

## 协议与日志

`LD6002CParser` 依据海凌科官方《LD6002C 跌倒检测串口协议文档》实现 TinyFrame 帧头、长度、消息类型和校验，不使用其他 LD6002 型号协议，也不从样本猜字段。当前课程使用：

- `0x0E02`：跌倒状态。
- `0x0F09`：人体存在状态。
- `0x0A08`：3D 点云，数据区包含目标数，以及每个点的聚类 ID、X/Y/Z 坐标和速度。

帧日志默认写入 `data/fall_log.csv`；状态变化、AI 调用和设备交互事件写入 `data/events.csv`。事件包括 `AI_REQUEST`、`AI_RESPONSE`、`AI_ERROR`、`AI_FALLBACK`、`FALL_SUSPECTED`、`FALL_DETECTED`、`ALARM_TRIGGERED`、`ALARM_CANCELLED`、`DEVICE_CONNECTED`、`DEVICE_DISCONNECTED`。事件会同时保存触发时的原始雷达数据。Streamlit 页面每秒自动读取这两个日志文件，无需手动刷新浏览器。

帧日志同时记录 `radar_is_fall`、`ai_result`、`ai_label`、`ai_status`、`ai_success`、`ai_cached`、`ai_model`、`ai_inference_ms`、`ai_message`、`final_result`、`device_state`、`ai_work_state`、`ai_trigger`、`point_count` 和 `radar_points`，用于展示“雷达输入 → 本地 AI → Python 状态机 → 最终业务结果”的完整链路。`radar_points` 使用 JSON 保存每个点的聚类 ID、坐标和速度；`ai_cached=true` 表示当前帧复用了最近一次校验结果。旧日志会自动迁移并补充空点云，不会被误标为真实坐标。

`fall_log.csv` 中的 `source` 字段用于区分数据来源：`mock` 是程序生成的教学数据，`serial` 是从 LD6002C 串口实时读取的数据，`replay` 是历史 `.bin` 回放。排查现场状态时优先确认 Dashboard 的“数据来源”是否为 `serial`。

## 项目结构

```text
src/ld6002c_fall/      Python 数据源、parser、状态机、日志和电脑报警
src/ld6002c_fall/ai/   Ollama 客户端、3 秒调度器、结构化模型与固定 Prompt
src/ld6002c_fall/live_monitor.py  AI Live Monitor 的纯数据模型
tools/                 串口发现与原始数据采集
dashboard/app.py       Streamlit 实时监测展示大屏
firmware/sticks3_alarm 旧版 StickS3 PlatformIO 参考固件
ollama/Modelfile       可选的课程模型别名配置
data/raw/              本地真实采样目录
docs/                  课程说明文档
tests/                 pytest 自动化测试
```

## 验证

```fish
pytest
ld6002c-fall --help
python tools/list_serial_ports.py
ffplay -version
```

扩展点云、距离或更多状态字段前，应继续提供官方字段定义和带场景 metadata 的真实 `.bin`，不要仅凭十六进制样本反推并写死业务含义。

## Open WebUI（可选）

Open WebUI 只用于手工发送 Prompt、检查模型是否能响应等临时调试，不是本项目的实时监测界面，也不参与雷达状态机或电脑语音报警。它是独立软件，不属于本项目 Python 依赖，也不会由 `ld6002c-fall` 启动。项目与 Open WebUI 只共享同一个本机 Ollama 服务：

```text
                    +-- LD6002C Python 项目
Ollama :11434 ------+
                    +-- Open WebUI
```

正式演示请使用项目自带的 Streamlit AI Live Monitor；只有需要手动调试 `qwen3:0.6b` 时才单独打开 Open WebUI。本项目始终通过 `http://127.0.0.1:11434` 完成真实业务调用。
