import contextlib
import io
import json
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from iphone_gps import windows


class WindowsLauncherTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell integration')
    def test_powershell_preserves_native_arguments_and_exit_status(self):
        arguments = ['地点 空格', '单引号\'双引号"', '$HOME; `echo hi', '尾部\\']
        code = ('import json,sys; print(json.dumps(sys.argv[1:], ensure_ascii=True)); '
                'raise SystemExit(7)')
        executable, parameters = windows.powershell_command(
            sys.executable, ['-c', code, *arguments])
        result = subprocess.run([executable, *parameters], capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(json.loads(result.stdout), arguments)

    def test_offline_commands_do_not_check_device_or_elevate(self):
        with patch.object(windows, 'sys', SimpleNamespace(platform='win32')), \
             patch('iphone_gps.api.check_device', new_callable=AsyncMock) as check, \
             patch.object(windows, 'elevate') as elevate, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(windows.main(['gps', 'set', '1', '2', '--dry-run']), 0)
            check.assert_not_called()
            elevate.assert_not_called()

    def test_device_free_commands_are_excluded(self):
        parser = windows.build_parser()
        for argv in (['setup'], ['doctor'], ['devices'], ['gps', 'place', 'list']):
            self.assertFalse(windows.needs_device(parser.parse_args(argv)))

    def test_missing_tunnel_elevates_before_running_gps(self):
        ready = SimpleNamespace(product_version='27.0.1', paired=True,
                                developer_mode=True, tunnel_available=False)
        with patch.object(windows, 'sys', SimpleNamespace(platform='win32')), \
             patch('iphone_gps.api.check_device', new=AsyncMock(return_value=ready)), \
             patch.object(windows, 'tunnel_listing', side_effect=OSError), \
             patch.object(windows, 'is_admin', return_value=False), \
             patch.object(windows, 'elevate', return_value=130) as elevate, \
             patch.object(windows, 'run_args') as run:
            self.assertEqual(windows.main(['gps', 'set', '1', '2']), 130)
            elevate.assert_called_once_with(['gps', 'set', '1', '2'])
            run.assert_not_called()

    def test_existing_device_tunnel_runs_without_elevation(self):
        ready = SimpleNamespace(product_version='27', paired=True,
                                developer_mode=True, tunnel_available=True)
        with patch.object(windows, 'sys', SimpleNamespace(platform='win32')), \
             patch('iphone_gps.api.check_device', new=AsyncMock(return_value=ready)), \
             patch.object(windows, 'elevate') as elevate, \
             patch.object(windows, 'run_args', return_value=0):
            self.assertEqual(windows.main(['gps', 'clear']), 0)
            elevate.assert_not_called()

    def test_shared_tunnel_is_never_stopped(self):
        with patch.object(windows, 'tunnel_listing', return_value={'phone': [{}]}), \
             patch('uvicorn.Server') as server:
            with windows.managed_tunnel('phone'):
                pass
            server.assert_not_called()

    def test_owned_tunnel_stops_after_cli_failure(self):
        with patch.object(windows, 'tunnel_listing', side_effect=[OSError(), {'phone': [{}]}]), \
             patch('pymobiledevice3.tunneld.server.TunneldRunner'), \
             patch('uvicorn.Server') as server, \
             patch.object(windows.threading, 'Thread') as thread:
            with self.assertRaisesRegex(RuntimeError, 'gps failed'):
                with windows.managed_tunnel('phone'):
                    raise RuntimeError('gps failed')
            self.assertTrue(server.return_value.should_exit)
            thread.return_value.join.assert_called_once_with(timeout=8)

    def test_shared_tunnel_timeout_does_not_create_or_stop_server(self):
        with patch.object(windows, 'tunnel_listing', return_value={}), \
             patch('uvicorn.Server') as server:
            with self.assertRaisesRegex(windows.GpsError, '超时'):
                with windows.managed_tunnel('phone', timeout=0):
                    self.fail('device must be ready before running GPS')
            server.assert_not_called()


if __name__ == '__main__':
    unittest.main()
