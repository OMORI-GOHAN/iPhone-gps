from pathlib import Path
from importlib.util import find_spec
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
datas, binaries, hiddenimports = collect_all('pymobiledevice3')
datas += copy_metadata('pymobiledevice3', recursive=True)
datas += copy_metadata('iphone-gps')
pytun = Path(find_spec('pytun_pmd3').origin).parent
binaries += [(str(pytun / 'wintun/bin/amd64/wintun.dll'), 'pytun_pmd3/wintun/bin/amd64')]
datas += [(str(pytun / 'wintun/LICENSE.txt'), 'pytun_pmd3/wintun')]

a = Analysis([str(root / 'packaging' / 'windows_entry.py')],
             pathex=[str(root / 'src')], datas=datas, binaries=binaries,
             hiddenimports=hiddenimports + ['win32com.shell.shell', 'win32com.shell.shellcon'],
             excludes=['IPython', 'jedi', 'matplotlib', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='iphone-gps',
          console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='iphone-gps', upx=False)
