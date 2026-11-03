import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from iphone_gps.api import Coordinate, PlaceError, PlaceStore
from iphone_gps.cli import gps_main, main
from test_session import Backend


class PlaceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {'XDG_DATA_HOME': self.directory.name,
                                                 'LOCALAPPDATA': self.directory.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.store = PlaceStore()

    def call(self, args, *, full=False):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(['gps', *args]) if full else gps_main(args)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_store_persists_original_system_across_processes(self):
        self.store.save('教学楼', 28.169004, 112.945261, coord_system='gcj02')
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(root / 'src'), PYTHONUTF8='1')
        process = subprocess.run([sys.executable, '-c',
            "from iphone_gps.api import PlaceStore; p=PlaceStore().get('教学楼'); "
            "assert p.latitude==28.169004 and p.longitude==112.945261; "
            "assert p.coord_system=='gcj02'; print(p.coordinate.latitude)"],
            env=env, cwd=self.directory.name, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn('28.172508', process.stdout)

    def test_duplicate_requires_explicit_replace_and_invalid_save_preserves_old(self):
        original = self.store.save('东京', 35.71488401550224, 139.7966438955983)
        with self.assertRaisesRegex(PlaceError, '--replace'):
            self.store.save('东京', 1, 2)
        with self.assertRaises(PlaceError):
            self.store.save('东京', float('nan'), 2, replace=True)
        self.assertEqual(self.store.get('东京'), original)
        replacement = self.store.save('东京', 35, 139, replace=True)
        self.assertEqual(PlaceStore().get('东京'), replacement)

    def test_names_spaces_quotes_and_negative_coordinates(self):
        for name in ('学校 北门', "门口' OR 1=1 --", 'status'):
            self.store.save(name, -28, -112)
            self.assertEqual(self.store.get(name).coordinate, Coordinate(-28, -112))
        self.assertEqual(len(self.store.list()), 3)
        self.store.delete("门口' OR 1=1 --")
        self.assertEqual(len(self.store.list()), 2)
        for name in ('', '   ', '28', 'nan', '1e3', 'a\nb', 'a' * 101):
            with self.assertRaises(PlaceError):
                self.store.save(name, 1, 2)

    def test_read_missing_does_not_create_storage(self):
        self.assertEqual(self.store.list(), [])
        with self.assertRaises(PlaceError):
            self.store.get('未保存')
        with self.assertRaises(PlaceError):
            self.store.delete('未保存')
        self.assertFalse(self.store.path.exists())
        self.assertFalse(self.store.path.parent.exists())

    def test_corrupt_file_is_reported_and_preserved(self):
        self.store.path.parent.mkdir()
        content = b'this is not a sqlite database'
        self.store.path.write_bytes(content)
        for action in (self.store.list, lambda: self.store.save('学校', 1, 2)):
            with self.assertRaisesRegex(PlaceError, '损坏'):
                action()
            self.assertEqual(self.store.path.read_bytes(), content)

    def test_management_and_dry_run_are_offline(self):
        with patch('iphone_gps.features.gps.session.default_backend', side_effect=AssertionError('device accessed')):
            status, output, error = self.call(['place', 'save', '学校 北门', '--coord-system', 'gcj02',
                                               '28.167440144763262', '112.96048234383075'])
            self.assertEqual(status, 0, error)
            self.assertIn('已保存', output)
            status, output, _ = self.call(['place', 'list'], full=True)
            self.assertEqual(status, 0)
            self.assertIn('学校 北门', output)
            self.assertIn('GCJ02', output)
            status, output, _ = self.call(['place', 'show', '学校 北门'])
            self.assertEqual(status, 0)
            self.assertIn('28.170914691', output)
            status, output, error = self.call(['--dry-run', '学校 北门'])
            self.assertEqual(status, 0, error)
            self.assertIn('28.170914691', output)
            self.assertIn('112.954996509', output)
            self.assertIn('未连接手机', output)
            status, _, error = self.call(['place', 'delete', '学校 北门'])
            self.assertEqual(status, 0, error)
            status, _, error = self.call(['学校 北门'])
            self.assertEqual(status, 1)
            self.assertIn('未保存地点', error)

    def test_named_location_submits_correct_coordinate_once(self):
        self.store.save('教学楼', 28.169004, 112.945261, coord_system='gcj02')
        self.store.save('status', 35.71488401550224, 139.7966438955983)
        for args, expected in ((['教学楼'], (28.172508457, 112.939813427)),
                               (['set', 'status'], (35.71488401550224, 139.7966438955983))):
            backend = Backend()
            with patch('iphone_gps.features.gps.session.default_backend', return_value=backend):
                status, _, error = self.call([*args, '--duration', '.001'])
            self.assertEqual(status, 0, error)
            self.assertEqual(len(backend.connection.writes), 1)
            target = backend.connection.writes[0]
            self.assertAlmostEqual(target.latitude, expected[0], places=8)
            self.assertAlmostEqual(target.longitude, expected[1], places=8)
            self.assertEqual(backend.connection.closes, 1)
        self.assertEqual(self.store.get('教学楼').latitude, 28.169004)

    def test_invalid_combinations_fail_without_device_access(self):
        self.store.save('学校', 28, 112)
        with patch('iphone_gps.features.gps.session.default_backend', side_effect=AssertionError('device accessed')):
            for args in (['学校', '112'], ['28'], ['学校', '--coord-system', 'gcj02']):
                status, _, error = self.call(args)
                self.assertEqual(status, 1)
                self.assertTrue(error)

    def test_explicit_update_and_delete_do_not_affect_other_places(self):
        self.call(['place', 'save', '东京', '35', '139'])
        self.call(['place', 'save', '学校', '28', '112'])
        status, _, _ = self.call(['place', 'save', '学校', '29', '113'])
        self.assertEqual(status, 1)
        self.assertEqual(self.store.get('学校').latitude, 28)
        status, _, error = self.call(['place', 'save', '学校', '--replace', '29', '113'])
        self.assertEqual(status, 0, error)
        self.assertEqual(self.store.get('学校').latitude, 29)
        self.call(['place', 'delete', '学校'])
        self.assertEqual([p.name for p in self.store.list()], ['东京'])
