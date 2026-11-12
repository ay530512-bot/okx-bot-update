"""Guarded migration of the known watch-only host-v2. Never migrate live trading."""
import hashlib
import json
import errno
import os
from pathlib import Path
import socket
import time


def process_token(pid):
    """Own-child PID reuse guard. Do not treat unreadable /proc as stopped."""
    try:
        text = (Path('/proc')/str(pid)/'stat').read_text()
    except FileNotFoundError:
        return None
    fields = text.rsplit(') ', 1)[1].split()
    if fields[0] == 'Z':
        return None
    return fields[19]


def child_pids(pid):
    path = Path('/proc')/str(pid)/'task'/str(pid)/'children'
    try:
        return [int(value) for value in path.read_text().split()]
    except FileNotFoundError:
        # Some Android kernels omit CONFIG_CHECKPOINT_RESTORE's children file.
        result = []
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                if proc.stat().st_uid != os.getuid():
                    continue
                fields = (proc/'stat').read_text().rsplit(') ', 1)[1].split()
                if int(fields[1]) == pid:
                    result.append(int(proc.name))
            except FileNotFoundError:
                continue  # Child exited during snapshot.
        return result


def verify_legacy(root):
    manifest = json.loads((Path(__file__).parent/'phone_migration_sources.json').read_text())['host-v2']
    folder = root/'host-v2'
    if folder.is_symlink():
        raise ValueError('기존 실행기 폴더 링크 오류')
    for name, expected in manifest.items():
        p = folder/name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('기존 실행기 버전이 다릅니다. 실행 중인 파일은 변경하지 않았습니다.')
    return folder


def transport_released(root):
    """Probe only the local listener; never delete a socket or login state."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        code = probe.connect_ex(str(root/'remote-private'/'ts.sock'))
    if code == 0:
        return False
    if code in (errno.ENOENT, errno.ECONNREFUSED):
        return True
    raise ValueError('이전 연결 프로세스 종료 여부를 확인하지 못했습니다. 상태 파일은 유지합니다.')


def prepare_watch_upgrade(root):
    import phone_service as service
    from phone_host import read_json
    from phone_account import save_json
    if (root/'phone_owner.json').exists() or (root/'phone_owner.json').is_symlink():
        raise ValueError('이미 폰 실거래 전환 기록이 있습니다. 운용 중인 엔진은 교체하지 않습니다.')
    if not service.running(root):
        if service.running(root, 'phone_host.lock'):
            raise ValueError('기존 폰 조회 화면을 CTRL 다음 C로 종료한 후 다시 실행하세요.')
        if not transport_released(root):
            raise ValueError('기존 원격 연결이 아직 실행 중입니다. 중복 시작하지 않았습니다.')
        return
    row = read_json(root/'phone_service_status.json')
    if row.get('service_version') == service.VERSION:
        return  # Idempotent setup resumes the already installed v3.
    cfg = service.config(root)
    if cfg.get('mode') != 'watch' or row.get('mode') != 'watch' or row.get('state') != 'running':
        raise ValueError('조회 모드 실행기만 교체할 수 있습니다.')
    if not isinstance(row.get('observed_at'), (int, float)) or not 0 <= time.time()-row['observed_at'] < 30:
        raise ValueError('기존 실행기 상태가 오래되었습니다. 자동 교체하지 않았습니다.')
    folder = verify_legacy(root)
    pid = row.get('pid')
    if type(pid) is not int or pid < 2:
        raise ValueError('기존 실행기 프로세스 확인 실패')
    proc = Path('/proc')/str(pid)
    argv = (proc/'cmdline').read_bytes().split(b'\0')
    if str(folder/'phone_service.py').encode() not in argv or b'--supervise' not in argv:
        raise ValueError('기존 조회 실행기와 프로세스가 일치하지 않습니다.')
    children = child_pids(pid)
    tokens = {child: process_token(child) for child in children}
    print('기존 폰 조회 실행기를 정상 종료하고 Android용 연결로 전환합니다. PC 매매는 유지됩니다.', flush=True)
    service.request_stop(root, wait=25)
    deadline = time.monotonic()+12
    while (any(token is not None and process_token(child) == token for child, token in tokens.items())
           or not transport_released(root)):
        if time.monotonic() >= deadline:
            raise ValueError('이전 연결 프로세스 종료를 기다리는 중입니다. 강제 종료하거나 상태 파일을 지우지 마세요.')
        time.sleep(.25)
    save_json(root/'phone_transport_migration.json', dict(from_version='host-v2', to_version='host-v3',
              previous_mode='watch', state_files_preserved=True, completed_at=time.time()))
