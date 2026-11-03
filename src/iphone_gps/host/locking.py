"""Per-user, cross-process device exclusion on Linux."""

import fcntl
import hashlib
import os
from pathlib import Path
import stat
import tempfile

from ..core.errors import DeviceBusyError


class DeviceLock:
    def __init__(self, udid: str):
        self.udid = udid
        self._fd = None

    def acquire(self):
        directory = Path(tempfile.gettempdir()) / f"iphone-gps-{os.getuid()}"
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DeviceBusyError("设备锁目录权限不安全")
        name = hashlib.sha256(self.udid.encode()).hexdigest() + ".lock"
        fd = os.open(directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise DeviceBusyError("该设备已有 iphone-gps 会话，请先关闭它") from exc
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd

    def release(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        # Never unlink: another process may already be waiting on this inode.
