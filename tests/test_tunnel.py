import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from iphone_gps.api import GpsError
from iphone_gps.cli import gps_main, main
from iphone_gps.host.tunnel import start_tunnel, tunnel_command


class TunnelTests(unittest.TestCase):
    def test_command_keeps_venv_and_disables_privileged_bytecode(self):
        python = '/project with spaces/.venv/bin/python'
        with patch('iphone_gps.host.tunnel.sys', SimpleNamespace(platform='linux', executable=python)), \
             patch('iphone_gps.host.tunnel.os.geteuid', return_value=1000, create=True):
            self.assertEqual(tunnel_command(), ['sudo', '--', python, '-B', '-m',
                                               'pymobiledevice3', 'remote', 'tunneld'])
        with patch('iphone_gps.host.tunnel.sys', SimpleNamespace(platform='linux', executable=python)), \
             patch('iphone_gps.host.tunnel.os.geteuid', return_value=0, create=True):
            self.assertEqual(tunnel_command()[0], python)

    def test_dry_run_never_elevates_or_loads_device_dependency(self):
        for entry, prefix in ((gps_main, []), (main, ['gps'])):
            stdout = io.StringIO()
            with patch('iphone_gps.host.tunnel.sys', SimpleNamespace(platform='linux', executable='/venv/bin/python')), \
                 patch('iphone_gps.host.tunnel.os.geteuid', return_value=1000, create=True), \
                 patch('iphone_gps.host.tunnel.os.execvp') as execute, \
                 patch('iphone_gps.backends.pymobiledevice.check_dependency', side_effect=AssertionError('dependency accessed')), \
                 contextlib.redirect_stdout(stdout):
                self.assertEqual(entry([*prefix, 'tunnel', '--dry-run']), 0)
            execute.assert_not_called()
            self.assertIn('sudo -- /venv/bin/python -B', stdout.getvalue())

    def test_missing_dependency_fails_before_privilege_request(self):
        with patch('iphone_gps.host.tunnel.sys', SimpleNamespace(platform='linux', executable='/venv/bin/python')), \
             patch('iphone_gps.host.tunnel.os.geteuid', return_value=1000, create=True), \
             patch('iphone_gps.host.tunnel.os.execvp') as execute, \
             patch('iphone_gps.backends.pymobiledevice.check_dependency', side_effect=GpsError('missing dependency')):
            with self.assertRaisesRegex(GpsError, 'missing dependency'):
                start_tunnel()
        execute.assert_not_called()

    def test_other_platform_gets_actionable_error(self):
        with patch('iphone_gps.host.tunnel.sys', SimpleNamespace(platform='win32')):
            with self.assertRaisesRegex(GpsError, 'Windows'):
                tunnel_command()
