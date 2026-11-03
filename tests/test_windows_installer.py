import contextlib
import io
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from iphone_gps.host import windows_installer as installer


class WindowsInstallerTests(unittest.TestCase):
    def test_native_fallback_still_rejects_non_apple_destination(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(installer.subprocess, 'Popen') as popen:
            target = Path(directory) / 'download.exe'
            target.write_bytes(b'download')
            process = popen.return_value.__enter__.return_value
            process.communicate.return_value = (b'https://example.com/payload', b'')
            process.returncode = 0
            process.poll.return_value = 0
            with self.assertRaises(installer.GpsError):
                installer.download_native(target)
            args = popen.call_args.args[0]
            self.assertIn('=https', args)
            self.assertNotIn('--insecure', args)

    def test_cancelled_native_download_stops_owned_downloader(self):
        cancel = threading.Event()
        cancel.set()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(installer.subprocess, 'Popen') as popen:
            process = popen.return_value.__enter__.return_value
            process.poll.return_value = None
            with self.assertRaises(installer.GpsError):
                installer.download_native(Path(directory) / 'download.exe', cancel)
            process.terminate.assert_called_once()
            process.communicate.assert_not_called()

    def test_python_tls_failure_uses_native_fallback(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(installer.urllib.request, 'build_opener') as opener, \
             patch.object(installer, 'download_native') as native, \
             contextlib.redirect_stdout(io.StringIO()):
            opener.return_value.open.side_effect = OSError('TLS failure')
            target = Path(directory) / 'download.exe'
            installer.download_installer(target)
            native.assert_called_once_with(target, None)

    def test_partial_download_is_rejected(self):
        response = io.BytesIO(b'partial')
        response.headers = {'Content-Length': '100'}
        response.geturl = lambda: installer.APPLE_URL
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(installer.urllib.request, 'build_opener') as opener, \
             contextlib.redirect_stdout(io.StringIO()), \
             self.assertRaisesRegex(installer.GpsError, '不完整'):
            opener.return_value.open.return_value = response
            installer.download_installer(Path(directory) / 'download.exe')

    def test_reuses_running_service_without_download_or_elevation(self):
        with patch.object(installer, 'service_status', return_value='running'), \
             patch.object(installer, 'download_installer') as download, \
             patch.object(installer, 'run_elevated') as elevated, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.install_components(), 0)
            download.assert_not_called()
            elevated.assert_not_called()

    def test_existing_stopped_service_is_started_without_reinstall(self):
        with patch.object(installer, 'service_status', side_effect=['stopped', 'running']), \
             patch.object(installer, 'download_installer') as download, \
             patch.object(installer, 'run_elevated', return_value=0), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.install_components(), 0)
            download.assert_not_called()

    def test_rejects_non_apple_or_unencrypted_redirects(self):
        for url in ('http://apple.com/file', 'https://apple.com.evil.test/file',
                    'https://example.com/file', 'https://user@apple.com/file'):
            with self.subTest(url=url), self.assertRaises(installer.GpsError):
                installer.check_url(url)
        installer.check_url('https://secure-appldnld.apple.com/file')

    def test_truncated_cabinet_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.exe'
            data = bytearray(b'MSCF' + bytes(32))
            struct.pack_into('<I', data, 8, 100)
            source.write_bytes(data)
            with patch.object(installer.subprocess, 'run') as run, \
                 self.assertRaises(installer.GpsError):
                installer.extract_support(source, root)
            run.assert_not_called()

    def test_bad_signature_never_starts_installer(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(installer, 'service_status', return_value=None), \
             patch.object(installer, 'user_data_directory', return_value=Path(directory)), \
             patch.object(installer, 'download_installer'), \
             patch.object(installer, 'verify_apple_signature', side_effect=installer.GpsError('signature')), \
             patch.object(installer, 'run_elevated') as run, \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(installer.GpsError):
            installer.install_components()
        run.assert_not_called()

    def test_install_outcomes_and_no_forced_reboot(self):
        for code, expected in ((0, 0), (3010, 0), (1602, 1)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory, \
                 patch.object(installer, 'service_status', side_effect=[None, 'running']), \
                 patch.object(installer, 'user_data_directory', return_value=Path(directory)), \
                 patch.object(installer, 'download_installer'), \
                 patch.object(installer, 'verify_apple_signature') as verify, \
                 patch.object(installer, 'extract_support', return_value=Path(directory) / installer.MSI_NAME), \
                 patch.object(installer, 'run_elevated', return_value=code) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(installer.install_components(), expected)
                self.assertEqual(verify.call_count, 2)
                arguments = run.call_args.args[1]
                self.assertIn('/norestart', arguments)
                self.assertNotIn('/quiet', arguments)

    def test_cancel_after_verification_never_opens_install_ui(self):
        cancel = threading.Event()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(installer, 'service_status', return_value=None), \
             patch.object(installer, 'user_data_directory', return_value=Path(directory)), \
             patch.object(installer, 'download_installer'), \
             patch.object(installer, 'verify_apple_signature', side_effect=lambda _: cancel.set()), \
             patch.object(installer, 'extract_support', return_value=Path(directory) / installer.MSI_NAME), \
             patch.object(installer, 'run_elevated') as run, \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(installer.GpsError):
            installer.install_components(cancel)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
