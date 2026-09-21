# ld6002c-fall-detection

基于 **HiLink HLK-LD6002C 60GHz 毫米波跌倒检测雷达** 的老人跌倒检测课程项目。Python 负责协议解析、二次判断、日志、展示大屏和电脑本地语音报警。

> 本项目仅用于教学和演示，不是医疗诊断设备，也不能作为唯一的生命安全保障手段。模拟跌倒必须使用软垫并由同伴保护。

## 环境要求

### 基础环境

| 项目 | 要求与说明 |
| --- | --- |
| 操作系统 | 当前开发及硬件联调环境为 Linux。Windows/macOS 需要按系统调整虚拟环境激活命令、串口名称和音频环境，尚未完成完整联调验证。 |
| Python | **3.11 或更高版本**，需要可用的 `pip` 和 `venv`。执行 `python --version` 确认；如果系统仅提供 `python3`，创建虚拟环境时使用 `python3`。 |
| Streamlit | 本机大屏使用 **1.59.2**，下方安装命令显式安装此版本。当前页面使用 `st.fragment`、`st.context.theme` 等接口，不能仅按依赖文件中较宽松的 `streamlit>=1.30` 下限准备环境。 |
| 浏览器 | 需要支持 WebSocket 和 CSS `light-dark()`；后者用于大屏深浅色适配。 |
| 工作目录 | 从项目根目录运行命令，并确保 `data/` 可写。主程序和大屏应使用同一份项目目录及日志文件。 |
| 网络 | 常规开发环境首次安装依赖和下载模型需要网络；准备完整 Windows 离线包后，录课电脑的安装和运行全程不需要联网。 |

项目的 Python 依赖由 `pyproject.toml` 管理，安装项目时自动安装：

| 依赖 | 用途 |
| --- | --- |
| `pyserial` | 串口通信及设备发现 |
| `pandas`、`altair` | 日志数据处理、点云投影和 XYZ 轴线图 |
| `streamlit` | 实时监测大屏 |
| `websockets` | 旧版 StickS3 通信兼容层，默认不启用服务 |
| `pytest`（`dev` 可选依赖） | 自动化测试 |

当前本机虚拟环境版本记录：Python `3.14.7`、Streamlit `1.59.2`、pandas `3.0.3`、Altair `6.2.2`、pyserial `3.5`、websockets `16.1`、pytest `9.1.1`。这是环境参考，不是所有依赖的最低版本要求或锁定文件。

### 按功能准备

| 功能 | 额外要求 |
| --- | --- |
| 无设备模拟 | `mock` 模式不需要雷达、串口驱动或 StickS3。仅验证状态机和页面时，可关闭 AI 和音频报警。 |
| 真实雷达 | HLK-LD6002C、配套测试底板、支持数据传输的 USB/Type-C 线；系统需识别 USB-UART 串口，本机底板使用 CP2104。当前用户必须具有串口读写权限，且串口不能同时被其他采集程序占用。 |
| 本地 AI | 单独安装并启动 Ollama，准备 `qwen3:0.6b` 模型；默认服务地址为 `http://127.0.0.1:11434`。Python 安装命令不会安装 Ollama 或下载模型；不使用 AI 时传入 `--disable-ai`。 |
| 电脑语音 | 单独安装带 `ffplay` 的 FFmpeg，并确保 `ffplay` 在 `PATH` 中；需要可用的扬声器或耳机，以及项目中的报警音频文件。不播放声音时传入 `--disable-audio-alarm`。 |
| 原始数据回放 | `replay` 模式需要已采集的 `.bin` 文件，不需要连接雷达。 |

AI 模型需要额外的内存、磁盘空间和推理时间，项目尚未做最低内存或显卡配置基准测试。演示前应在目标电脑上确认模型能够加载、响应时间符合配置的 `--ollama-timeout`，避免只根据 Python 环境安装成功判断 AI 已就绪。

默认端口：Streamlit 大屏为 `8501`，Ollama 为 `11434`；只有显式启用 `--enable-websocket` 时才使用 `8765`。大屏端口已占用时，可用 `python -m streamlit run dashboard/app.py --server.port 8502` 指定其他端口，并打开终端实际输出的 URL。

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

在项目根目录执行以下命令，按自己的 shell 选择一组。Ollama 和 FFmpeg 属于系统工具，需要按上面的功能要求单独准备。

fish shell：

```fish
python -m venv .venv
source .venv/bin/activate.fish
python -m pip install -e '.[dev]' 'streamlit==1.59.2'
```

bash/zsh：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]' 'streamlit==1.59.2'
```

Windows PowerShell：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]' 'streamlit==1.59.2'
```

