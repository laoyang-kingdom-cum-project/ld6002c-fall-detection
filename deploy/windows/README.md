# Windows 10/11 x64 离线安装与一键启动

录课电脑只需事先安装 Python 3.11 x64 和 Ollama Windows。完整离线目录复制到电脑后，首次双击安装，之后每次双击启动。脚本不会联网安装、下载模型或修改系统级 `PATH` / ExecutionPolicy。

## 录课电脑前置准备

1. 安装 Python 3.11 x64。安装器会拒绝 32 位、3.10、3.12 或其他版本。
2. 安装 Ollama Windows；也兼容已经准备好的 `runtime\ollama\ollama.exe`。
3. 复制完整离线交付目录，确认包含 `wheelhouse\`、`project-wheel\` 和 `models\`。
4. 双击 `INSTALL_WINDOWS_OFFLINE.bat`，等待 `INSTALLATION COMPLETE`。
5. 安装 Silicon Labs CP210x 驱动，连接 LD6002C 后在设备管理器确认出现 `COMx`。
6. 可选准备 ffplay；缺少播放器时只关闭电脑声音，不影响雷达、AI、日志或大屏。

不要从另一台电脑复制 `.venv`。安装器会在目标电脑创建正式 `.venv`，并用该电脑的 Python 3.11 从离线 wheel 重建环境。

## 双击入口

| 文件 | 作用 |
| --- | --- |
| `INSTALL_WINDOWS_OFFLINE.bat` | 首次创建 `.venv`、安装离线 Python wheel、导入并验证 `qwen3:0.6b`。 |
| `START_WINDOWS.bat` | 检查环境，必要时启动本地 Ollama，选择真实雷达或 mock，启动主程序和大屏，等待页面可访问后打开浏览器。 |
| `WINDOWS_CHECK.bat` | 只检查环境，不启动主程序、大屏或 Ollama。 |
| `STOP_WINDOWS.bat` | 根据 `data\windows-runtime` 中的 PID 状态停止本项目创建的窗口；不会按进程名批量结束 Python。 |

BAT 仅对当前 PowerShell 进程使用 `-ExecutionPolicy Bypass`，不会更改系统永久策略。所有子进程的工作目录都是仓库根目录，支持包含空格和中文的路径。

## 离线安装内容

安装器优先使用 `py -3.11`，找不到时再检查 `python.exe`，并验证解释器必须是 Python 3.11 x64。正式环境固定为 `.venv`；`.builder-venv` 和 `.offline-test` 不参与部署。

Python 安装命令固定使用 `--no-index --find-links wheelhouse`，项目本体来自 `project-wheel\ld6002c_fall_detection-*.whl`。有多个项目 wheel 时选择修改时间最新的文件并打印文件名。完成后执行 `pip check` 和项目导入检查。`requirements-win.txt` 即使存在也只作为锁定依赖参考，安装器不依赖其中的本机路径。

安装器检查 `models\manifests\registry.ollama.ai\library\qwen3\0.6b` 及其引用的每个 blob，然后合并复制到 `OLLAMA_MODELS` 指定目录；未设置时使用 `%USERPROFILE%\.ollama\models`。复制不会使用 `/MIR`，不会删除用户原有模型。目标模型已经完整时直接跳过大文件复制。

模型复制后通过本机 `/api/tags` 验证。如果 Ollama 原本未运行，安装器会临时启动 `ollama serve`，验证完成后只停止自己创建的临时进程；原本已运行的 Ollama 会直接复用且不会关闭。

如果 `.venv` 损坏或版本不正确，在命令提示符运行：

```bat
INSTALL_WINDOWS_OFFLINE.bat -Repair
```

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
| `OLLAMA_MODELS` | `%USERPROFILE%\.ollama\models` | 可选的自定义 Ollama 模型仓库；示例配置默认保持注释。 |
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

确认离线目录包含完整 `models\manifests` 和 `models\blobs`，再运行 `INSTALL_WINDOWS_OFFLINE.bat`。安装器和启动器都不会现场下载。Ollama 已安装但服务停止时，`WINDOWS_CHECK.bat` 会根据本地 manifest/blob 给出离线确认和警告，而不是错误地判定服务不可用。

## 验证边界

普通 Git 仓库忽略大型 `models/`；制作 U 盘交付目录时必须另外放入真实模型，并确认仓库中的 `wheelhouse/` 和 `project-wheel/` 一并复制。当前脚本在 Linux 开发环境中执行 pytest 和静态检查，仍需在断网的 Windows 10/11 x64 真机验证：删除 `.venv` 后首次安装、模型大文件复制、Ollama 识别、CP2104 COM、ffplay，以及重复启动和停止后的进程行为。
