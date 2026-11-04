"""Short Linux tunnel launcher using the active project's Python environment."""

import os
import shlex
import sys

from ..core.errors import GpsError


def tunnel_command() -> list[str]:
    if sys.platform != 'linux':
        raise GpsError('gps tunnel 当前用于 Linux；Windows 请使用独立程序的自动通道管理入口')
    # Keep the venv executable path: resolving its symlink would select the
    # system Python without the project's installed device dependencies.
    command = [sys.executable, '-B', '-m', 'pymobiledevice3', 'remote', 'tunneld']
    if os.geteuid() != 0:
        command = ['sudo', '--', *command]
    return command


def start_tunnel(*, dry_run=False):
    command = tunnel_command()
    if dry_run:
        print(shlex.join(command))
        print('预演完成，未启动通道、未请求管理员权限。')
        return
    from ..backends.pymobiledevice import check_dependency
    check_dependency()
    print('正在启动开发者通道，请保持此终端运行；按 Ctrl+C 停止。', flush=True)
    try:
        # Replace this process, so the tunnel directly owns console signals.
        os.execvp(command[0], command)
    except OSError as exc:
        raise GpsError('无法启动开发者通道；请检查 sudo 是否安装以及当前 Python 环境是否可用') from exc
