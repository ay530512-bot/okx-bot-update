"""Private transport; native Android ARM64 build avoids Linux-only syscalls."""
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = '1.104.6'
PACKAGES = {
    'arm64': {
        'archive': '228b6c3a12192434ab1a7f55049222d84360a52c39f34a5eb73725fde140adfb',
        'tailscale': 'ca27b5c24dfa6bbe63385ff58049bdadea74364dc01b4d4b2873bd16f3256d06',
        'tailscaled': '1176e405d33d93f45fc2848bf0367017c3c86b6754e755677923f30777c13831',
        'folder': 'tailscale-1.104.6-android-arm64-r1',
        'prefix': 'tailscale_1.104.6_android_arm64_r1/',
        'url': 'https://github.com/ay530512-bot/okx-bot-update/releases/download/phone-tailscale-1.104.6-android-arm64-r1/tailscale_1.104.6_android_arm64_r1.tar.gz'},
    'amd64': {
        'archive': '82a85429f733e52fd1a95dedb2c8dd8cd46d6603504e566a56b1779c9a7a4809',
        'tailscale': 'a781895a86932424dce380c8b445c77b8568dd2248a7fed20ba77ce3cb221185',
        'tailscaled': '01106e93593dfe01ba6d8615ba5de40222ce3e54797525cc66ef7795f682c216'},
}


def binary_folder(root, arch=None):
    arch = arch or architecture()
    return root / PACKAGES[arch].get('folder', f'tailscale-{VERSION}-{arch}')


def architecture():
    value = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64', 'amd64': 'amd64'}.get(platform.machine().lower())
    if not value:
        raise ValueError('지원하지 않는 CPU입니다. 다른 실행 파일로 우회하지 마세요.')
    return value


def valid_host(host):
    return isinstance(host, str) and bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.ts\.net:8443', host))


def host_from_status(status):
    if status.get('BackendState') != 'Running':
        raise ValueError('Tailscale 로그인 또는 기기 승인이 아직 완료되지 않았습니다.')
    host = str(status.get('Self', {}).get('DNSName', '')).rstrip('.').lower() + ':8443'
    if not valid_host(host):
        raise ValueError('폰의 Tailscale HTTPS 주소를 확인할 수 없습니다.')
    return host


