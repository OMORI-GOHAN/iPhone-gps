"""Windows distribution entry point; core API keeps explicit host management."""

import asyncio
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

from .cli import build_parser, run_args
from .core.errors import GpsError


def needs_device(args):
    return (args.command == 'gps' and args.gps_command in ('set', 'clear', 'prepare')
            and not getattr(args, 'dry_run', False))


def is_admin():
    import ctypes
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def tunnel_listing():
    # Local checks must bypass system HTTP proxies and have a bounded timeout.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:49151/', timeout=1) as response:
        listing = json.load(response)
    if not isinstance(listing, dict):
        raise GpsError('隧道端口返回了无法识别的数据，请检查 49151 端口占用')
    return listing


def powershell_command(executable, arguments):
    """Keep native Windows argv quoting, including quotes in saved-place names."""
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$start = New-Object System.Diagnostics.ProcessStartInfo; "
        f"$start.FileName = {literal(executable)}; "
        f"$start.Arguments = {literal(subprocess.list2cmdline(arguments))}; "
        "$start.UseShellExecute = $false; "
        "$child = [System.Diagnostics.Process]::Start($start); "
        "try { $child.WaitForExit() } finally { "
        "if (-not $child.HasExited) { $child.WaitForExit() } }; "
        "exit $child.ExitCode"
    )
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    powershell = (Path(os.environ.get('SystemRoot', r'C:\Windows')) /
                  'System32/WindowsPowerShell/v1.0/powershell.exe')
    return str(powershell), ['-NoLogo', '-NoProfile', '-EncodedCommand', encoded]


def elevate(argv):
    """Wait for the elevated CLI; its console owns interaction and Ctrl+C."""
    from win32com.shell import shell, shellcon
    import win32api
    import win32event
    import win32process

    arguments = list(argv)
    if not getattr(sys, 'frozen', False):
        arguments = ['-m', 'iphone_gps.windows', *arguments]
    powershell, parameters = powershell_command(sys.executable, arguments)
    print('启动开发者隧道需要管理员权限，请确认 Windows 权限提示。', flush=True)
    try:
        result = shell.ShellExecuteEx(
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS, lpVerb='runas',
            lpFile=powershell, lpParameters=subprocess.list2cmdline(parameters),
            lpDirectory=str(Path.cwd()), nShow=1)
    except Exception as exc:
        raise GpsError('未能取得管理员权限；请允许 Windows 权限提示，或在管理员终端重试') from exc
    handle = result['hProcess']
    try:
        while True:
            try:
                if win32event.WaitForSingleObject(handle, 200) == win32event.WAIT_OBJECT_0:
                    return win32process.GetExitCodeProcess(handle)
            except KeyboardInterrupt:
                print('请在新打开的管理员窗口中按 Ctrl+C，完成定位清理。', file=sys.stderr)
    finally:
        win32api.CloseHandle(handle)


@contextmanager
def managed_tunnel(udid, timeout=30):
    """Own one in-process tunnel server, only when no shared server exists.

    TunneldRunner._app is intentionally pinned to pymobiledevice3 11.49.2.
    A daemon thread prevents orphan helper processes if this CLI is killed.
    """
    from pymobiledevice3.tunneld.api import TUNNELD_DEFAULT_ADDRESS
    from pymobiledevice3.tunneld.server import TunneldRunner
    from pymobiledevice3.remote.common import TunnelProtocol
    import uvicorn

    # A reachable server is shared, even if it has no tunnel for this device yet.
    try:
        tunnel_listing()
        shared = True
    except Exception:
        shared = False
    server = thread = None
    failures = []
    if not shared:
        host, port = TUNNELD_DEFAULT_ADDRESS
        runner = TunneldRunner(host, port, protocol=TunnelProtocol.TCP,
                               wifi_monitor=False, mobdev2_monitor=False)
        server = uvicorn.Server(uvicorn.Config(runner._app, host=host, port=port,
                                              log_level='warning', timeout_graceful_shutdown=5))

        def serve():
            try:
                server.run()
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=serve, daemon=True, name='iphone-gps-tunnel')
    try:
        if thread is not None:
            print('正在启动开发者隧道……', flush=True)
            thread.start()
        deadline = time.monotonic() + timeout
        while True:
            if thread is not None and not thread.is_alive():
                raise GpsError('开发者隧道启动失败，请检查端口占用或设备组件') from (failures[0] if failures else None)
            try:
                tunnels = tunnel_listing()
            except Exception:
                tunnels = {}
            if tunnels.get(udid):
                break
            if time.monotonic() >= deadline:
                raise GpsError('等待设备隧道超时；请保持手机解锁，检查信任和开发者模式后重试')
            time.sleep(.2)
        yield
    finally:
        if server is not None:
            server.should_exit = True
            thread.join(timeout=8)
            if thread.is_alive():
                print('开发者隧道未在限时内停止，将随本程序退出释放。', file=sys.stderr)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    if sys.platform == 'win32' and args.command == 'setup':
        try:
            # Check dynamic native imports in the distribution without starting a service.
            from pymobiledevice3.tunneld.server import TunneldRunner
            from win32com.shell import shell
            print('内置隧道及 Windows 权限组件：可加载')
        except Exception as exc:
            print(f'错误：Windows 运行组件不完整（{exc}）', file=sys.stderr)
            return 1
    if sys.platform != 'win32' or not needs_device(args):
        return run_args(args)
    try:
        from .api import check_device
        readiness = asyncio.run(check_device(getattr(args, 'device', None)))
        # Pairing and enabling Developer Mode still use the existing explicit flow.
        if (int(readiness.product_version.split('.')[0]) < 17 or not readiness.paired
                or readiness.developer_mode is not True or readiness.tunnel_available):
            return run_args(args)
        try:
            tunnel_listing()
        except Exception:
            if not is_admin():
                return elevate(argv)
        with managed_tunnel(readiness.device.udid):
            # run_args waits for GPS cleanup before this context closes the tunnel.
            return run_args(args)
    except KeyboardInterrupt:
        return 130
    except (GpsError, TimeoutError, OSError) as exc:
        print(f'错误：{str(exc) or "设备操作超时"}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
