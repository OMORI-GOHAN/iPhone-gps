# Windows 精简交付约定

目标：原生 Windows 使用；最终用户尽量只安装本项目。Arch 验证不替代 Windows 验收。

## 用户体验要求

- 发布包自带 Python 运行环境、项目及锁定的设备依赖；用户无需安装 Python、uv、MSYS2 或编译器。
- 首次运行先只读检查 USB 驱动、通信服务和设备；已有可用组件时直接复用。
- 缺少系统组件时明确展示组件及作用，再由用户执行安装；不把完整 iTunes 作为唯一入口。
- 开发者隧道后续由启动器管理，复用已有服务；需要提权时明确提示，避免要求用户长期手动管理第二个终端。
- 手机信任、开发者模式和必要的 Windows 权限确认仍保留。

## 技术路线与验证关口

1. 先验证通信基础：苹果设备支持组件与开源 usbmuxd 分别评估，不以是否开源代替安装成本判断。
2. 苹果组件路线：本机独立设备支持组件已通过 USB 枚举和固定定位验收；继续确认干净环境依赖及再分发条件，不直接把苹果安装文件打进发布包。
3. 开源路线：需要实际 Windows 构建、libusb 可用的 USB 驱动、配对记录读写和协议兼容性验证。usbmuxd README 标注 Windows 测试支持，但当前官方 CI 只构建 Linux，不能按成熟 Windows 安装方案交付。
4. 现有 pymobiledevice3 11.49.2 支持 USBMUXD_SOCKET_ADDRESS 指向 TCP 服务，项目可利用该入口进行兼容测试，无需提前改写 GPS 核心。
5. 完成设备枚举、配对和隧道验证后，再验证定位、Ctrl+C/Ctrl+Break、拔线及资源回收。
6. 最后制作包含运行环境的 Windows 发布包，在没有 Python 和苹果软件的干净 Windows 环境验收安装数量、权限提示及卸载行为。

选择标准：真实 USB 通信稳定、组件数量少、可维护、可卸载，并尽量保持现有苹果软件兼容。开源 usbmuxd 是否满足这些标准尚待验证。

## 当前状态（2026-11-03）

- 分支 feat/windows-cli：Windows 路径、设备锁、信号适配已存在。
- Python 3.13 下 51 项自动化测试通过。
- 独立 Apple Mobile Device Support 安装后，USB 枚举成功；用户确认 doctor 全部就绪、固定定位、Ctrl+C 后位置恢复、连续更新及拔线测试功能正常。具体恢复耗时未记录。
- 已制作 Windows x64 独立测试包：`dist/iphone-gps-windows-x64.zip`；自带 Python 和设备依赖，支持按需 UAC 提权、隧道复用与自动启动/停止。新增 `setup --install`，显式从苹果官网获取、校验、提取并显示设备支持组件安装界面；已有服务则复用或请求启动。
- 用户已完成独立苹果设备支持组件安装；尚未验证开源 usbmuxd 驱动路线。
- 新增 Windows 启动器边界测试后共 58 项自动化测试通过。独立程序的版本、预演、组件动态加载、USB 枚举及只读 doctor 检查已通过；另以关闭手机监测的真实服务器验证超时后停止和端口释放。
- 新程序的 UAC 交互、自动建隧道后的定位和退出清理，以及干净 Windows 环境安装仍需复验；原源码版真机结果不代替新程序验收。
- 用户随后确认独立测试包的自动提权及定位流程成功。按用户偏好，提权入口进一步改为 Windows PowerShell；该改动的参数和退出状态集成测试通过，全量测试现为 59 项。新入口的实际 Ctrl+C 行为待用户复验。

## 最小苹果组件检查结果

已从苹果官方 `https://www.apple.com/itunes/download/win64` 下载安装包，原包和提取后的 MSI 的 Authenticode 签名均为 Valid，签名者为 Apple Inc.。

- 独立组件：`.venv/windows-deps/AppleMobileDeviceSupport64.msi`。
- 版本：20.0.1.47；MSI 文件约 32.8 MiB（不是安装后占用）。
- MSI ServiceInstall 表包含 Apple Mobile Device Service，自动启动，依赖 Tcpip。
- LaunchCondition 表未要求先安装 iTunes 或 Apple Application Support；要求管理员权限及受支持的 64 位 Windows。此项仅为静态检查，不等于独立安装已通过。
- 详细静态检查：`.venv/windows-deps/msi-inspection.json`。
- 用户安装后已确认设备枚举、doctor 全部就绪、固定定位、Ctrl+C 恢复、连续更新和拔线测试功能正常；说明本机无需完整 iTunes 即可完成这些操作。下一阶段是精简交付与干净 Windows 环境复验；Ctrl+Break 和命名地点专项验收待补充。

开发机安装命令（显示正常安装界面）：

```powershell
msiexec.exe /i "D:\git\iPhone-GPS\.venv\windows-deps\AppleMobileDeviceSupport64.msi"
```

用户最终发行版本仍需确认组件获取、许可、升级及卸载流程；本次提取不代表已获得再分发许可。

## 自动安装入口

`setup --install` 在缺少设备服务时从官方 HTTPS 下载，校验完整安装包和提取的 MSI 的有效 Apple Inc. 签名；显示 UAC 与苹果安装界面，不自动接受许可，不自动重启。Python TLS 不兼容时回退系统 curl，保持 HTTPS 校验。临时文件在流程结束后清理，安装日志保留在用户数据目录 logs 中。

70 项测试通过，覆盖复用服务、启动已停止服务、不完整下载、非官方跳转、TLS 回退、取消下载、签名失败、安装取消和需要重启的结果。已用真实官方包验证提取及双重签名，并核对提取结果与之前真机验证的 MSI 一致。本机已有服务的跳过安装流程通过；缺少组件的干净 Windows 上完整安装尚待验收，不卸载现有可用组件来模拟。

## 依据

- usbmuxd：https://github.com/libimobiledevice/usbmuxd
- 当前官方构建流程：https://github.com/libimobiledevice/usbmuxd/blob/master/.github/workflows/build.yml
- libusb Windows 驱动要求：https://github.com/libusb/libusb/wiki/Windows
