import contextlib
import io
import unittest
from unittest.mock import patch

from iphone_gps.api import Coordinate, to_wgs84
from iphone_gps.cli import gps_main, main
from test_session import Backend


class ConversionTests(unittest.TestCase):
    def test_verified_changsha_points(self):
        # These WGS84 results were manually tested on the phone against the
        # corresponding source-map landmarks before CLI integration.
        cases = (
            ((28.169004, 112.945261), (28.172508, 112.939813)),
            ((28.167440144763262, 112.96048234383075), (28.170914691, 112.954996509)),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                actual = to_wgs84(*source, source='gcj02')
                self.assertAlmostEqual(actual.latitude, expected[0], places=6)
                self.assertAlmostEqual(actual.longitude, expected[1], places=6)

    def test_default_wgs84_unchanged_including_outside_gcj_bounds(self):
        for point in ((28.167440144763262, 112.96048234383075), (-90, -180), (0, 0), (90, 180)):
            self.assertEqual(to_wgs84(*point), Coordinate(*point))

    def test_invalid_input_and_unsupported_source(self):
        for latitude, longitude, source in (
            (float('nan'), 112, 'gcj02'), (28, float('inf'), 'gcj02'),
            (91, 112, 'gcj02'), (28, 181, 'gcj02'),
            (0, 0, 'gcj02'), (-28, 112, 'gcj02'),
            (28, 112, 'bd09'), (28, 112, 'guess'),
        ):
            with self.subTest(latitude=latitude, longitude=longitude, source=source):
                with self.assertRaises(ValueError):
                    to_wgs84(latitude, longitude, source=source)

    def test_dry_run_shows_input_and_output_without_connecting(self):
        for run, prefix in ((gps_main, []), (main, ['gps', 'set'])):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), patch(
                'iphone_gps.features.gps.session.default_backend', side_effect=AssertionError('device accessed')
            ):
                status = run(prefix + ['--coord-system', 'gcj02', '--dry-run',
                                       '28.167440144763262', '112.96048234383075'])
            self.assertEqual(status, 0)
            output = stdout.getvalue()
            self.assertIn('输入（GCJ02）', output)
            self.assertIn('WGS84', output)
            self.assertIn('28.170914691', output)
            self.assertIn('112.954996509', output)
            self.assertIn('未连接手机', output)

    def test_cli_submits_converted_value_and_cleans_session(self):
        for system in ('wgs84', 'gcj02'):
            with self.subTest(system=system):
                backend = Backend()
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout), patch(
                    'iphone_gps.features.gps.session.default_backend', return_value=backend
                ):
                    status = gps_main(['--coord-system', system, '--duration', '.001',
                                       '28.167440144763262', '112.96048234383075'])
                self.assertEqual(status, 0)
                self.assertEqual(len(backend.connection.writes), 1)
                target = backend.connection.writes[0]
                if system == 'gcj02':
                    self.assertAlmostEqual(target.latitude, 28.170914691, places=8)
                    self.assertAlmostEqual(target.longitude, 112.954996509, places=8)
                else:
                    self.assertEqual(target, Coordinate(28.167440144763262, 112.96048234383075))
                self.assertEqual(backend.connection.closes, 1)
                self.assertEqual(backend.connection.clears, 1)

    def test_out_of_scope_conversion_fails_before_backend_access(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), patch(
            'iphone_gps.features.gps.session.default_backend', side_effect=AssertionError('device accessed')
        ):
            status = gps_main(['--coord-system', 'gcj02', '--', '-28', '-112'])
        self.assertEqual(status, 1)
        self.assertIn('超出当前支持的近似范围', stderr.getvalue())
