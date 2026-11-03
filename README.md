# iPhone GPS

通过开发者接口模拟 iPhone 定位，支持固定定位、连续更新、GCJ-02 坐标转换和命名地点。提供 CLI 与异步 Python API。Linux 已实机验证，Windows 已加入命令行适配，待实机验证。

## 项目构成

```text
src/iphone_gps/
├── api.py          # Python 公开接口
├── cli.py          # 命令入口
├── core/           # 坐标转换、数据模型和错误
├── backends/       # pymobiledevice3 设备适配
├── host/           # 平台路径、设备锁和退出处理
└── features/gps/   # GPS 会话、命名地点和命令
examples/           # 连续更新示例
tests/              # 自动化测试
```

设计说明见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。Linux 需可用的 `usbmuxd`；Windows 需安装 [iTunes](https://www.apple.com/itunes/download/win64) 提供的 Apple 设备驱动与服务。

```bash
git clone https://github.com/OMORI-GOHAN/iPhone-gps.git
cd iPhone-gps
uv sync --extra device
```

通过 USB 连接并解锁 iPhone，信任电脑，开启手机的开发者模式。iOS 17+ 在另一个终端启动隧道并保持运行：

```bash
sudo .venv/bin/python -m pymobiledevice3 remote tunneld
```

Windows 请改用管理员 PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pymobiledevice3 remote tunneld
```

检查连接；若提示需要配对或挂载 DDI，再执行 `uv run gps prepare`（可能下载镜像）：

```bash
uv run iphone-gps devices
uv run iphone-gps doctor
```

输入纬度、经度开始定位，按 **Ctrl+C** 清除并退出。默认 WGS84；GCJ-02 输入需显式指定：

```bash
uv run gps 35.714884 139.796644
uv run gps --coord-system gcj02 28.169004 112.945261
```

保存地点后，可直接用名称定位：

```bash
uv run gps place save 湖南大学 --coord-system gcj02 28.169004 112.945261
uv run gps 湖南大学
uv run gps place list
uv run gps place delete 湖南大学
```

更多参数见 `uv run gps set --help`，地点管理见 `uv run gps place --help`。
