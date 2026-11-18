# Voice Input Bridge

**把任何能采集 PCM 音频的设备，变成 Windows/macOS 上的实时语音输入源。**

Voice Input Bridge（`vib`）是一个与厂商解耦的语音转文字桥接服务。ESP32、M5Stick、浏览器、手机或脚本通过 WebSocket/TCP 发送录音，桥接服务调用云端或本地 ASR，再把增量文字注入当前输入框。

> 默认只监听 `127.0.0.1`。Token 只做身份校验，不提供传输加密。需要跨设备使用时，优先放在可信局域网、WireGuard/Tailscale 后面，或使用 TLS 反向代理。

## 能做什么

- WebSocket / TCP / 可选串口 / 可选 UDP 发现。
- 统一 PCM S16LE 格式和 `AUD1` 二进制帧。
- 边说边出字：支持 `partial` 和 `final` 两类结果。
- Windows 使用 Win32 `SendInput` 注入 Unicode。
- macOS 使用 Quartz 注入 Unicode，也提供剪贴板兜底。
- 内置 `mock`、阿里云 Paraformer、Deepgram、命令行 ASR 适配器。
- 第三方 provider 可作为 Python 插件安装。
- `doctor` 检查依赖、凭据、输入后端和端口。
- HTTP `/health`、`/v1/status`、`/v1/protocol` 状态接口。

## 安全演示

发布到 GitHub 前，请把仓库、`pyproject.toml` 和 Issue 模板中的 `YOUR_GITHUB_USER` 替换为实际用户名。

先不要直接把 mock 文本打进前台窗口。使用 `config.demo.toml`：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
voicebridge doctor --config config.demo.toml
voicebridge serve --config config.demo.toml
```

另开终端：

```powershell
voicebridge simulate --target ws://127.0.0.1:18766/v1/audio
```

这条路径不调用付费 API，也不会碰当前输入框。

## 真正开始输入

```powershell
Copy-Item config.example.toml config.toml
$env:DASHSCOPE_API_KEY = "..."
$env:DASHSCOPE_WORKSPACE_ID = "..."
voicebridge doctor --config config.toml
voicebridge serve --config config.toml
```

Windows 配置：

```toml
[input]
backend = "windows"
send_partial = true
require_same_window = true
```

macOS 配置：

```toml
[input]
backend = "macos"
```

macOS 需要在“系统设置 -> 隐私与安全性 -> 辅助功能”中允许 Python/打包后的应用。Windows 桥接进程不能向管理员权限更高的窗口注入文字。剪贴板兜底只支持最终结果，而且不能判断前台窗口是否变化，因此必须显式设置 `input.require_same_window = false`。

## 内置 ASR

| 方案 | 边说边出字 | 适用场景 |
| --- | --- | --- |
| `aliyun` | 是 | 中文实时听写，支持热词 |
| `deepgram` | 是 | 多语言、低延迟云端听写 |
| `mock` | 是 | CI、协议测试、安装检查 |
| `command` | 否，整段识别 | whisper.cpp、faster-whisper、FunASR、Vosk 等本地 CLI |

云端价格、配额和模型名称会变化，请以 [docs/providers.md](docs/providers.md) 中的官方链接为准。不要把 API Key 写进仓库、截图、Issue 或聊天。

## 设备接入

控制消息是 JSON；音频是 `AUD1` 帧：

```text
41 55 44 31  LL LL  SS SS  <PCM payload>
A  U  D  1  length  seq
```

完整流程：

1. 发送 `hello`。
2. 发送 `start`，声明 16 kHz、单声道、16-bit PCM。
3. 持续发送二进制 `AUD1` 帧。
4. 发送 `stop`。
5. 接收 `partial`、`final`、`session_end`。

详细字段见 [docs/protocol.md](docs/protocol.md)。

## 示例

- `examples/clients/python_client.py`：WAV、stdin 或麦克风。
- `examples/clients/browser/index.html`：浏览器 Web Audio。
- `examples/esp32/arduino_ws_mic`：通用 ESP32 I2S 麦克风。
- `examples/m5stick_s3_ws_dictation`：M5StickS3/M5Unified 参考。

浏览器页面需要通过本地 HTTP 打开：

```powershell
python -m http.server 8000 --directory examples/clients/browser
```

然后访问 `http://127.0.0.1:8000`。远程部署时如页面是 HTTPS，WebSocket 必须使用 `wss://`。

## 常用命令

```powershell
voicebridge serve --config config.toml
voicebridge doctor --config config.toml --json
voicebridge simulate --target ws://127.0.0.1:18766/v1/audio
voicebridge config --config config.toml --json
voicebridge providers
```

## 开发与限制

```powershell
python -m pip install -e ".[dev]"
ruff check .
pytest -q
python -m build
twine check dist/*
```

当前仍是 alpha：

- 云端 provider 的上游事件格式可能变化。
- `command` 本地识别通常要等录音结束后才能返回最终文字。
- macOS Quartz 需要在实际机器上逐版本验证。
- ESP32/M5 示例的麦克风引脚必须按开发板修改。
- 静态 token 不加密网络流量。

安全说明见 [SECURITY.md](SECURITY.md)，协议见 [docs/protocol.md](docs/protocol.md)，排错见 [docs/troubleshooting.md](docs/troubleshooting.md)。

许可证：MIT。
