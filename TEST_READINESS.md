# Windows 测试准备记录

日期：2026-11-03。分支：`feat/windows-cli`，提交：`2d4b00d`。

## 项目理解

CLI 与公开异步 API 共用 GPS 会话；会话管理连接、串行坐标提交、设备锁及限时清理。`backends/pymobiledevice.py` 对接精确版本的设备依赖；`host/` 负责 Windows/Linux 路径、锁和退出处理。地点保存在 SQLite，GCJ-02 在提交前转换为 WGS84。轨迹执行器和插件尚未实现。

## 本机验证

- Windows 内核版本：10.0.26200.0；Python 3.13。
- 已建立 `.venv`，安装项目内 uv，并执行 `uv sync --locked --extra device`，设备依赖为 pymobiledevice3 11.49.2。
- 完整 unittest：51 项全部通过，无跳过。覆盖后端适配、会话清理、模拟断线、Windows 锁、信号、坐标和地点持久化。
- CLI 帮助、GCJ-02 预演、连续更新示例预演及 setup 检查通过。
- 初次受限执行时临时目录权限导致失败；允许测试访问自身临时目录后全量通过。
- 初始环境缺少设备通信服务；安装独立 Apple Mobile Device Support 组件后已能枚举 USB iPhone。
- Windows 真机验收（用户确认）：`doctor` 全部就绪；固定定位生效；Ctrl+C 正常退出，手机位置恢复成功。未记录具体恢复耗时。
- 检查时读取到 iOS 27.0.1。用户进一步确认连续更新及运行中拔线测试功能正常；未记录精确断线检测和位置恢复耗时。
- Ctrl+Break 和命名地点的 Windows 真机专项验收仍待完成；尚未进行干净 Windows 环境安装复验。

## Windows 独立测试包

已生成 `dist/iphone-gps-windows-x64.zip`，无需用户另装 Python/uv。新增启动器测试后共 58 项自动化测试通过；独立程序的版本、GCJ-02 预演、设备服务检查、隧道动态组件加载、USB 枚举和只读 doctor 已通过。关闭全部手机监测后，真实隧道服务器的超时停止及端口释放检查通过。

新包自动提权、自动创建隧道及定位清理待真机复验。详细步骤见 `packaging/README.md`。

后续用户确认初版独立程序定位流程成功；提权入口已按偏好改为 Windows PowerShell。

新增 `setup --install` 苹果组件自动获取及安装入口后，70 项测试通过。真实官方安装包提取和原包/组件签名校验通过，本机已有设备服务时可正确跳过下载和安装。缺少组件的干净 Windows 完整安装流程仍待验收。

## 重跑自动化

在项目目录使用 PowerShell；无需激活虚拟环境，也无需全局安装 uv：

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\gps.exe --dry-run --coord-system gcj02 28.169004 112.945261
.\.venv\Scripts\python.exe examples/continuous_updates.py --dry-run
```

## 真机验收顺序

1. 安装或确认 iTunes 提供的 Apple 设备支持组件及 Apple Mobile Device Service。
2. USB 连接 iPhone，解锁、信任电脑并开启开发者模式。
3. iOS 17+ 在另一个管理员 PowerShell 中进入项目目录，执行并保持运行：
   `.\.venv\Scripts\python.exe -m pymobiledevice3 remote tunneld`。
4. 执行 `.\.venv\Scripts\iphone-gps.exe devices` 和 `.\.venv\Scripts\iphone-gps.exe doctor`。
5. 若检查提示需要配对或 DDI，显式执行 `.\.venv\Scripts\gps.exe prepare`，可能下载镜像。
6. 固定定位：`.\.venv\Scripts\gps.exe 35.714884 139.796644`；在手机上观察，再按 Ctrl+C，确认退出清理及位置恢复耗时。
7. 连续更新：`.\.venv\Scripts\python.exe examples/continuous_updates.py`；观察同一会话三次更新。
8. 单独测试 Ctrl+Break 与运行中拔线，确认停止提交、释放资源，并记录手机位置恢复时间。
9. 用 `gps place save/list/show/delete` 验证命名地点及重启后读取。

记录手机型号、iOS 版本、Apple 驱动版本及各项结果。自动化通过不代表驱动、隧道或手机定位已通过实机验收。
