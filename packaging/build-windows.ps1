$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw '请先执行 uv sync --locked --extra device。'
    }
    & $python -c "from iphone_gps.backends.pymobiledevice import check_dependency; check_dependency(); import PyInstaller"
    if ($LASTEXITCODE -ne 0) { throw '请先安装 packaging/requirements-windows.txt 中的构建依赖。' }
    & $python -m PyInstaller --noconfirm --distpath dist --workpath build packaging/windows.spec
    if ($LASTEXITCODE -ne 0) { throw 'Windows 构建失败。' }
    Copy-Item -LiteralPath packaging/WINDOWS_README.txt -Destination dist/iphone-gps/使用说明.txt
    & .\dist\iphone-gps\iphone-gps.exe --version
    if ($LASTEXITCODE -ne 0) { throw '程序启动验证失败。' }
    & .\dist\iphone-gps\iphone-gps.exe gps developer-mode --help
    if ($LASTEXITCODE -ne 0) { throw '开发者模式命令验证失败。' }
    & .\dist\iphone-gps\iphone-gps.exe setup
    if ($LASTEXITCODE -ne 0) { throw '内置隧道及设备组件加载失败。' }
    & .\dist\iphone-gps\iphone-gps.exe gps set --dry-run --coord-system gcj02 28.169004 112.945261
    if ($LASTEXITCODE -ne 0) { throw '离线定位预演失败。' }
    & $python -c "import shutil; shutil.make_archive('dist/iphone-gps-windows-x64', 'zip', 'dist', 'iphone-gps')"
    if ($LASTEXITCODE -ne 0) { throw 'Windows 压缩包生成失败。' }
    & $python -c "import zipfile; z=zipfile.ZipFile('dist/iphone-gps-windows-x64.zip'); assert 'iphone-gps/iphone-gps.exe' in z.namelist(); assert 'iphone-gps/使用说明.txt' in z.namelist(); assert z.testzip() is None"
    if ($LASTEXITCODE -ne 0) { throw 'Windows 压缩包验证失败。' }
    Write-Host '已生成 dist/iphone-gps-windows-x64.zip'
} finally {
    Pop-Location
}
