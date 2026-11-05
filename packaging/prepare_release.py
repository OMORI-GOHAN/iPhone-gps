"""Verify built files and attach them to a draft; never publish a release."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tomllib
import zipfile


def verify_files(folder: Path, version: str) -> list[Path]:
    paths = [folder / 'iphone-gps-windows-x64.zip',
             folder / f'iphone_gps-{version}-py3-none-any.whl',
             folder / f'iphone_gps-{version}.tar.gz']
    for path in paths:
        if not path.is_file():
            raise ValueError(f'Missing release file: {path.name}')
    with zipfile.ZipFile(paths[0]) as archive:
        names = set(archive.namelist())
        if not {'iphone-gps/iphone-gps.exe', 'iphone-gps/使用说明.txt'} <= names:
            raise ValueError('Windows executable or instructions missing')
        if any('\\' in name for name in names) or archive.testzip() is not None:
            raise ValueError('Invalid Windows ZIP structure or CRC')
    with zipfile.ZipFile(paths[1]) as archive:
        metadata = archive.read(f'iphone_gps-{version}.dist-info/METADATA').decode()
        if f'Version: {version}\n' not in metadata:
            raise ValueError('Wheel version mismatch')
    with tarfile.open(paths[2]) as archive:
        if f'iphone_gps-{version}/uv.lock' not in archive.getnames():
            raise ValueError('Source archive does not contain the dependency lock')
    sums = []
    for path in sorted(paths):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        sums.append(f'{digest}  {path.name}')
    checksum = folder / 'SHA256SUMS.txt'
    checksum.write_text('\n'.join(sums) + '\n', encoding='utf-8')
    return [*paths, checksum]


def gh(*args):
    return subprocess.run(['gh', *args], check=True, capture_output=True, text=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    with Path('pyproject.toml').open('rb') as stream:
        version = tomllib.load(stream)['project']['version']
    files = verify_files(args.folder, version)
    tag = f'v{version}'
    # List only; if the API fails, abort rather than assuming a missing release.
    releases = json.loads(gh('api', f'repos/{args.repo}/releases?per_page=100'))
    existing = next((release for release in releases if release['tag_name'] == tag), None)
    if existing is not None:
        if not existing['draft']:
            raise ValueError(f'{tag} is already public; refusing to replace release files')
        gh('release', 'edit', tag, '--repo', args.repo, '--draft', '--target', args.commit)
    else:
        gh('release', 'create', tag, '--repo', args.repo, '--draft', '--target', args.commit,
           '--title', f'iPhone GPS {tag}', '--notes-file', 'packaging/RELEASE_NOTES.md')
    gh('release', 'upload', tag, '--repo', args.repo, '--clobber', *map(str, files))
    result = json.loads(gh('release', 'view', tag, '--repo', args.repo,
                           '--json', 'isDraft,targetCommitish,assets,url'))
    uploaded = {asset['name']: asset for asset in result['assets']}
    if not result['isDraft'] or result['targetCommitish'] != args.commit:
        raise ValueError('Release draft no longer matches the build commit')
    for path in files:
        asset = uploaded.get(path.name)
        if asset is None or asset['size'] != path.stat().st_size or asset['state'] != 'uploaded':
            raise ValueError(f'Incomplete release upload: {path.name}')
    print(result['url'])


if __name__ == '__main__':
    main()