def verify_serve(data, host):
    if not valid_host(host) or any((data.get('AllowFunnel') or {}).values()):
        raise ValueError('공개 접속 설정은 사용할 수 없습니다.')
    expected_tcp = {'8443': {'HTTPS': True}}
    expected_web = {host: {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8768'}}}}
    if data.get('TCP') != expected_tcp or data.get('Web') != expected_web:
        raise ValueError('원격 연결 대상이 폰 화면과 일치하지 않습니다.')
    if any(data.get(k) for k in ('Services', 'Foreground')):
        raise ValueError('다른 원격 공유 설정이 있습니다.')


def verify_binaries(folder, arch):
    for name in ('tailscale', 'tailscaled'):
        path = folder / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != PACKAGES[arch][name]:
            raise ValueError('원격 연결 파일 검증 실패: ' + name)


def verify_native_runtime(folder, arch):
    if arch != 'arm64':
        return
    try:
        result = subprocess.run([str(folder/'tailscale'), 'version', '--json'],
                                capture_output=True, text=True, timeout=15, check=False)
        version = json.loads(result.stdout)
        if result.returncode or not isinstance(version, dict) or version.get('short') != VERSION:
            raise ValueError()
        result = subprocess.run([str(folder/'tailscaled'), '--version'],
                                capture_output=True, text=True, timeout=15, check=False)
        if result.returncode or '1.104.6-phone-android-r1' not in result.stdout:
            raise ValueError()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ValueError('Android용 연결 파일의 실행 확인에 실패했습니다. 기존 조회 실행기는 유지합니다.') from None


def unpack(raw, target, arch):
    if hashlib.sha256(raw).hexdigest() != PACKAGES[arch]['archive']:
        raise ValueError('Tailscale 다운로드 해시 불일치')
    parts = {}
    prefix = PACKAGES[arch].get('prefix', f'tailscale_{VERSION}_{arch}/')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tar:
        for name in ('tailscale', 'tailscaled'):
            entries = [m for m in tar.getmembers() if m.name == prefix + name]
            if len(entries) != 1 or not entries[0].isfile() or entries[0].size > 160*1024*1024:
                raise ValueError('원격 연결 파일 형식 오류')
            data = tar.extractfile(entries[0]).read()
            if hashlib.sha256(data).hexdigest() != PACKAGES[arch][name]:
                raise ValueError('원격 연결 실행 파일 해시 불일치')
            parts[name] = data
    # Extract only the two individually verified regular files, never tar paths.
    for name, data in parts.items():
        path = target / name
        if path.exists() or path.is_symlink():
            raise ValueError('설치 대상에 기존 파일이 있습니다.')
        path.write_bytes(data)
        path.chmod(0o700)


def install(root):
    arch = architecture()
    target = binary_folder(root, arch)
    if target.is_symlink():
        raise ValueError('원격 연결 폴더 링크는 사용할 수 없습니다.')
    if target.exists():
        verify_binaries(target, arch)
        verify_native_runtime(target, arch)
        return target
    url = PACKAGES[arch].get('url', f'https://pkgs.tailscale.com/stable/tailscale_{VERSION}_{arch}.tgz')
    print('원격 연결 파일 다운로드·무결성 확인 중 …', flush=True)
    with urllib.request.urlopen(url, timeout=45) as response:
        raw = response.read(80*1024*1024 + 1)
    if len(raw) > 80*1024*1024:
        raise ValueError('다운로드 크기 초과')
    import shutil
    temp = Path(tempfile.mkdtemp(prefix='.tailscale-', dir=root))
    try:
        unpack(raw, temp, arch)
        verify_native_runtime(temp, arch)
        os.rename(temp, target)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return target


def paths(root):
    folder = binary_folder(root)
    state = root / 'remote-private'
    if state.is_symlink():
        raise ValueError('원격 설정 폴더 링크는 사용할 수 없습니다.')
    state.mkdir(mode=0o700, exist_ok=True)
    state.chmod(0o700)
    return folder, state


def cli(root, *args, capture=True, timeout=20):
    folder, state = paths(root)
    command = [str(folder/'tailscale'), '--socket='+str(state/'ts.sock'), *args]
    return subprocess.run(command, capture_output=capture, text=True, timeout=timeout, check=False)


def status(root):
    result = cli(root, 'status', '--json')
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError('원격 연결 서비스 준비 중입니다. 같은 설치 명령을 다시 실행하면 이어집니다.')


def daemon_command(root):
    folder, state = paths(root)
    verify_binaries(folder, architecture())
    return [str(folder/'tailscaled'), '--tun=userspace-networking',
            '--socket='+str(state/'ts.sock'), '--state='+str(state/'tailscaled.state'),
            '--statedir='+str(state), '--port=0', '--no-logs-no-support']


def configure(root):
    current = status(root)
    if current.get('BackendState') != 'Running':
        print('\n아래 로그인 링크를 열어 아이폰 Tailscale과 같은 계정으로 연결하세요.', flush=True)
        result = cli(root, 'up', '--accept-dns=false', '--accept-routes=false',
                     '--hostname=okx-fold-home', '--timeout=3m', capture=False, timeout=190)
        if result.returncode:
            raise ValueError('연결 명령이 중단되었습니다. 승인 대기로 단정할 수 없습니다. 종료 기록을 확인해야 합니다.')
    # Never alter OKX internet egress: no exit node, advertised routes, or DNS changes.
    prefs = cli(root, 'debug', 'prefs')
    try:
        cfg = json.loads(prefs.stdout)
    except ValueError:
        raise ValueError('원격 네트워크 설정 확인 실패')
    if cfg.get('ExitNodeID') or cfg.get('ExitNodeIP') or cfg.get('AdvertiseRoutes') or cfg.get('RouteAll') or cfg.get('CorpDNS'):
        raise ValueError('출구 노드/경로/DNS 설정을 확인하세요. 거래 연결은 변경하지 않았습니다.')
    host = host_from_status(status(root))
    before = cli(root, 'serve', 'status', '--json')
    data = json.loads(before.stdout or '{}') or {}
    if any(data.get(k) for k in ('TCP', 'Web', 'AllowFunnel', 'Services', 'Foreground')):
        verify_serve(data, host)
    print('아이폰용 비공개 HTTPS 주소 설정 중 …', flush=True)
    result = cli(root, 'serve', '--bg', '--https=8443', 'http://127.0.0.1:8768', capture=False, timeout=190)
    if result.returncode:
        raise ValueError('HTTPS 설정 대기입니다. 표시된 링크에서 승인 후 같은 설치 명령으로 이어가세요.')
    verify_serve(json.loads(cli(root, 'serve', 'status', '--json').stdout), host)
    from phone_account import save_json
    save_json(root/'phone_remote.json', dict(https_host=host, transport='private-tailscale-serve', public_access=False))
    # Verify that a short successful response is not immediately followed by
    # another daemon crash (the failure observed after browser authentication).
    import time
    for _ in range(3):
        time.sleep(2)
        if host_from_status(status(root)) != host:
            raise ValueError('원격 연결 유지 확인 실패')
    return 'https://' + host
