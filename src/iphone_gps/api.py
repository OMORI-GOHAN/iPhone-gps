"""Supported public Python API. Device access is lazy and asynchronous."""

import asyncio

from .core.coordinates import to_wgs84
from .core.errors import (BackendError, CleanupError, DependencyError, DeviceBusyError,
                          DeviceError, DeviceDisconnectedError, GpsError, SessionError)
from .core.models import CleanupResult, Coordinate, Device, Readiness
from .features.gps.session import GpsSession, default_backend, select_device
from .features.gps.places import PlaceError, PlaceStore, SavedPlace


async def list_devices(*, backend=None) -> list[Device]:
    async with asyncio.timeout(30):
        return await (backend or default_backend()).list_devices()


async def check_device(device: str | None = None, *, backend=None) -> Readiness:
    async with asyncio.timeout(30):
        backend = backend or default_backend()
        return await backend.check(await select_device(backend, device))


async def prepare_device(device: str | None = None, *, backend=None) -> Readiness:
    """Explicit pairing/DDI preparation; may download a developer image."""
    async with asyncio.timeout(300):
        backend = backend or default_backend()
        return await backend.prepare(await select_device(backend, device))


__all__ = ["Coordinate", "to_wgs84", "Device", "Readiness", "CleanupResult", "GpsSession",
           "PlaceStore", "SavedPlace", "PlaceError",
           "list_devices", "check_device", "prepare_device", "GpsError", "BackendError",
           "CleanupError", "DependencyError", "DeviceBusyError", "DeviceError", "DeviceDisconnectedError", "SessionError"]
