# iPhone GPS

通过开发者接口模拟 iPhone 定位，支持固定定位、连续更新、GCJ-02 坐标转换和命名地点，提供命令行与异步 Python API。Linux 和 Windows 已完成核心定位功能的实机验证。

根据电脑系统选择下面对应的说明。两种系统都需要通过 USB 连接 iPhone，解锁并信任电脑，在手机「设置 → 隐私与安全性」中开启开发者模式并完成重启确认。

## Linux 使用方法

### 安装与连接

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/) 和可用的 `usbmuxd` 服务。Arch Linux 可通过系统包管理器安装 `usbmuxd`；其他发行版请使用对应的软件包和服务管理方式。

```bash
git clone --branch feat/windows-cli https://github.com/OMORI-GOHAN/iPhone-gps.git
cd iPhone-gps
uv sync --locked --extra device
uv run --no-sync iphone-gps devices
```

iOS 17 及以上需要在另一个终端启动开发者隧道，并保持该终端运行：

```bash
sudo .venv/bin/python -m pymobiledevice3 remote tunneld
```

回到原终端检查准备状态：

```bash
uv run --no-sync iphone-gps doctor
```

若提示需要配对或挂载 DDI，执行下面命令，并留意手机上的信任提示。此操作可能下载开发者镜像；完成后再次运行 `doctor` 检查。

```bash
uv run --no-sync gps prepare
```

### 定位与地点管理

输入纬度、经度开始定位，按 **Ctrl+C** 清除并退出。默认坐标系为 WGS84；GCJ-02 输入需显式指定：

```bash
uv run --no-sync gps 35.714884 139.796644
uv run --no-sync gps --coord-system gcj02 28.169004 112.945261
```

仅查看转换结果、不连接手机：

```bash
uv run --no-sync gps --dry-run --coord-system gcj02 28.169004 112.945261
```

保存地点后可直接使用名称定位：

```bash
uv run --no-sync gps place save 湖南大学 --coord-system gcj02 28.169004 112.945261
uv run --no-sync gps 湖南大学
uv run --no-sync gps place list
uv run --no-sync gps place delete 湖南大学
```

测试同一会话内连续更新三个坐标：

```bash
uv run --no-sync python examples/continuous_updates.py --interval 10
```

更多参数见 `uv run --no-sync gps set --help` 和 `uv run --no-sync gps place --help`。设计与 Python API 约定见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## Windows 使用方法

### 安装与连接

推荐使用 **Windows x64 独立测试包** `iphone-gps-windows-x64.zip`，自带 Python 和设备依赖，用户无需另装 Python 或 uv。当前测试包由项目构建生成，获取和构建方式见 [Windows 打包说明](packaging/README.md)。解压整个压缩包，保留程序旁的 `_internal` 文件夹。

电脑需要 Apple USB 驱动和 **Apple Mobile Device Service**。在解压后的 `iphone-gps` 文件夹中打开普通 PowerShell，执行自动安装命令：

```powershell
.\iphone-gps.exe setup --install
```

已有设备服务时会直接复用，或请求启动服务；缺少组件时从苹果官网下载约 200 MB 的安装包，校验苹果数字签名，提取并再次校验 `AppleMobileDeviceSupport64.msi`，然后打开苹果组件安装界面。确认管理员权限提示并按界面完成安装即可，无需完整安装 iTunes，也无需手动下载或解压。安装不会自动重启电脑；若提示需要重启，请完成重启后再连接手机。

苹果组件在运行时从官方下载，不包含在项目压缩包中。仅检查状态而不安装时使用 `setup`。安装取消或失败后可重新执行 `setup --install`。

连接并解锁手机，在解压后的 `iphone-gps` 文件夹中打开普通 PowerShell，依次检查组件和设备：

```powershell
.\iphone-gps.exe setup
.\iphone-gps.exe devices
```

`devices` 成功时会显示设备编号。首次连接或需要准备开发者镜像时运行：

```powershell
.\iphone-gps.exe gps prepare
```

留意手机上的信任和开发者模式提示。首次配对或启用开发者模式后，可能需要再次运行 `gps prepare`；此命令可能下载开发者镜像。

iOS 17 及以上需要开发者隧道。独立程序在执行定位、清除或准备命令时按需管理隧道：已有隧道会直接复用；需要新建时会请求管理员权限，并通过 **Windows PowerShell** 执行命令。确认 Windows 权限提示后，在新窗口中操作。窗口外观仍由系统默认终端设置决定，可能由 Windows Terminal 承载。

可随时进行只读检查：

```powershell
.\iphone-gps.exe doctor
```

`doctor` 不自动启动隧道，因此尚未运行定位或准备命令时，隧道一项可能显示未就绪。

### 定位与地点管理

输入纬度、经度开始定位，在实际运行定位的窗口按 **Ctrl+C** 清除并退出。本程序创建的隧道会在定位清理后停止，外部已有隧道继续运行。

```powershell
.\iphone-gps.exe gps set 35.714884 139.796644
.\iphone-gps.exe gps set --coord-system gcj02 28.169004 112.945261
```

仅查看转换结果、不连接手机：

```powershell
.\iphone-gps.exe gps set --dry-run --coord-system gcj02 28.169004 112.945261
```

保存与复用命名地点：

```powershell
.\iphone-gps.exe gps place save 湖南大学 --coord-system gcj02 28.169004 112.945261
.\iphone-gps.exe gps set 湖南大学
.\iphone-gps.exe gps place list
.\iphone-gps.exe gps place delete 湖南大学
```

更多参数见 `.\iphone-gps.exe gps set --help` 和 `.\iphone-gps.exe gps place --help`。手机地图刷新和位置恢复可能有延迟，请在手机上确认；程序不读取手机实际位置。

### 从源码运行（开发者）

需要 Python 3.11+ 和 uv。在 PowerShell 中执行：

```powershell
git clone --branch feat/windows-cli https://github.com/OMORI-GOHAN/iPhone-gps.git
cd iPhone-gps
uv sync --locked --extra device
.\.venv\Scripts\python.exe -m iphone_gps.windows setup
.\.venv\Scripts\python.exe -m iphone_gps.windows setup --install
.\.venv\Scripts\python.exe -m iphone_gps.windows devices
.\.venv\Scripts\python.exe -m iphone_gps.windows gps prepare
.\.venv\Scripts\python.exe -m iphone_gps.windows gps set 35.714884 139.796644
```

`python -m iphone_gps.windows` 使用与独立程序相同的 Windows 隧道管理入口。若直接使用 `.venv\Scripts\gps.exe` 或 `.venv\Scripts\iphone-gps.exe`，需自行在管理员 PowerShell 中启动隧道并保持运行：

```powershell
.\.venv\Scripts\python.exe -m pymobiledevice3 remote tunneld
```

连续更新示例使用手动启动的隧道：

```powershell
.\.venv\Scripts\python.exe examples/continuous_updates.py --interval 10
```

架构与 Python API 约定见 [ARCHITECTURE.md](ARCHITECTURE.md)，独立程序构建及验收步骤见 [Windows 打包说明](packaging/README.md)。