每个新终端都需要激活虚拟环境。只运行项目、不执行测试时，可将 `'.[dev]'` 改为 `.`；当前演示不需要安装旧固件的 `firmware` 可选依赖，也不依赖 Home Assistant 或 Open WebUI。

安装后检查：

```bash
python --version
python -m pip check
python -m streamlit version
ld6002c-fall --help
```

## Windows 离线安装与一键启动

Windows 10/11 x64 录课电脑只需事先安装 **Python 3.14 x64** 和 **Ollama Windows**。复制完整离线交付目录后，不需要网络、Open WebUI、在线 pip 下载或 `ollama pull`。

完整离线交付目录必须携带以下构建产物。Python wheel 可以作为离线发布资源维护；数百 MB 的 Ollama 模型不进入普通 Git 历史，需要另外放入 U 盘交付目录：

```text
wheelhouse/       Windows CPython 3.14 第三方依赖 wheel
project-wheel/    ld6002c_fall_detection-*.whl
models/           另行加入的 qwen3:0.6b Ollama manifests 和 blobs
```

第一次部署：

```text
1. 安装 Python 3.14 x64
2. 安装 Ollama Windows
3. 复制完整离线项目目录
4. 双击 INSTALL_WINDOWS_OFFLINE.bat
5. 等待 INSTALLATION COMPLETE
```

以后每次录课先插入 LD6002C，再双击 `START_WINDOWS.bat`。其他入口如下：

```text
INSTALL_WINDOWS_OFFLINE.bat   创建 .venv、离线安装 wheel、导入并验证模型
WINDOWS_CHECK.bat             只检查离线环境，不启动系统
START_WINDOWS.bat             自动检测并启动整套演示
START_COMMUNITY_DEMO.bat      一键启动社区课堂演示，不需要接入雷达
STOP_WINDOWS.bat              只停止本项目启动的进程
```

安装器只接受 Python 3.14 x64，只从 `wheelhouse/` 和 `project-wheel/` 安装，使用 `--no-index` 禁止访问包索引；模型安全合并到 `OLLAMA_MODELS` 或 `%USERPROFILE%\.ollama\models`，不会删除已有模型。若 `.venv` 损坏，可在命令提示符运行 `INSTALL_WINDOWS_OFFLINE.bat -Repair` 重建。

`START_WINDOWS.bat` 会检查项目 `.venv`、必要时启动 Ollama、确认模型、识别 CP210x/CP2104 对应的 `COMx`，随后启动雷达服务和 AI Live Monitor；页面可访问后才打开浏览器。若没有真实雷达，可输入 `M` 切换 Mock Fall Demo。ffplay 缺失只会禁用电脑语音。

所有 Windows 脚本都不会执行在线安装、模型下载或永久修改 ExecutionPolicy / 系统 PATH。固定 COM 口、模型仓库或服务端口时，可复制 `deploy\windows\config.example.cmd` 为 `config.cmd`。完整准备方法、模型验证、停止规则和故障排查见 [Windows 部署说明](deploy/windows/README.md)。

## 启动速查

### 一条命令启动社区课堂演示

已安装项目并准备好 Ollama 后，在项目根目录执行：

```bash
ld6002c-community-demo
```

该命令默认启用 `http://127.0.0.1:11434` 的 `qwen3:0.6b`，在 `0.0.0.0:8501` 启动 Streamlit，打开社区大屏，并在终端打印三个地址：

```text
http://127.0.0.1:8501/
http://127.0.0.1:8501/?view=control
http://127.0.0.1:8501/?view=technical&resident=B2-302
```

第二个地址是演示控制台；同一局域网的手机可使用终端打印的 `http://<电脑局域网 IP>:8501/?view=control`。启动器会同时运行社区后台 runtime，默认以 2 Hz 为全部住户持续生成有界滚动遥测，因此无需先打开控制台或手工发送正常数据。如 Ollama 不可用，业务页面继续使用安全规则给出结果，控制台 health 区域和技术事件会记录 `AI_FALLBACK`。可用 `--no-enable-ai`、`--no-audio-alarm`、`--port 8502` 覆盖默认值。重置所有社区演示状态、演示事件、runtime health 和分住户遥测后退出：

```bash
ld6002c-community-demo --reset
```

Windows 离线部署完成后可直接双击 `START_COMMUNITY_DEMO.bat`，它使用同一个 Python 3.14 `.venv`、离线 wheel、Ollama 模型和 ffplay，不会在现场执行 `pip install` 或 `ollama pull`。

以下流程假设已经完成安装。每个终端先进入同一项目根目录，并按上面的 shell 说明激活 `.venv`。**真实监测与 mock 演示二选一运行**，避免多个主程序同时写入默认日志；Streamlit 大屏在另一个终端独立启动。

