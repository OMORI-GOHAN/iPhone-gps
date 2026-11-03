iPhone GPS Windows 测试版（x64）

解压整个文件夹，保留 _internal 目录。不需要另装 Python 或 uv。
在该文件夹打开 PowerShell：

  .\iphone-gps.exe setup
  .\iphone-gps.exe setup --install
  .\iphone-gps.exe devices
  .\iphone-gps.exe doctor
  .\iphone-gps.exe gps prepare
  .\iphone-gps.exe gps set 35.714884 139.796644

需要苹果 USB 驱动和 Apple Mobile Device Service。
运行 setup --install 可自动从苹果官网下载、校验并提取设备支持组件。
已有服务时直接复用或请求启动，无需重复下载。
请确认 Windows 权限提示并在苹果安装界面完成安装，无需完整 iTunes。
下载约 200 MB，临时文件在流程结束后清理；安装不会自动重启。
本项目不包含苹果安装文件。安装取消或失败后可再次运行 setup --install。
安装组件后连接手机，解锁并确认信任，在手机上开启开发者模式。
prepare 是显式配对与开发者镜像准备操作，可能下载镜像。

iOS 17+ 定位/清除/准备命令在需要时请求管理员权限，并打开 Windows PowerShell 会话。
窗口外壳由系统默认终端设置决定，可能仍由 Windows Terminal 承载。
在管理员窗口中操作，按 Ctrl+C 停止定位。已有开发者隧道直接复用。
本程序创建的隧道在 GPS 清理后停止；外部已有的隧道保持运行。
首次配对或启用开发者模式后，可再次执行 prepare，然后 doctor 检查。
doctor 只读检查，不自动创建隧道；未启动隧道时该项显示未就绪是正常的。

命名地点（保存和预演不连接手机）：
  .\iphone-gps.exe gps place save 测试地点 35.714884 139.796644
  .\iphone-gps.exe gps set 测试地点

手机地图更新和位置恢复可能有延迟。命令成功不代表已读取真实 GPS。
此包尚需在干净 Windows 环境及真实手机上复验自动提权和隧道退出。
