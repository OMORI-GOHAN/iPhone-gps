"""Public errors; third-party failures are retained as exception causes."""


class GpsError(Exception):
    pass


class DependencyError(GpsError):
    pass


class DeviceError(GpsError):
    pass


class DeviceBusyError(DeviceError):
    pass


class SessionError(GpsError):
    pass


class DeviceDisconnectedError(SessionError):
    """The selected USB device disappeared or the GPS transport closed."""


class BackendError(GpsError):
    pass


class CleanupError(GpsError):
    def __init__(self, result):
        self.result = result
        super().__init__("清理失败：" + "; ".join(str(error) or type(error).__name__ for error in result.errors))