### 启动前：AI 与语音

要使用 AI，先检查 Ollama 服务：

```bash
ollama list
```

若提示连接不上 Ollama，在单独终端运行以下命令并保持该终端开启；服务已运行时跳过，不要重复启动：

```bash
ollama serve
```

首次使用且 `ollama list` 中没有目标模型时，在另一个终端下载，然后再次检查：

```bash
ollama pull qwen3:0.6b
ollama list
```

要使用电脑语音，确认以下命令成功，并检查扬声器/耳机和系统音量：

```bash
ffplay -version
```

暂时不需要 AI 或语音时，可分别使用 `--disable-ai`、`--disable-audio-alarm`；下方提供不依赖这两个外部服务的演示命令。

### 正常启动：真实雷达监测

终端 1 插好雷达后列出串口：

```bash
python tools/list_serial_ports.py
```

将下方引号中的串口路径替换为本机实际输出，再启动真实监测：

```bash
ld6002c-fall --mode serial \
  --port "/dev/serial/by-id/替换为实际设备名称" \
  --baudrate 115200 \
  --enable-ai \
  --enable-audio-alarm \
  --alarm-volume 100
```

Windows 将 `--port` 改为实际的 `COM3` 等名称；PowerShell 中请将多行命令合并为一行执行。正常监测保留默认疑似/确认阈值 2 秒/5 秒，报警冷却 30 秒。大屏的数据来源应为 `HLK-LD6002C`；具体串口权限和点云说明见“识别串口设备”。

### 演示启动：模拟跌倒

终端 1 使用 AI 和电脑语音进行课程演示：

```bash
ld6002c-fall --mode mock \
  --mock-scenario fall-demo \
  --enable-ai \
  --enable-audio-alarm \
  --suspect-seconds 1 \
  --confirm-seconds 2 \
  --alarm-volume 100
```

无设备、无 AI 服务、无音频播放器时，改用以下命令：

```bash
ld6002c-fall --mode mock --mock-scenario fall-demo --disable-ai --disable-audio-alarm --suspect-seconds 1 --confirm-seconds 2
```

`fall-demo` 的模拟时间前 10 秒为正常有人，第 10～16 秒产生跌倒信号，之后恢复正常；它不会循环触发跌倒。需要重新演示时，在主程序终端按 `Ctrl+C` 后重新执行命令。该模式的大屏来源应为 `MOCK`；未启用音频时仍会输出控制台报警。

### 启动 Streamlit 大屏

终端 2 执行，适用于上面两种模式：

```bash
python -m streamlit run dashboard/app.py --server.port 8501
```

浏览器打开 <http://localhost:8501>。若 8501 已被占用，改用 `--server.port 8502` 并打开 <http://localhost:8502>。大屏读取主程序产生的日志，不会自行启动雷达采集或 mock 数据。

演示时可先打开大屏，再启动 `fall-demo`，避免错过前 10 秒的正常阶段；没有新数据时页面可能提示等待数据或 `DISCONNECTED`。退出时，分别在主程序和大屏终端按 `Ctrl+C`。

默认首页是“幸福社区 · 老人智能安全监测中心”。页面不再显示顶部视图切换器；演示控制台使用 `?view=control`，技术详情由住户卡片的“查看技术详情”进入，也可使用 `?view=technical&resident=B2-302` 直达。

## 社区老人安全监测大屏

`config/community.json` 配置幸福社区 1、2、3 栋共 18 户。`B2-302` 王阿姨绑定真实 `LD6002C`，主程序将现有 `SystemController` 结果单向同步到该住户；其他 17 户是社区课堂演示点，其技术详情使用标记为 `SIMULATED RADAR DATA · CLASSROOM DEMO` 的教学点云，不宣称为真实硬件数据。

三个 URL 视图共享文件状态，因此电脑展示大屏和手机控制页能看到同一次演示操作：

- **社区监控大屏**：显示监护住户、在线设备、正常住户、当前报警、今日报警，以及 18 户状态矩阵和最近事件。社区数据每 1.5 秒由 `st.fragment` 局部刷新。
- **演示控制台**：只负责切换任意住户的期望场景，并显示 runtime、Ollama、模型、遥测和报警健康状态。AI 推理、业务状态迁移、遥测与报警均由 launcher 所属 runtime 处理，Streamlit rerun 不会重复报警。
- **技术详情**：任意住户都复用同一套雷达链路、业务判断、点云投影、XYZ 趋势、实时数据总线和原始日志渲染器，页面本身只读。`B2-302` 仅在 `fall_log.csv` 最后一帧不超过 5 秒且无演示覆盖时使用真实数据；真实日志过期时自动改读带课堂模拟标记的遥测。

