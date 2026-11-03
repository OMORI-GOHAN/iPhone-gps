"""Regression checks for the user-visible USB unplug acceptance example."""

import asyncio
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from iphone_gps.api import GpsSession
from test_session import Backend

path = Path(__file__).resolve().parents[1] / 'examples' / 'continuous_updates.py'
spec = importlib.util.spec_from_file_location('continuous_updates_example', path)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class ExampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_unplug_stops_updates_and_does_not_claim_clear_sent(self):
        backend = Backend()
        session = GpsSession(backend=backend)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(example, 'GpsSession', return_value=session), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            task = asyncio.create_task(example.run(SimpleNamespace(device=None, interval=10)))
            async with asyncio.timeout(1):
                while not backend.connection.writes:
                    await asyncio.sleep(.001)
            backend.connection.disconnected.set()
            status = await asyncio.wait_for(task, 1)
        self.assertEqual(status, 1)
        self.assertEqual(len(backend.connection.writes), 1)
        self.assertEqual(backend.connection.clears, 0)
        self.assertEqual(backend.connection.closes, 1)
        self.assertIn('测试因断线停止', stderr.getvalue())
        self.assertIn('未发送清除请求', stderr.getvalue())
        self.assertNotIn('清除请求已发送', stdout.getvalue() + stderr.getvalue())
        self.assertTrue(session.cleanup_result.clear_skipped)

    async def test_timeout_has_nonempty_description(self):
        backend = Backend()
        backend.connection.error = TimeoutError()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(example, 'GpsSession', return_value=GpsSession(backend=backend)), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = await example.run(SimpleNamespace(device=None, interval=.001))
        self.assertEqual(status, 1)
        self.assertIn('测试失败：设备操作超时', stderr.getvalue())
