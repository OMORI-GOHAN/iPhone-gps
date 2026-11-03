import asyncio
import os
import subprocess
import sys
import unittest

from iphone_gps.api import (Coordinate, GpsSession, Device, DeviceBusyError, DeviceError,
                            CleanupError, SessionError)
from iphone_gps.host.locking import DeviceLock


class Connection:
    def __init__(self):
        self.writes = []
        self.clears = 0
        self.closes = 0
        self.active = 0
        self.max_active = 0
        self.error = None
        self.clear_error = None
        self.hang_clear = False
        self.hang_close = False
        self.disconnected = asyncio.Event()

    async def set_location(self, coordinate):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(.005)
            if self.error:
                raise self.error
            self.writes.append(coordinate)
        finally:
            self.active -= 1

    async def clear_location(self):
        self.clears += 1
        if self.hang_clear:
            await asyncio.Event().wait()
        if self.clear_error:
            raise self.clear_error

    async def close(self):
        self.closes += 1
        if self.hang_close:
            await asyncio.Event().wait()

    async def wait_disconnected(self):
        await self.disconnected.wait()


class Backend:
    def __init__(self):
        self.devices = [Device(f'test-device-{os.getpid()}')]
        self.connection = Connection()
        self.connections = 0

    async def list_devices(self):
        return self.devices

    async def connect(self, device):
        self.connections += 1
        return self.connection


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_serialized_updates(self):
        backend = Backend()
        points = [Coordinate(i, -i) for i in range(10)]
        async with GpsSession(backend=backend) as session:
            await asyncio.gather(*(session.set_location(point) for point in points))
            self.assertEqual(session.last_submitted, points[-1])
            self.assertIsNone(session.actual_location)
            await session.clear_location()
            self.assertIsNone(session.last_submitted)
        self.assertEqual(backend.connections, 1)
        self.assertEqual(backend.connection.writes, points)
        self.assertEqual(backend.connection.max_active, 1)
        self.assertEqual(backend.connection.closes, 1)
        self.assertTrue(session.cleanup_result.cleared)
        await session.close()
        self.assertEqual(backend.connection.closes, 1)
        with self.assertRaises(SessionError):
            await session.set_location(points[0])

    async def test_selection(self):
        backend = Backend()
        for devices in ([], [Device('a'), Device('b')]):
            backend.devices = devices
            with self.assertRaises(DeviceError):
                async with GpsSession(backend=backend):
                    self.fail('must not open')
        self.assertEqual(backend.connections, 0)
        backend.devices = [Device('a'), Device('b')]
        async with GpsSession('b', backend=backend) as session:
            self.assertEqual(session.device.udid, 'b')
        with self.assertRaises(DeviceError):
            async with GpsSession('missing', backend=backend):
                pass

    async def test_lock_and_release(self):
        backend = Backend()
        async with GpsSession(backend=backend):
            with self.assertRaises(DeviceBusyError):
                async with GpsSession(backend=Backend()):
                    pass
            result = subprocess.run([sys.executable, '-c',
                f"from iphone_gps.host.locking import DeviceLock; DeviceLock({backend.devices[0].udid!r}).acquire()"],
                capture_output=True, env=os.environ)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'DeviceBusyError', result.stderr)
        async with GpsSession(backend=Backend()):
            pass

    async def test_error_preserves_last_success_and_original(self):
        backend = Backend()
        error = ConnectionError('offline')
        async with GpsSession(backend=backend) as session:
            good = Coordinate(1, 2)
            await session.set_location(good)
            backend.connection.error = error
            with self.assertRaises(ConnectionError) as raised:
                await session.set_location(Coordinate(3, 4))
            self.assertIs(raised.exception, error)
            self.assertEqual(session.last_submitted, good)
            self.assertEqual(session.target, Coordinate(3, 4))
            with self.assertRaises(SessionError):
                await session.set_location(good)
        self.assertEqual(backend.connections, 1)

    async def test_cancellation_cleans(self):
        backend = Backend()
        started = asyncio.Event()
        async def run():
            async with GpsSession(backend=backend):
                started.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(run())
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(backend.connection.clears, 1)
        self.assertEqual(backend.connection.closes, 1)
        async with GpsSession(backend=Backend()):
            pass

    async def test_repeated_cancel_during_cleanup(self):
        backend = Backend()
        backend.connection.hang_clear = True
        session = GpsSession(backend=backend, cleanup_timeout=.03)
        await session.__aenter__()
        task = asyncio.create_task(session.close())
        await asyncio.sleep(.005)
        task.cancel()
        await asyncio.sleep(.005)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(backend.connection.closes, 1)
        self.assertIsInstance(session.cleanup_result.errors[0], TimeoutError)
        async with GpsSession(backend=Backend()):
            pass

    async def test_cleanup_failure_reported_and_original_retained(self):
        backend = Backend()
        backend.connection.clear_error = ConnectionError('clear failed')
        with self.assertRaises(CleanupError) as raised:
            async with GpsSession(backend=backend):
                pass
        self.assertTrue(raised.exception.result.released)
        self.assertEqual(backend.connection.closes, 1)
        original = ValueError('user code failed')
        session = GpsSession(backend=backend)
        with self.assertRaises(ValueError) as raised:
            async with session:
                raise original
        self.assertIs(raised.exception, original)
        self.assertTrue(original.__notes__)
        self.assertEqual(len(session.cleanup_result.errors), 1)

    async def test_cleanup_timeouts_release_lock(self):
        backend = Backend()
        backend.connection.hang_clear = backend.connection.hang_close = True
        with self.assertRaises(CleanupError) as raised:
            async with GpsSession(backend=backend, cleanup_timeout=.01):
                pass
        self.assertEqual(len(raised.exception.result.errors), 2)
        self.assertFalse(raised.exception.result.released)
        async with GpsSession(backend=Backend()):
            pass

    async def test_write_timeout(self):
        backend = Backend()
        async with GpsSession(backend=backend, operation_timeout=.001) as session:
            with self.assertRaises(TimeoutError):
                await session.set_location(Coordinate(1, 2))
            self.assertEqual(session.state, 'failed')
            self.assertIsNone(session.last_submitted)

    async def test_open_failure_releases_lock(self):
        backend = Backend()
        async def fail(device):
            raise ConnectionError('open failed')
        backend.connect = fail
        with self.assertRaises(ConnectionError):
            async with GpsSession(backend=backend):
                pass
        async with GpsSession(backend=Backend()):
            pass

    async def test_disconnect_ends_session(self):
        backend = Backend()
        with self.assertRaises(CleanupError):
            async with GpsSession(backend=backend) as session:
                backend.connection.disconnected.set()
                with self.assertRaises(SessionError):
                    await session.wait_disconnected()
                with self.assertRaises(SessionError):
                    await session.clear_location()
        self.assertEqual(backend.connections, 1)
        self.assertEqual(backend.connection.clears, 0)
        self.assertEqual(backend.connection.closes, 1)
        self.assertTrue(session.cleanup_result.clear_skipped)
        self.assertFalse(session.cleanup_result.cleared)

    async def test_disconnect_detected_without_waiter(self):
        backend = Backend()
        with self.assertRaises(CleanupError):
            async with GpsSession(backend=backend) as session:
                backend.connection.disconnected.set()
                await asyncio.sleep(0)
                self.assertEqual(session.state, 'failed')
                with self.assertRaises(SessionError):
                    await session.set_location(Coordinate(1, 2))
        self.assertEqual(backend.connection.closes, 1)


class CoordinateTests(unittest.TestCase):
    def test_validation(self):
        for value in (float('nan'), float('inf'), -float('inf'), 91, -91, True, '1'):
            with self.assertRaises(ValueError):
                Coordinate(value, 0)
        for value in (181, -181, float('nan')):
            with self.assertRaises(ValueError):
                Coordinate(0, value)
        self.assertEqual(Coordinate(-90, 180).longitude, 180)
