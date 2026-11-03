"""Adapter verified against pymobiledevice3 11.49.2.

Modern iOS uses an existing local tunneld. This adapter never starts privileged
host services, installs packages, or enables Developer Mode.
"""

import asyncio
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from ..core.errors import BackendError, DependencyError, DeviceError, DeviceDisconnectedError, GpsError
from ..core.models import Device, Readiness

SUPPORTED_VERSION = "11.49.2"
TUNNEL_HINT = "请先在另一终端运行 sudo python -m pymobiledevice3 remote tunneld，再重试"


def check_dependency():
    try:
        installed = version("pymobiledevice3")
    except PackageNotFoundError as exc:
        raise DependencyError("未安装设备依赖；请运行 uv sync --extra device") from exc
    if installed != SUPPORTED_VERSION:
        raise DependencyError(f"需要 pymobiledevice3=={SUPPORTED_VERSION}，当前为 {installed}")
    return installed


class Resources:
    def __init__(self):
        self.items = []

    def add(self, resource):
        self.items.append(resource)
        return resource

    async def close(self):
        errors = []
        for resource in reversed(self.items):
            try:
                async with asyncio.timeout(1):
                    await resource.close()
            except Exception as exc:
                errors.append(exc)
        self.items.clear()
        if errors:
            raise BackendError("设备连接释放失败") from ExceptionGroup("关闭设备资源失败", errors)


@asynccontextmanager
async def resources_scope():
    resources = Resources()
    original = None
    try:
        yield resources
    except BaseException as exc:
        original = exc
        raise
    finally:
        task = asyncio.create_task(resources.close())
        cancelled = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                cancelled = exc
            except Exception:
                break
        error = task.exception()
        if error is not None:
            if original is not None:
                original.add_note(str(error))
            else:
                raise error
        if cancelled is not None and original is None:
            raise cancelled


class PymobiledeviceConnection:
    def __init__(self, resources, dvt, location, device):
        self.resources = resources
        self.dvt = dvt
        self.location = location
        self.device = device
        self._disconnected = False

    def _require_connected(self):
        if self._disconnected:
            raise DeviceDisconnectedError("设备已断开，无法发送定位或清除请求")

    async def set_location(self, coordinate):
        self._require_connected()
        try:
            await self.location.set(coordinate.latitude, coordinate.longitude)
        except Exception as exc:
            raise BackendError("定位提交失败；连接可能已断开，请检查设备后建立新会话") from exc

    async def clear_location(self):
        self._require_connected()
        try:
            await self.location.clear()
        except Exception as exc:
            raise BackendError("未能清除模拟定位；离线时无法保证恢复") from exc

    async def _wait_usb_detach(self):
        from pymobiledevice3.usbmux import list_devices
        from pymobiledevice3.exceptions import ConnectionFailedToUsbmuxdError, MuxException
        from pymobiledevice3.osu.os_utils import get_os_utils
        while True:
            try:
                async with asyncio.timeout(5):
                    devices = await list_devices()
            except Exception as exc:
                # Arch may stop usbmuxd as soon as the last USB phone leaves.
                # A failed mux query alone is not evidence of physical detach;
                # ask the host USB inventory independently before classifying it.
                if isinstance(exc, (ConnectionFailedToUsbmuxdError, MuxException,
                                    ConnectionError, FileNotFoundError)):
                    try:
                        host_devices = get_os_utils().usb_devices_seen_by_host()
                    except Exception:
                        host_devices = None
                    if host_devices is not None and not any(
                        d.serial.replace('-', '') == self.device.udid.replace('-', '')
                        for d in host_devices
                    ):
                        return
                raise BackendError(f"USB 连接监测失败（{type(exc).__name__}）；请检查 usbmuxd，已停止会话") from exc
            # A network pairing record must not hide the physical USB detach.
            if not any(d.is_usb and d.matches_udid(self.device.udid) for d in devices):
                return
            await asyncio.sleep(0.5)

    async def wait_disconnected(self):
        usb = asyncio.create_task(self._wait_usb_detach())
        transport = asyncio.create_task(self.dvt.dtx.wait_disconnected())
        try:
            done, _ = await asyncio.wait((usb, transport), return_when=asyncio.FIRST_COMPLETED)
            if usb in done:
                usb.result()
                self._disconnected = True
                raise DeviceDisconnectedError("检测到 USB 设备断开；已停止更新，离线时无法发送清除请求")
            transport.result()
            self._disconnected = True
            raise DeviceDisconnectedError("定位通道已断开；已停止更新，无法保证清除定位")
        finally:
            for task in (usb, transport):
                task.cancel()
            await asyncio.gather(usb, transport, return_exceptions=True)

    async def close(self):
        await self.resources.close()


