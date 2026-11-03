"""Persistent, serialized GPS sessions with bounded best-effort cleanup."""

import asyncio
import math

from ...core.backend import Backend
from ...core.errors import CleanupError, DeviceError, DeviceDisconnectedError, GpsError, SessionError
from ...core.models import CleanupResult, Coordinate
from ...host.locking import DeviceLock


def default_backend():
    from ...backends.pymobiledevice import PymobiledeviceBackend
    return PymobiledeviceBackend()


async def select_device(backend, udid=None):
    devices = await backend.list_devices()
    if udid is not None:
        for device in devices:
            if device.udid == udid:
                return device
        raise DeviceError("指定的 USB 设备不存在，请运行 iphone-gps devices")
    if not devices:
        raise DeviceError("未发现 USB 设备；请解锁手机、连接 USB 并检查 usbmuxd")
    if len(devices) != 1:
        raise DeviceError("发现多台设备，请使用 --device 指定 UDID")
    return devices[0]


class GpsSession:
    """Use ``async with GpsSession(...)``; failures make the session unusable.

    Success records a backend acknowledgement, never an actual GPS measurement.
    Cleanup failures are raised on normal exit, or attached as notes to an existing
    exception. The full structured result remains available in ``cleanup_result``.
    """

    def __init__(self, device: str | None = None, *, backend: Backend | None = None,
                 operation_timeout: float = 30, cleanup_timeout: float = 5):
        for timeout in (operation_timeout, cleanup_timeout):
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("超时必须是正的有限秒数")
        self._udid = device
        self._backend = backend
        self._operation_timeout = operation_timeout
        self._cleanup_timeout = cleanup_timeout
        self._mutex = asyncio.Lock()
        self._connection = None
        self._device_lock = None
        self._close_task = None
        self._watch_task = None
        self._disconnect_error = None
        self._disconnected = False
        self._state = "new"
        self.device = None
        self.target = None
        self.last_submitted = None
        self.actual_location = None
        self.cleanup_result = None

    @property
    def state(self):
        return self._state

    async def __aenter__(self):
        if self._state != "new":
            raise SessionError("会话不能重复打开")
        self._state = "opening"
        try:
            async with asyncio.timeout(self._operation_timeout):
                self._backend = self._backend or default_backend()
                self.device = await select_device(self._backend, self._udid)
                self._device_lock = DeviceLock(self.device.udid)
                self._device_lock.acquire()
                self._connection = await self._backend.connect(self.device)
            self._state = "open"
            self._watch_task = asyncio.create_task(self._watch_connection())
            return self
        except BaseException as exc:
            await self.__aexit__(type(exc), exc, exc.__traceback__)
            raise

    def _require_open(self):
        if self._disconnected:
            raise DeviceDisconnectedError("设备连接已断开；不会继续提交坐标，请重新连接后建立新会话") from self._disconnect_error
        if self._state != "open":
            raise SessionError(f"会话不可用（{self._state}）；请建立新会话")

    async def _submit(self, coordinate=None):
        async with self._mutex:
            self._require_open()
            try:
                async with asyncio.timeout(self._operation_timeout):
                    if coordinate is None:
                        await self._connection.clear_location()
                    else:
                        self.target = coordinate
                        await self._connection.set_location(coordinate)
                self.last_submitted = coordinate
                self.target = coordinate
            except DeviceDisconnectedError as exc:
                self._disconnected = True
                self._disconnect_error = exc
                self._state = "failed"
                raise
            except BaseException:
                self._state = "failed"
                raise

    async def set_location(self, coordinate: Coordinate):
        if not isinstance(coordinate, Coordinate):
            raise TypeError("set_location 需要 Coordinate")
        await self._submit(coordinate)

    async def clear_location(self):
        await self._submit()

    async def _watch_connection(self):
        try:
            await self._connection.wait_disconnected()
            self._disconnected = True
        except DeviceDisconnectedError as exc:
            self._disconnected = True
            self._disconnect_error = exc
        except Exception as exc:
            self._disconnect_error = exc
        if self._state == "open":
            self._state = "failed"

    async def wait_disconnected(self):
        if self._watch_task is None or self._state in ("closing", "closed"):
            raise SessionError("会话尚未打开或已经关闭")
        await asyncio.shield(self._watch_task)
        if self._disconnected:
            message = str(self._disconnect_error) if self._disconnect_error is not None else "设备连接已断开；会话结束，未自动重连，离线时无法保证清除定位"
            raise DeviceDisconnectedError(message) from self._disconnect_error
        detail = (str(self._disconnect_error) if isinstance(self._disconnect_error, GpsError)
                  else type(self._disconnect_error).__name__)
        raise SessionError(f"连接监测失败，已停止会话：{detail}") from self._disconnect_error

    async def _cleanup(self):
        errors = []
        cleared = False
        released = True
        clear_skipped = False
        async with self._mutex:
            try:
                if self._watch_task is not None:
                    self._watch_task.cancel()
                    await asyncio.gather(self._watch_task, return_exceptions=True)
                if self._connection is not None:
                    if self._disconnected:
                        clear_skipped = True
                        errors.append(DeviceDisconnectedError("设备已断开，无法发送清除请求；不能保证手机定位已恢复"))
                    else:
                        try:
                            async with asyncio.timeout(self._cleanup_timeout):
                                await self._connection.clear_location()
                            cleared = True
                        except Exception as exc:
                            errors.append(exc)
                    try:
                        async with asyncio.timeout(self._cleanup_timeout):
                            await self._connection.close()
                    except Exception as exc:
                        released = False
                        errors.append(exc)
            finally:
                if self._device_lock is not None:
                    self._device_lock.release()
                self._state = "closed"
        self.cleanup_result = CleanupResult(cleared, released, tuple(errors), clear_skipped)
        return self.cleanup_result

    async def close(self):
        if self._close_task is None:
            self._state = "closing"
            self._close_task = asyncio.create_task(self._cleanup())
        cancellation = None
        while True:
            try:
                result = await asyncio.shield(self._close_task)
                break
            except asyncio.CancelledError as exc:
                cancellation = exc
        if cancellation is not None:
            if result.errors:
                cancellation.add_note(str(CleanupError(result)))
            raise cancellation
        if result.errors:
            raise CleanupError(result)
        return result

    async def __aexit__(self, exc_type, exc, traceback):
        try:
            await self.close()
        except (CleanupError, asyncio.CancelledError) as cleanup:
            if exc is None:
                raise
            exc.add_note(f"会话清理：{cleanup}")
        return False
