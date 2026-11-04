"""User-facing host preparation hints, without installing or starting services."""

import sys


def usb_hint() -> str:
    if sys.platform == 'win32':
        return '请解锁手机、检查 USB 连接和 Apple Mobile Device Service；缺少组件时运行 iphone-gps setup --install，无需完整 iTunes'
    return '请解锁手机、检查 USB 连接、usbmuxd 服务及访问权限'


def tunnel_hint() -> str:
    if sys.platform == 'win32':
        return ('请在项目目录的管理员 PowerShell 中运行 '
                '.\\.venv\\Scripts\\python.exe -m pymobiledevice3 remote tunneld，并保持运行')
    return ('请在项目目录的另一终端运行 '
            'uv run gps tunnel，并保持运行')


def host_requirements() -> str:
    if sys.platform == 'win32':
        return '主机需要 Apple Mobile Device Service 和 Apple 设备驱动；iOS 17+ 需要已有的本地开发者隧道。'
    return '主机需要 usbmuxd；iOS 17+ 需要已有的本地开发者隧道。'
