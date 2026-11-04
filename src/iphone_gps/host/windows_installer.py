"""Explicit installation of Apple's device support, fetched from Apple at runtime."""

import base64
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

from ..core.errors import GpsError
from .paths import user_data_directory

APPLE_URL = 'https://www.apple.com/itunes/download/win64'
MSI_NAME = 'AppleMobileDeviceSupport64.msi'
MAX_DOWNLOAD = 512 * 1024 * 1024


def system_tool(name):
    return str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / name)


def powershell(script):
    # A PowerShell 7 parent may export incompatible modules to Windows PowerShell.
    script = "$env:PSModulePath = Join-Path $PSHOME 'Modules'; " + script
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return system_tool('WindowsPowerShell/v1.0/powershell.exe'), [
        '-NoLogo', '-NoProfile', '-EncodedCommand', encoded]


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def service_status():
    import psutil
    try:
        return psutil.win_service_get('Apple Mobile Device Service').status()
    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied as exc:
        raise GpsError('无法检查 Apple 设备服务权限，请在管理员 PowerShell 中重试') from exc


class AppleRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not (parsed.hostname == 'apple.com' or parsed.hostname.endswith('.apple.com'))
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise GpsError('苹果下载地址发生变化，已停止；请从苹果官网手动获取设备组件')


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise GpsError('已取消苹果组件准备，未启动安装')


def download_installer(destination, cancel=None):
    print('正在从苹果官网下载设备支持安装包（约 200 MB）……', flush=True)
    opener = urllib.request.build_opener(AppleRedirects())
    deadline = time.monotonic() + 900
    try:
        with opener.open(APPLE_URL, timeout=20) as response, destination.open('wb') as output:
            check_url(response.geturl())
            expected = int(response.headers.get('Content-Length', 0))
            received = reported = 0
            while chunk := response.read(1024 * 1024):
                check_cancel(cancel)
                received += len(chunk)
                if received > MAX_DOWNLOAD or time.monotonic() > deadline:
                    raise GpsError('下载超时或文件大小异常，请检查网络后重试')
                output.write(chunk)
                if received - reported >= 20 * 1024 * 1024:
                    print(f'已下载 {received // (1024 * 1024)} MB', flush=True)
                    reported = received
            if not received or (expected and received != expected):
                raise GpsError('苹果安装包下载不完整，请重试')
    except GpsError:
        raise
    except (OSError, ValueError) as exc:
        # Windows curl uses the system TLS backend; some networks reject Python TLS.
        print('正在尝试 Windows 原生下载方式……', flush=True)
        download_native(destination, cancel)


def download_native(destination, cancel=None):
    arguments = [system_tool('curl.exe'), '--location', '--fail', '--silent', '--show-error',
                 '--proto', '=https', '--proto-redir', '=https', '--max-redirs', '5',
                 '--connect-timeout', '20', '--max-time', '900', '--max-filesize', str(MAX_DOWNLOAD),
                 '--speed-limit', '1024', '--speed-time', '30', '--retry', '1', '--retry-delay', '1',
                 '--output', str(destination), '--write-out', '%{url_effective}', APPLE_URL]
    try:
        with subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
            try:
                reported = 0
                while True:
                    check_cancel(cancel)
                    try:
                        stdout, stderr = process.communicate(timeout=1)
                        break
                    except subprocess.TimeoutExpired:
                        received = destination.stat().st_size if destination.exists() else 0
                        if received - reported >= 20 * 1024 * 1024:
                            print(f'已下载 {received // (1024 * 1024)} MB', flush=True)
                            reported = received
                if process.returncode:
                    raise GpsError('无法从苹果官网下载，请检查网络连接、代理和磁盘空间后重试')
                check_url(stdout.decode('utf-8').strip())
                if not destination.is_file() or not 0 < destination.stat().st_size <= MAX_DOWNLOAD:
                    raise GpsError('苹果安装包下载不完整或大小异常')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    except OSError as exc:
        raise GpsError('无法运行 Windows 下载器，请检查系统组件或从苹果官网手动安装') from exc


