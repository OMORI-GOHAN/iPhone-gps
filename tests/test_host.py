import contextlib
import io
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from iphone_gps.api import PlaceStore
from iphone_gps.cli import gps_main
from iphone_gps.host.environment import tunnel_hint, usb_hint
from iphone_gps.host.locking import DeviceLock
from iphone_gps.host.paths import user_data_directory


class HostTests(unittest.TestCase):
    def test_linux_data_path_preserves_existing_location(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('iphone_gps.host.paths.sys', SimpleNamespace(platform='linux')), \
             patch.dict(os.environ, {'XDG_DATA_HOME': directory, 'LOCALAPPDATA': 'unused'}):
            self.assertEqual(user_data_directory(), Path(directory) / 'iphone-gps')
            self.assertEqual(PlaceStore().path, Path(directory) / 'iphone-gps' / 'places.sqlite3')
            self.assertEqual(list(Path(directory).iterdir()), [])
        with patch('iphone_gps.host.paths.sys', SimpleNamespace(platform='linux')), \
             patch.dict(os.environ, {'XDG_DATA_HOME': 'relative/path'}):
            self.assertEqual(user_data_directory(), Path.home() / '.local/share/iphone-gps')

    def test_windows_data_path_uses_local_app_data(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('iphone_gps.host.paths.sys', SimpleNamespace(platform='win32')), \
             patch.dict(os.environ, {'LOCALAPPDATA': directory, 'XDG_DATA_HOME': 'unused'}):
            self.assertEqual(PlaceStore().path, Path(directory) / 'iphone-gps' / 'places.sqlite3')
            self.assertEqual(list(Path(directory).iterdir()), [])
        for local_app_data in ('', 'relative/path'):
            with patch('iphone_gps.host.paths.sys', SimpleNamespace(platform='win32')), \
                 patch.dict(os.environ, {'LOCALAPPDATA': local_app_data}):
                self.assertEqual(user_data_directory(), Path.home() / 'AppData/Local/iphone-gps')

    def test_host_messages_match_selected_platform(self):
        with patch('iphone_gps.host.environment.sys', SimpleNamespace(platform='win32')):
            self.assertIn('Apple Mobile Device Service', usb_hint())
            self.assertIn('Scripts\\python.exe', tunnel_hint())
            self.assertIn('管理员 PowerShell', tunnel_hint())
            self.assertNotIn('sudo', tunnel_hint())
        with patch('iphone_gps.host.environment.sys', SimpleNamespace(platform='linux')):
            self.assertIn('usbmuxd', usb_hint())
            self.assertIn('uv run gps tunnel', tunnel_hint())

    def test_cli_restores_signal_handlers(self):
        original = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gps_main(['--dry-run', '1', '2']), 0)
        self.assertEqual(original, {sig: signal.getsignal(sig) for sig in original})

    def test_process_exit_releases_device_lock(self):
        # Runs against flock on Linux and the native CRT lock on Windows CI.
        root = Path(__file__).resolve().parents[1]
        udid = f'crash-lock-{os.getpid()}'
        env = dict(os.environ, PYTHONPATH=str(root / 'src'), PYTHONUTF8='1')
        code = ("import sys; from iphone_gps.host.locking import DeviceLock; "
                f"lock=DeviceLock({udid!r}); lock.acquire(); "
                "print('locked', flush=True); sys.stdin.read(1)")
        process = subprocess.Popen([sys.executable, '-u', '-c', code], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                   text=True, encoding='utf-8')
        line = queue.Queue()
        reader = threading.Thread(target=lambda: line.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            self.assertEqual(line.get(timeout=5).strip(), 'locked')
            reader.join(timeout=1)
            process.kill()
            process.communicate(timeout=5)
            lock = DeviceLock(udid)
            lock.acquire()
            lock.release()
            lock.release()
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()
            reader.join(timeout=1)
