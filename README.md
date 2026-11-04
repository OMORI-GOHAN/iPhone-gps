# iPhone GPS

通过开发者接口模拟 iPhone 定位，支持固定定位、连续更新、GCJ-02 坐标转换和命名地点，提供命令行与异步 Python API。支持 Linux 和 Windows。

使用前通过 USB 连接 iPhone，解锁并信任电脑。

## Linux 使用方法

### 安装

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/) 和 `usbmuxd`。Arch Linux 可通过系统包管理器安装 `usbmuxd`。

```bash
git clone --branch feat/windows-cli https://github.com/OMORI-GOHAN/iPhone-gps.git
cd iPhone-gps
uv sync --locked --extra device
```

### 开启开发者模式

手机打开「设置 → 隐私与安全性 → 开发者模式」。若找不到入口，在项目目录执行后重新打开手机设置：

```bash
uv run gps developer-mode
```

打开开发者模式开关，按提示重启。重启后解锁手机，在确认框中点「开启」，按提示输入锁屏密码。

### 启动通道

iOS 17 及以上在一个终端启动通道，保持运行：

```bash
uv run gps tunnel
```

首次使用时，在另一个终端准备配对及开发者镜像，按手机提示操作（可能下载镜像）：

```bash
uv run gps prepare
```

### 定位与保存地点

纬度在前、经度在后。默认 WGS84；GCJ-02 坐标加 `--coord-system gcj02`。按 **Ctrl+C** 清除并退出。

```bash
uv run gps 35.714884 139.796644
uv run gps --coord-system gcj02 28.169004 112.945261
```

保存后可直接用名称定位：

```bash
uv run gps place save 湖南大学 --coord-system gcj02 28.169004 112.945261
uv run gps 湖南大学
uv run gps place list
uv run gps place delete 湖南大学
```

## Windows 使用方法

### 安装

使用 Windows x64 测试包 `iphone-gps-windows-x64.zip`，无需另装 Python 或 uv。解压整个压缩包，保留 `_internal` 文件夹。在程序文件夹打开普通 PowerShell，安装 Apple 设备组件：

```powershell
.\iphone-gps.exe setup --install
```

按提示确认管理员权限并完成安装；若要求重启电脑，重启后再连接手机。测试包获取及构建方式见 [Windows 打包说明](packaging/README.md)。

### 开启开发者模式

手机打开「设置 → 隐私与安全性 → 开发者模式」。若找不到入口，在程序文件夹执行后重新打开手机设置：

```powershell
.\iphone-gps.exe gps developer-mode
```

打开开发者模式开关，按提示重启。重启后解锁手机，在确认框中点「开启」，按提示输入锁屏密码。

`developer-mode` 需要包含该命令的新构建；旧包提示命令不存在时请更新。

### 准备设备

首次使用或重新开启开发者模式后运行，按手机提示操作（可能下载开发者镜像）：

```powershell
.\iphone-gps.exe gps prepare
```

Windows 独立程序会按需管理通道。出现管理员权限提示时确认，并在新打开的窗口中操作。

### 定位与保存地点

纬度在前、经度在后。默认 WGS84；GCJ-02 坐标加 `--coord-system gcj02`。在实际运行定位的窗口按 **Ctrl+C** 清除并退出。

```powershell
.\iphone-gps.exe gps set 35.714884 139.796644
.\iphone-gps.exe gps set --coord-system gcj02 28.169004 112.945261
```

保存后可直接用名称定位：

```powershell
.\iphone-gps.exe gps place save 湖南大学 --coord-system gcj02 28.169004 112.945261
.\iphone-gps.exe gps set 湖南大学
.\iphone-gps.exe gps place list
.\iphone-gps.exe gps place delete 湖南大学
```

从源码运行时，先安装 Python 3.11+、uv 并执行 `uv sync --locked --extra device`，然后将上述 `.\iphone-gps.exe` 替换为 `.\.venv\Scripts\python.exe -m iphone_gps.windows`。

更多参数使用 `--help` 查看。手机位置恢复及地图刷新可能有延迟。设计与 Python API 见 [ARCHITECTURE.md](ARCHITECTURE.md)。