def verify_apple_signature(path):
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$sig=Get-AuthenticodeSignature -LiteralPath {literal(path)}; "
        "if ($sig.Status -ne 'Valid' -or $null -eq $sig.SignerCertificate "
        "-or $sig.SignerCertificate.GetNameInfo(0, $false) -ne 'Apple Inc.' "
        r"-or $sig.SignerCertificate.Subject -notmatch '(^|,\s*)O=Apple Inc\.(,|$)') { exit 1 }"
    )
    executable, args = powershell(script)
    try:
        result = subprocess.run([executable, *args], capture_output=True, timeout=90,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GpsError('无法完成苹果数字签名校验，已停止安装，请检查网络和系统证书') from exc
    if result.returncode:
        raise GpsError('文件未通过苹果数字签名校验，已停止安装')


def extract_support(source, directory):
    """Only extract the selected MSI from the signed self-extracting CAB."""
    data = source.read_bytes()
    offset = data.find(b'MSCF')
    if offset < 0 or offset + 36 > len(data):
        raise GpsError('苹果安装包格式已变化，未找到设备支持组件')
    size = struct.unpack_from('<I', data, offset + 8)[0]
    if size < 36 or offset + size > len(data):
        raise GpsError('苹果安装包中的组件数据不完整')
    cabinet = directory / 'support.cab'
    cabinet.write_bytes(data[offset:offset + size])
    try:
        subprocess.run([system_tool('expand.exe'), str(cabinet), f'-F:{MSI_NAME}', str(directory)],
                       check=True, capture_output=True, timeout=120,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError) as exc:
        raise GpsError('无法提取 Apple 设备支持组件，请检查安装包格式及磁盘空间') from exc
    msi = directory / MSI_NAME
    if not msi.is_file() or not msi.stat().st_size:
        raise GpsError('苹果安装包不再包含预期的设备支持组件')
    return msi


def run_elevated(executable, arguments):
    import pythoncom
    pythoncom.CoInitialize()
    try:
        return _run_elevated(executable, arguments)
    finally:
        pythoncom.CoUninitialize()


def _run_elevated(executable, arguments):
    from win32com.shell import shell, shellcon
    import win32api
    import win32event
    import win32process
    try:
        result = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
                                     lpVerb='runas', lpFile=executable,
                                     lpParameters=subprocess.list2cmdline(arguments), nShow=1)
    except Exception as exc:
        raise GpsError('安装未启动；请允许 Windows 管理员权限提示后重试') from exc
    handle = result['hProcess']
    try:
        while True:
            try:
                if win32event.WaitForSingleObject(handle, 200) == win32event.WAIT_OBJECT_0:
                    return win32process.GetExitCodeProcess(handle)
            except KeyboardInterrupt:
                print('请在苹果安装窗口中完成或取消安装。', flush=True)
    finally:
        win32api.CloseHandle(handle)


def install_components(cancel=None):
    try:
        return _install_components(cancel)
    except GpsError:
        raise
    except OSError as exc:
        raise GpsError('无法准备设备组件，请检查临时目录、用户数据目录权限和磁盘空间') from exc


def _install_components(cancel=None):
    check_cancel(cancel)
    status = service_status()
    if status == 'running':
        print('Apple 设备服务已运行，直接复用，无需下载安装。')
        return 0
    if status is not None:
        print('已有 Apple 设备组件，正在请求启动服务……', flush=True)
        executable, args = powershell(
            "$ErrorActionPreference='Stop'; Start-Service -Name 'Apple Mobile Device Service'")
        check_cancel(cancel)
        if run_elevated(executable, args) != 0 or service_status() != 'running':
            raise GpsError('Apple 设备服务未能启动，请检查现有安装或在 Windows 应用设置中修复组件')
        print('Apple 设备服务已启动。')
        return 0
    log_dir = user_data_directory() / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f'apple-device-install-{time.time_ns()}.log'
    with tempfile.TemporaryDirectory(prefix='iphone-gps-apple-') as temporary:
        directory = Path(temporary)
        source = directory / 'iTunes64Setup.exe'
        download_installer(source, cancel)
        check_cancel(cancel)
        print('正在校验苹果安装包并提取设备支持组件……', flush=True)
        verify_apple_signature(source)
        msi = extract_support(source, directory)
        verify_apple_signature(msi)
        check_cancel(cancel)
        print('校验通过。请确认 Windows 权限提示，并在苹果安装窗口中完成安装。', flush=True)
        code = run_elevated(system_tool('msiexec.exe'),
                            ['/i', str(msi), '/norestart', '/L*v', str(log)])
        if code == 1602:
            print('已取消苹果组件安装。')
            return 1
        if code not in (0, 3010):
            raise GpsError(f'苹果组件安装失败（代码 {code}），安装日志：{log}')
        if code == 3010:
            print('苹果组件安装完成，需要重启 Windows 后再连接手机。')
            return 0
        for _ in range(20):
            if service_status() == 'running':
                print('苹果组件安装完成，服务已运行。请连接并解锁手机，再运行 devices 检查。')
                return 0
            time.sleep(.5)
        raise GpsError(f'安装结束但设备服务尚未运行，请检查安装日志：{log}')
