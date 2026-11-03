"""Per-user, cross-process device exclusion on Linux and Windows."""

import errno
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile

from ..core.errors import DeviceBusyError, DeviceError
from .paths import user_data_directory


def _lock_file(fd):
    if sys.platform == 'win32':
        import msvcrt
        # Lock the first byte, even when the file is empty. The CRT permits
        # locking beyond EOF; no initialization write can race with an owner.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(fd):
    if sys.platform == 'win32':
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    # On Linux closing the descriptor releases flock.


class DeviceLock:
    def __init__(self, udid: str):
        self.udid = udid
        self._fd = None

    def acquire(self):
        if self._fd is not None:
            raise DeviceBusyError('该设备锁已经被当前会话持有')
        fd = None
        try:
            if sys.platform == 'win32':
                directory = user_data_directory() / 'locks'
                directory.mkdir(parents=True, exist_ok=True)
                flags = os.O_CREAT | os.O_RDWR | os.O_BINARY | os.O_NOINHERIT
            else:
                directory = Path(tempfile.gettempdir()) / f'iphone-gps-{os.getuid()}'
                directory.mkdir(mode=0o700, exist_ok=True)
                info = directory.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise DeviceBusyError('设备锁目录权限不安全')
                flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
            name = hashlib.sha256(self.udid.encode()).hexdigest() + '.lock'
            fd = os.open(directory / name, flags, 0o600)
            try:
                _lock_file(fd)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise DeviceBusyError('该设备已有 iphone-gps 会话，请先关闭它') from exc
                raise
            self._fd = fd
        except BaseException as exc:
            if fd is not None:
                os.close(fd)
            if isinstance(exc, OSError):
                raise DeviceError('无法创建或获取设备锁，请检查用户目录权限') from exc
            raise

    def release(self):
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                _unlock_file(fd)
            finally:
                os.close(fd)
        # Never unlink: another process may already be waiting on this inode.
