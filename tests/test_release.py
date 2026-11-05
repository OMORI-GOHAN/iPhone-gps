"""Prevent the release helper from publishing or replacing a public release."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_release', root / 'packaging/prepare_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_missing_file_fails_before_api_access(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(release, 'gh') as gh:
            with self.assertRaisesRegex(ValueError, 'Missing release file'):
                release.verify_files(Path(directory), '0.1.0')
            gh.assert_not_called()

    def test_public_release_is_never_edited_or_replaced(self):
        with patch.object(release, 'verify_files', return_value=[]), \
             patch.object(release, 'gh', return_value=json.dumps([{'tag_name': 'v0.1.0', 'draft': False}])) as gh, \
             patch('sys.argv', ['prepare_release', '--repo', 'owner/repo', '--commit', 'source-sha', '--folder', 'dist']):
            with self.assertRaisesRegex(ValueError, 'already public'):
                release.main()
        self.assertEqual(gh.call_count, 1)
        self.assertEqual(gh.call_args.args[0], 'api')

    def test_draft_upload_must_match_commit_and_complete_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'artifact.zip'
            artifact.write_bytes(b'checked artifact')
            for target in ('source-sha', 'wrong-sha'):
                result = {'isDraft': True, 'targetCommitish': target, 'url': 'https://example.test/draft',
                          'assets': [{'name': artifact.name, 'size': artifact.stat().st_size, 'state': 'uploaded'}]}
                responses = [json.dumps([{'tag_name': 'v0.1.0', 'draft': True}]), '', '', json.dumps(result)]
                with patch.object(release, 'verify_files', return_value=[artifact]), \
                     patch.object(release, 'gh', side_effect=responses) as gh, \
                     patch('sys.argv', ['prepare_release', '--repo', 'owner/repo', '--commit', 'source-sha', '--folder', directory]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    if target == 'source-sha':
                        release.main()
                    else:
                        with self.assertRaisesRegex(ValueError, 'no longer matches'):
                            release.main()
                self.assertIn('--draft', gh.call_args_list[1].args)
