# Windows 10/11 x64 离线一键启动

该目录只负责检查和启动现有 Python、Ollama、LD6002C 串口、电脑语音及 Streamlit 大屏，不会联网安装依赖、下载模型或修改系统级 `PATH` / ExecutionPolicy。

## 录课电脑前置准备

1. 安装 64 位 Python 3.11 或更高版本，并在项目根目录创建 `.venv`。
2. 使用离线 wheel 包完成项目安装，确保以下命令成功：

   ```powershell
   .\.venv\Scripts\python.exe -c "import ld6002c_fall, serial, streamlit"
   ```

   不建议从另一台电脑直接复制 `.venv`，因为其中的解释器路径通常与原电脑绑定。可在联网电脑准备 wheelhouse，再在目标电脑使用 `--no-index --find-links` 安装。
3. 安装 Ollama，或者将 standalone `ollama.exe` 放到 `runtime\ollama\ollama.exe`。
4. 提前把 `qwen3:0.6b` 放入目标电脑的 Ollama 模型存储，并在断网状态下确认 `ollama list` 能看到该名称。一键启动不会执行 `ollama pull`。
5. 安装 Silicon Labs CP210x 驱动，连接 LD6002C 后在设备管理器确认出现 `COMx`。
6. 可选：安装 FFmpeg，或将 `ffplay.exe` 放到 `runtime\ffmpeg\bin\ffplay.exe` / `vendor\ffmpeg\bin\ffplay.exe`。缺少播放器时系统会关闭电脑声音并继续运行。

准备完成后，先双击仓库根目录的 `WINDOWS_CHECK.bat`。没有 `[ERROR]` 时，再双击 `START_WINDOWS.bat`。

## 双击入口

| 文件 | 作用 |
| --- | --- |
| `START_WINDOWS.bat` | 检查环境，必要时启动本地 Ollama，选择真实雷达或 mock，启动主程序和大屏，等待页面可访问后打开浏览器。 |
| `WINDOWS_CHECK.bat` | 只检查环境，不启动主程序、大屏或 Ollama。 |
| `STOP_WINDOWS.bat` | 根据 `data\windows-runtime` 中的 PID 状态停止本项目创建的窗口；不会按进程名批量结束 Python。 |

BAT 仅对当前 PowerShell 进程使用 `-ExecutionPolicy Bypass`，不会更改系统永久策略。所有子进程的工作目录都是仓库根目录，支持包含空格和中文的路径。

## 串口选择

`tools\detect_ld6002c_port.py` 使用 pyserial 读取 device、description、manufacturer、VID、PID、serial number 和 HWID。Silicon Labs VID、CP2104、CP210x 等元数据用于标记候选设备：

- 只有一个明确候选时自动选择。
- 有多个候选时显示所有串口并要求选择一次。
- 没有明确候选时可重新扫描、切换 Mock Fall Demo 或退出。
- 选择真实端口后先短暂打开并关闭，以提前发现 Access Denied、上位机占用或旧进程未退出。

需要固定端口时，把 `config.example.cmd` 复制为同目录的 `config.cmd`，设置：

```bat
set "LD6002C_PORT=COM5"
```

`config.cmd` 已被 Git 忽略，不会把某台电脑的 COM 号提交到仓库。

## Ollama 与模型

启动脚本先访问 `OLLAMA_BASE_URL/api/tags`，默认地址是 `http://127.0.0.1:11434/api/tags`：

- API 已在线时直接复用，不重复启动 Ollama。
- API 离线时依次查找 PATH、`%LOCALAPPDATA%\Programs\Ollama\ollama.exe` 和 `runtime\ollama\ollama.exe`，找到后最小化执行 `ollama serve`，最多等待 20 秒。
- API 可用后检查模型列表中是否精确包含 `OLLAMA_MODEL`，默认 `qwen3:0.6b`。
- 模型缺失时明确失败，不尝试联网下载。

只有由本次启动临时创建的 Ollama 才会写入 PID 和可执行文件路径；停止脚本会同时验证 PID、进程名、`serve` 命令和可执行文件路径。启动前已经存在的 Ollama 不会被停止。

## 本地配置

可复制 `config.example.cmd` 为 `config.cmd`，覆盖以下环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LD6002C_PORT` | 空 | 固定 `COMx`；为空时自动扫描。 |
| `LD6002C_BAUDRATE` | `115200` | 雷达串口波特率。 |
| `LD6002C_DASHBOARD_PORT` | `8501` | Streamlit 本机端口。 |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API 地址。 |
| `OLLAMA_MODEL` | `qwen3:0.6b` | 必须已经离线存在的模型名。 |
| `ALARM_VOLUME` | `100` | ffplay 播放音量，范围 0～100。 |

## 运行状态与停止

启动脚本为雷达窗口、Dashboard 窗口及自己启动的 Ollama 记录状态：

```text
data/windows-runtime/
├── radar.pid
├── radar.ready     # 业务 Python 子进程已运行的临时标记
├── dashboard.pid
├── ollama.pid       # 仅启动脚本创建 Ollama 时存在
└── ollama.path      # 用于停止前验证进程归属
```

重复双击启动时，若两个项目窗口仍在运行，脚本只重新打开 Dashboard。若只剩一个窗口，则要求先运行 `STOP_WINDOWS.bat`，避免产生半套重复服务。

## 常见问题

### COM 口无法打开

关闭海凌科官方上位机、串口助手和旧的课程主程序，再重新启动。一个串口同一时间通常只能由一个程序占用。

### 8501 端口已占用

先运行 `STOP_WINDOWS.bat`。若仍被其他程序占用，在 `config.cmd` 中设置 `LD6002C_DASHBOARD_PORT=8502`。

### 找不到雷达

检查 CP210x 驱动、USB 数据线和设备管理器。录课现场可在启动菜单中输入 `M`，立即使用现有 `fall-demo` 模拟流程；Dashboard 会明确显示 `MOCK`。

### 找不到 ffplay

这只会禁用电脑语音。雷达、AI、CSV、控制台报警和 Dashboard 仍会启动。

### 模型缺失

在有网络的准备环境完成模型下载和离线迁移，回到录课电脑后用 `ollama list` 确认。启动脚本不会现场下载。

## 验证边界

仓库在 Linux 开发环境中执行 pytest 和静态检查；PowerShell 脚本按 Windows PowerShell 5.1 语法编写。仍需在目标 Windows 10/11 x64 电脑验证 CP2104 驱动、真实 COM 口、Ollama 安装位置、模型存储迁移、ffplay 音频设备以及两次双击/停止后的进程行为。
