"""Application entry point. Only this layer prints user-facing results."""

import argparse
import asyncio
import signal
import sys
import threading

from . import __version__
from .api import GpsError, check_device, list_devices
from .features.gps.cli import configure_parser, print_readiness, register_parser
from .host.environment import host_requirements, usb_hint
from .host.signals import cancel_on_signals


async def host_command(args):
    if args.command == "setup":
        from .backends.pymobiledevice import check_dependency
        print(f"设备依赖：pymobiledevice3 {check_dependency()}")
        print(host_requirements())
        if getattr(args, 'install', False):
            if sys.platform != 'win32':
                raise GpsError('setup --install 仅用于 Windows 的 Apple 设备组件安装')
            from .host.windows_installer import install_components
            cancel = threading.Event()
            installation = asyncio.create_task(asyncio.to_thread(install_components, cancel))
            try:
                return await asyncio.shield(installation)
            except asyncio.CancelledError:
                cancel.set()
                # Do not remove an installer's temporary files while it is running.
                while not installation.done():
                    try:
                        await asyncio.shield(installation)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if installation.done() and not installation.cancelled():
                    installation.exception()
                raise
        if sys.platform == 'win32':
            from .host.windows_components import component_status
            print(component_status())
        print("设备准备请运行 iphone-gps gps prepare；本命令不安装、不挂载。")
        return 0
    if args.command == "devices":
        devices = await list_devices()
        for device in devices:
            print(device.udid)
        if not devices:
            print("未发现 USB 设备；" + usb_hint())
            return 1
        return 0
    return print_readiness(await check_device(args.device))


def build_parser():
    parser = argparse.ArgumentParser(prog="iphone-gps", description="可编程 iPhone GPS 工具")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, description in (("setup", "检查主机依赖；Windows 可显式安装设备组件"),
                              ("doctor", "只读检查 USB、配对及开发者环境"), ("devices", "列出 USB 设备")):
        action = commands.add_parser(name, help=description)
        action.set_defaults(handler=host_command)
        if name == 'setup':
            action.add_argument('--install', action='store_true',
                                help='Windows：从苹果官网下载、校验并安装设备支持组件')
        if name == "doctor":
            action.add_argument("--device", metavar="UDID")
    register_parser(commands)
    return parser


async def dispatch(args):
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    with cancel_on_signals(loop, task) as cancellation:
        try:
            return await args.handler(args)
        except asyncio.CancelledError as exc:
            print("操作已取消，已尝试清理会话。", file=sys.stderr)
            if args.command == "gps" and args.gps_command in ("set", "clear"):
                print("手机位置恢复及地图刷新可能有延迟，请在手机上确认。", file=sys.stderr)
            for note in getattr(exc, "__notes__", ()):
                print(note, file=sys.stderr)
            return 128 + (cancellation.received or signal.SIGINT)


def main(argv=None):
    return run_args(build_parser().parse_args(argv))


def gps_main(argv=None):
    """Project-local shortcut: gps LAT LON, gps clear, gps status, ..."""
    parser = argparse.ArgumentParser(
        prog="gps", description="iPhone GPS 快捷命令",
        epilog="直接定位：gps 纬度 经度，或 gps 地点名；保存地点：gps place save 名称 纬度 经度。负数可放在 -- 后。")
    parser.add_argument("--version", action="version", version=__version__)
    parser.set_defaults(command="gps")
    configure_parser(parser)
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        parser.print_help()
        return 0
    if arguments[0] not in ("set", "clear", "status", "prepare", "place", "tunnel", "-h", "--help", "--version"):
        arguments.insert(0, "set")
    return run_args(parser.parse_args(arguments))


def run_args(args):
    try:
        return asyncio.run(dispatch(args))
    except (GpsError, TimeoutError) as exc:
        print(f"错误：{str(exc) or '设备操作超时，请检查连接后重试'}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        return 1
    except KeyboardInterrupt as exc:
        print("操作已取消。", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        return 130
