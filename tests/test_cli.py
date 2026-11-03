import contextlib
import io
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch

from iphone_gps.cli import main


class CliTests(unittest.TestCase):
    def test_offline_commands_never_load_backend(self):
        for args in (['--help'], ['--version'], ['gps', 'set', '--dry-run', '--', '-28', '-112']):
            output = io.StringIO()
            with patch('iphone_gps.features.gps.session.default_backend', side_effect=AssertionError('device accessed')):
                with contextlib.redirect_stdout(output):
                    try:
                        status = main(args)
                    except SystemExit as exc:
                        status = exc.code
            self.assertEqual(status, 0)

    def test_invalid_coordinates_and_duration(self):
        for args in (['gps', 'set', 'nan', '0', '--dry-run'],
                     ['gps', 'set', '0', '181', '--dry-run'],
                     ['gps', 'set', '0', '0', '--duration', '0', '--dry-run']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main(args)
            self.assertEqual(raised.exception.code, 2)

    def test_signals_clear_and_close(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            code = '''
from test_session import Backend
import iphone_gps.features.gps.session as sessions
from iphone_gps.cli import main
backend = Backend()
sessions.default_backend = lambda: backend
status = main(['gps', 'set', '1', '2'])
print(f'cleanup:{backend.connection.clears}:{backend.connection.closes}', flush=True)
raise SystemExit(status)
'''
            env = dict(os.environ)
            root = Path(__file__).resolve().parents[1]
            env['PYTHONPATH'] = os.pathsep.join((str(root / 'src'), str(root / 'tests')))
            process = subprocess.Popen([sys.executable, '-u', '-c', code], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                readable, _, _ = select.select([process.stdout], [], [], 5)
                self.assertTrue(readable, 'CLI did not start')
                self.assertIn('保持连接中', process.stdout.readline())
                process.send_signal(sig)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 128 + sig, stderr)
                self.assertIn('cleanup:1:1', stdout)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()