class PymobiledeviceBackend:
    def __init__(self):
        check_dependency()

    async def list_devices(self):
        from pymobiledevice3.usbmux import list_devices
        try:
            return [Device(udid) for udid in sorted({d.serial for d in await list_devices() if d.is_usb})]
        except Exception as exc:
            raise DeviceError("无法访问 USB 设备；请检查 usbmuxd 服务、USB 连接与访问权限") from exc

    async def _lockdown(self, device, resources, *, pair=False):
        from pymobiledevice3.lockdown import create_using_usbmux
        lockdown = resources.add(await create_using_usbmux(
            serial=device.udid, connection_type="USB", autopair=pair, pair_timeout=15))
        return lockdown

    async def _remote(self, device, resources):
        # This helper's HTTP request is synchronous in the pinned upstream version.
        # Query asynchronously via its public tunnel-list API, then connect only
        # the selected USB device, never all available phones.
        from pymobiledevice3.tunneld.api import get_tunneld_tunnels
        from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
        try:
            tunnels = await get_tunneld_tunnels()
            details = tunnels.get(device.udid, [])
            if not details:
                raise DeviceError(TUNNEL_HINT)
            detail = details[0]
            rsd = resources.add(RemoteServiceDiscoveryService(
                (detail["tunnel-address"], detail["tunnel-port"]),
                auxiliary_metadata=detail.get("auxiliary-metadata")))
            await rsd.connect()
            if rsd.udid != device.udid:
                raise DeviceError("隧道设备与所选 USB 设备不匹配")
            return rsd
        except GpsError:
            raise
        except Exception as exc:
            raise DeviceError("开发者隧道不可用；" + TUNNEL_HINT) from exc

    async def _readiness(self, device, lockdown):
        from pymobiledevice3.services.mobile_image_mounter import MobileImageMounterService, image_type_for_device
        issues = []
        developer = mounted = tunnel = None
        if not lockdown.paired:
            issues.append("尚未配对；解锁手机并运行 iphone-gps gps prepare，接受手机上的信任确认")
        else:
            try:
                developer = await lockdown.get_developer_mode_status() if lockdown.has_developer_mode else True
                if not developer:
                    issues.append("请在手机 设置 → 隐私与安全性 中开启开发者模式并完成重启确认")
            except Exception:
                issues.append("无法读取开发者模式；请解锁手机后重试")
            try:
                async with MobileImageMounterService(lockdown) as mounter:
                    mounted = await mounter.is_image_mounted(image_type_for_device(lockdown))
                if not mounted:
                    issues.append("DDI 未挂载；运行 iphone-gps gps prepare 显式准备（可能下载镜像）")
            except Exception:
                issues.append("无法检查 DDI；请解锁手机并检查配对")
            if int(lockdown.product_version.split('.')[0]) >= 17:
                from pymobiledevice3.tunneld.api import get_tunneld_tunnels
                try:
                    tunnel = bool((await get_tunneld_tunnels()).get(device.udid))
                except Exception:
                    tunnel = False
                if not tunnel:
                    issues.append(TUNNEL_HINT)
        return Readiness(device, lockdown.all_values.get("DeviceName", "iPhone"),
                         lockdown.product_version, lockdown.paired, developer, mounted, tunnel, tuple(issues))

    async def check(self, device):
        try:
            async with resources_scope() as resources:
                lockdown = await self._lockdown(device, resources)
                return await self._readiness(device, lockdown)
        except GpsError:
            raise
        except Exception as exc:
            raise DeviceError("设备检查失败；请解锁手机并检查 USB、配对及 usbmuxd") from exc

    async def prepare(self, device):
        from pymobiledevice3.exceptions import AlreadyMountedError
        from pymobiledevice3.services.mobile_image_mounter import auto_mount
        from ..host.locking import DeviceLock
        lock = DeviceLock(device.udid)
        lock.acquire()
        try:
            async with resources_scope() as resources:
                lockdown = await self._lockdown(device, resources, pair=True)
                if lockdown.has_developer_mode and not await lockdown.get_developer_mode_status():
                    raise DeviceError("请先在手机上开启开发者模式并完成重启确认")
                provider = lockdown
                if int(lockdown.product_version.split('.')[0]) >= 17:
                    provider = await self._remote(device, resources)
                try:
                    await auto_mount(provider)
                except AlreadyMountedError:
                    pass
                return await self._readiness(device, lockdown)
        except GpsError:
            raise
        except Exception as exc:
            raise DeviceError("设备准备失败；请检查信任确认、网络及 DDI 兼容性") from exc
        finally:
            lock.release()

    async def connect(self, device):
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
        resources = Resources()
        try:
            lockdown = await self._lockdown(device, resources)
            readiness = await self._readiness(device, lockdown)
            if not readiness.ready:
                raise DeviceError("；".join(readiness.issues))
            provider = lockdown
            if int(lockdown.product_version.split('.')[0]) >= 17:
                provider = await self._remote(device, resources)
            dvt = resources.add(DvtProvider(provider))
            await dvt.connect()
            location = resources.add(LocationSimulation(dvt))
            await location.connect()
            return PymobiledeviceConnection(resources, dvt, location, device)
        except BaseException as exc:
            try:
                # Reuse the cancellation-resistant cleanup path for partial opens.
                async with resources_scope() as scope:
                    scope.items = resources.items
            except Exception as cleanup:
                exc.add_note(str(cleanup))
            if isinstance(exc, (GpsError, asyncio.CancelledError)):
                raise
            raise BackendError("无法打开定位服务；请运行 iphone-gps doctor 检查开发者环境") from exc