“发送跌倒数据”只写入 `desired_scenario=FALL`。后台 runtime 观察到版本变化后构造 `is_fall=1` 并调用与真实雷达相同的 `OllamaFallAI`；Qwen3 返回合法结果时记录 `DEMO_AI`，不可用或返回非法结构时使用雷达输入安全回退并保留真实 `AI_ERROR` / `AI_FALLBACK` 诊断事件。runtime 每 0.5 秒追加一帧并原子保留最近 60 帧，所以 NORMAL、FALL 和恢复过程会共同留在短期 XYZ 历史中。离线场景只追加一次断开帧，随后停止产生新点云。

电脑语音只在住户首次进入 `FALL` 时触发一次；在状态仍为 `FALL` 时重复点击不会重播。“确认报警”和“恢复正常”都会关闭当前播放；后者还会清除真实住户的演示覆盖。

首次启动会自动生成 `data/community_state.json`，并将所有住户初始化为 `NORMAL`；`data/community_runtime.json` 保存 heartbeat、Ollama、模型、AI 模式、遥测和报警 health。状态和遥测使用锁文件与同目录临时文件原子替换，避免 Streamlit 刷新时读到半份数据。社区事件写入 `data/community_events.csv`；分住户技术帧与 AI/报警事件写入 `data/community_telemetry/<resident>.csv` 和 `<resident>.events.csv`。可通过 `COMMUNITY_TELEMETRY_INTERVAL`、`COMMUNITY_TELEMETRY_MAX_FRAMES` 和 `REAL_TELEMETRY_STALE_SECONDS` 调整默认的 0.5 秒、60 帧和 5 秒阈值。

## 技术详情大屏

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
2. 终端 2 启动 Streamlit，先打开实时监测展示大屏。
3. 终端 1 运行 `fall-demo`，观察启动后的正常阶段。
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

Linux 无权限时，先查看设备所属组；本机实测 CP2104 属于 `uucp`。请按 `ls -l` 的实际输出选择组名，其他系统可能使用 `dialout`，不要直接照搬本机组名：

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

帧日志默认写入 `data/fall_log.csv`；状态变化、AI 调用和设备交互事件写入 `data/events.csv`。事件包括 `AI_REQUEST`、`AI_RESPONSE`、`AI_ERROR`、`AI_FALLBACK`、`FALL_SUSPECTED`、`FALL_DETECTED`、`ALARM_TRIGGERED`、`ALARM_CANCELLED`、`DEVICE_CONNECTED`、`DEVICE_DISCONNECTED`。事件会同时保存触发时的原始雷达数据。社区层另外使用 `data/community_state.json` 和 `data/community_events.csv`，不修改原始雷达 CSV 格式。Streamlit 社区区域默认每 1.5 秒、技术实时区每 2 秒、日志表格每 5 秒自动更新，无需手动刷新浏览器。

帧日志同时记录 `radar_is_fall`、`ai_result`、`ai_label`、`ai_status`、`ai_success`、`ai_cached`、`ai_model`、`ai_inference_ms`、`ai_message`、`final_result`、`device_state`、`ai_work_state`、`ai_trigger`、`point_count` 和 `radar_points`，用于展示“雷达输入 → 本地 AI → Python 状态机 → 最终业务结果”的完整链路。`radar_points` 使用 JSON 保存每个点的聚类 ID、坐标和速度；`ai_cached=true` 表示当前帧复用了最近一次校验结果。旧日志会自动迁移并补充空点云，不会被误标为真实坐标。

`fall_log.csv` 中的 `source` 字段用于区分数据来源：`mock` 是程序生成的教学数据，`serial` 是从 LD6002C 串口实时读取的数据，`replay` 是历史 `.bin` 回放。排查现场状态时优先确认 Dashboard 的“数据来源”是否为 `serial`。

## 项目结构

```text
src/ld6002c_fall/      Python 数据源、parser、状态机、日志和电脑报警
src/ld6002c_fall/ai/   Ollama 客户端、3 秒调度器、结构化模型与固定 Prompt
src/ld6002c_fall/community/  住户注册、原子状态、事件、传感器映射和演示注入
src/ld6002c_fall/community_demo.py  一键社区课堂演示启动器
src/ld6002c_fall/live_monitor.py  AI Live Monitor 的纯数据模型
tools/                 串口发现与原始数据采集
config/community.json  幸福社区 18 户配置，B2-302 绑定真实 LD6002C
dashboard/app.py       Streamlit URL 路由入口与技术大屏
dashboard/community_ui.py  社区矩阵、住户详情、演示控制台和社区事件
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
