"""Backend-independent values returned by the public API."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float

    def __post_init__(self):
        for name, limit in (("latitude", 90), ("longitude", 180)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} 必须是数字")
            if not -limit <= value <= limit or not math.isfinite(value):
                raise ValueError(f"{name} 必须是 {-limit} 到 {limit} 之间的有限值")


@dataclass(frozen=True)
class Device:
    udid: str


@dataclass(frozen=True)
class Readiness:
    device: Device
    name: str
    product_version: str
    paired: bool
    developer_mode: bool | None
    ddi_mounted: bool | None
    tunnel_available: bool | None
    issues: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class CleanupResult:
    # A successful clear call is a local submission, not a device acknowledgement.
    cleared: bool
    released: bool
    errors: tuple[Exception, ...] = ()
    clear_skipped: bool = False
