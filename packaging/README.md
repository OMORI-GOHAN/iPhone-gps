# Windows 独立测试包

目标为 Windows x64，解压整个目录后运行 `iphone-gps.exe`，不要求用户安装 Python、uv 或编译器。保留 `_internal` 文件夹。苹果驱动与设备服务仍是系统组件，不包含在压缩包内。

## 构建

在 Windows 项目目录执行：

```powershell
uv sync --locked --extra device
uv pip install --python .venv/Scripts/python.exe -r packaging/requirements-windows.txt
powershell -ExecutionPolicy Bypass -File packaging/build-windows.ps1
```

输出：`dist/iphone-gps-windows-x64.zip`。使用 PyInstaller onedir，避免每次启动解压完整运行环境。打包工具仅用于开发机。构建脚本运行版本及离线预演检查；设备依赖遵循 uv.lock。

## 使用

```powershell
.\iphone-gps.exe setup
.\iphone-gps.exe setup --install
.\iphone-gps.exe devices
.\iphone-gps.exe gps developer-mode
```

手机上打开「设置 → 隐私与安全性 → 开发者模式」。开启开关并按提示重启；重启后解锁，点「开启」并按提示输入锁屏密码。`gps developer-mode` 只用于显示缺失的设置入口，不自动开启或确认，不需要开发者隧道。完成后继续：

```powershell
.\iphone-gps.exe gps prepare
.\iphone-gps.exe gps set 35.714884 139.796644
```

`setup` 只读检查设备服务及动态组件是否可加载，USB 驱动是否工作由 `devices` 验证。`setup --install` 是显式安装入口：已有设备服务则复用或请求启动；缺失时从苹果官方 HTTPS 地址下载完整安装包（约 200 MB），验证 Apple Inc. 的有效 Authenticode 签名，仅提取设备支持 MSI，再次验证签名后显示安装界面。需要用户确认 UAC 和苹果安装界面，不静默接受许可。

下载临时文件在完成、取消或失败后清理；重试会重新下载。取消发生在安装界面出现前时停止准备，出现安装界面后应在该窗口完成或取消，以避免破坏安装事务。安装日志保留在用户数据目录的 `logs` 中。

定位、清除及准备命令先检查设备。iOS 17+ 已配对且开发者模式开启时，若缺少设备隧道，会复用已有隧道服务并等待设备就绪；没有可用服务时按需请求 UAC 权限，并通过系统自带的 Windows PowerShell 执行原命令。请在新窗口中操作和按 Ctrl+C。

本程序创建的隧道只绑定回环地址，使用 TCP，仅启用 USB 相关监测。GPS 命令清理结束后限时停止该隧道；复用外部服务时不停止它。隧道在本进程后台线程中运行，进程强制结束不会遗留独立隧道进程，但强制结束无法保证执行 GPS 清理。

帮助、版本、坐标预演和地点管理不连接设备或提权。`doctor` 保持只读，不自动启动隧道，因此隧道停止时该项未就绪是预期结果。

后台服务器使用固定 pymobiledevice3 11.49.2 的 `TunneldRunner._app`，升级依赖时需复核。当前只完成开发机打包验证；自动提权、自动隧道、退出清理仍需新程序真机验收，以及干净 Windows 环境复验。
