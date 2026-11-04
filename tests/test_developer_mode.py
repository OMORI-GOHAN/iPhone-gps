import asyncio
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from iphone_gps.api import Device, DeviceError, reveal_developer_mode
from iphone_gps.cli import gps_main, main
from iphone_gps import windows


class DeveloperModeApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_selection_and_error_propagation(self):
        backend = SimpleNamespace(list_devices=AsyncMock(return_value=[Device('a'), Device('b')]),
                                  reveal_developer_mode=AsyncMock())
        with self.assertRaises(DeviceError):
            await reveal_developer_mode(backend=backend)
        backend.reveal_developer_mode.assert_not_awaited()
        await reveal_developer_mode('b', backend=backend)
        backend.reveal_developer_mode.assert_awaited_once_with(Device('b'))
        failure = DeviceError('reveal failed')
        backend.reveal_developer_mode.side_effect = failure
        with self.assertRaises(DeviceError) as raised:
            await reveal_developer_mode('b', backend=backend)
        self.assertIs(raised.exception, failure)


class DeveloperModeCliTests(unittest.TestCase):
    def test_both_entry_points_show_manual_confirmation_instructions(self):
        for entry, prefix in ((gps_main, []), (main, ['gps'])):
            output = io.StringIO()
            with patch('iphone_gps.features.gps.cli.reveal_developer_mode', new=AsyncMock()) as reveal, \
                 contextlib.redirect_stdout(output):
                self.assertEqual(entry([*prefix, 'developer-mode', '--device', 'phone']), 0)
            reveal.assert_awaited_once_with('phone')
            for text in ('隐私与安全性', '重新启动', '重启后解锁', '不会自动开启'):
                self.assertIn(text, output.getvalue())

    def test_windows_does_not_require_tunnel_or_admin_to_reveal(self):
        with patch.object(windows, 'sys', SimpleNamespace(platform='win32')), \
             patch.object(windows, 'elevate') as elevate, \
             patch.object(windows, 'managed_tunnel') as tunnel, \
             patch('iphone_gps.api.check_device', new=AsyncMock()) as check, \
             patch('iphone_gps.features.gps.cli.reveal_developer_mode', new=AsyncMock()) as reveal, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(windows.main(['gps', 'developer-mode']), 0)
        reveal.assert_awaited_once_with(None)
        elevate.assert_not_called()
        tunnel.assert_not_called()
        check.assert_not_called()
