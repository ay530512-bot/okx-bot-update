"""Flat-and-paused upgrade from verified host-v8 to host-v9.

Only allowlisted GETs are made by the upgrader. Never closes positions, cancels
orders, changes strategy/configuration/credentials, or force-kills a process.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from phone_account import atomic_private, readonly_client, save_json, validate_keys
from phone_host import (read_json, verified_installation, verify_owner,
                        verify_restart_journal, identity, finite, remote_host)
from phone_migrate import child_pids, process_token, transport_released
import phone_service as service

HERE = Path(__file__).resolve().parent
OLD = 'host-v8'  # Supported predecessors are pinned separately.
VERSION = 'phone-upgrade-1.1.2'


def require_paused_flat_journal(root):
    row = read_json(root/'runtime-q2x'/'bot_state.json')
    if row.get('version') != 1 or 'owned' not in row:
        raise ValueError('기존 운용 기록 형식을 확인하지 못했습니다.')
    continuity = row.get('entry_continuity732', {})
    if continuity.get('schema') != 1 or continuity.get('requested') is not False:
        raise ValueError('먼저 화면에서 신규 진입 중지를 누른 뒤 다시 실행하세요. 실행기는 변경하지 않았습니다.')
    records = [row.get('owned'), row.get('extra_owned'), *row.get('additional_owned', [])]
    if any(records) or row.get('manual_closes716'):
        raise ValueError('보유 또는 처리 중인 기록이 있어 설치 보류입니다. 기존 보호 관리를 유지합니다.')
    return row


def verify_old(root):
    all_pins = read_json(HERE/'phone_button_old_sources.json')
    boot = Path.home()/'.termux/boot/40-okx-home'
    if boot.is_symlink() or not boot.is_file():
        raise ValueError('기존 실행기 등록을 확인하지 못했습니다.')
    text = boot.read_text()
    matches = [name for name in all_pins if str(root/name/'phone_service.py') in text]
    if len(matches) != 1:
        raise ValueError('지원하는 기존 실행기를 확인하지 못했습니다.')
    folder = root/matches[0]
    pins = all_pins[matches[0]]
    if folder.is_symlink():
        raise ValueError('기존 실행기 폴더 링크 오류')
    for name, expected in pins.items():
        p = folder/name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('대상 host-v8 원본이 다릅니다. 자동 교체하지 않았습니다.')
    for p in folder.rglob('*'):
        relative = p.relative_to(folder)
        if p.is_symlink() or (p.is_file() and '__pycache__' not in relative.parts and relative.as_posix() not in pins):
            raise ValueError('기존 실행기에 알 수 없는 파일이 있습니다. 자동 교체하지 않았습니다.')
    return folder


def read_flat_account(api, root, pins):
    snapshot = api.snapshot()
    verify_owner(root, pins, snapshot)
    verify_restart_journal(root/'runtime-q2x', snapshot)
    algos = api.pending_algos(full=True)
    if (any(finite(p.get('pos', '0')) != 0 for p in snapshot['positions'])
            or snapshot['orders'] or algos):
        raise ValueError('거래소 보유·미체결·조건주문이 남아 설치 보류입니다. 자동 청산/취소하지 않습니다.')
    return identity(snapshot)


def running_tokens(root, folder, expected_version):
    if not service.running(root):
        if service.running(root, 'phone_host.lock') or not transport_released(root):
            raise ValueError('이전 프로세스 종료가 확인되지 않았습니다. 중복 시작하지 않습니다.')
        return {}
    row = read_json(root/'phone_service_status.json')
    age = time.time()-row.get('observed_at', 0)
    if row.get('service_version') != expected_version or not 0 <= age < 30:
        raise ValueError('실행 중인 버전 또는 최근 상태를 확인하지 못했습니다.')
    pid = row.get('pid')
    if type(pid) is not int or pid < 2:
        raise ValueError('프로세스 식별 실패')
    argv = (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
    if str(folder/'phone_service.py').encode() not in argv or b'--supervise' not in argv:
        raise ValueError('실행 중인 프로세스와 설치 경로가 다릅니다.')
    return {p: process_token(p) for p in [pid, *child_pids(pid)]}


def wait_released(root, tokens):
    deadline = time.monotonic()+15
    while (any(token is not None and process_token(pid) == token for pid, token in tokens.items())
           or service.running(root) or service.running(root, 'phone_host.lock')
           or not transport_released(root)):
        if time.monotonic() >= deadline:
            raise ValueError('정상 종료를 기다리고 있습니다. 강제 종료하지 마세요.')
        time.sleep(.25)


def wait_ready(root):
    deadline = time.monotonic()+35
    while time.monotonic() < deadline:
        row = read_json(root/'phone_service_status.json')
        if (row.get('service_version') == service.VERSION and row.get('state') == 'running'
                and row.get('mode') == 'run' and row.get('host_process_running')
                and row.get('remote_process_running') and time.time()-row.get('observed_at', 0) < 15):
            service.wait_ui(remote_host(root))
            require_paused_flat_journal(root)
            return
        time.sleep(.5)
    raise ValueError('새 실행기 준비를 확인하지 못했습니다.')


def rollback(root, old, boot, boot_before):
    # New host has no entry authorization. Still use its ordinary graceful stop;
    # if it refuses, leave protection running and do not start another host.
    tokens = running_tokens(root, HERE, service.VERSION)
    service.request_stop(root, wait=25)
    wait_released(root, tokens)
    require_paused_flat_journal(root)
    if boot_before is None:
        if boot.exists():
            if boot.is_symlink() or service.MARKER not in boot.read_text():
                raise ValueError('자동 시작 복원 대상이 다릅니다.')
            boot.unlink()
    else:
        atomic_private(boot, boot_before)
        boot.chmod(0o700)
    subprocess.run([sys.executable, '-B', str(old/'phone_service.py'), '--root', str(root), '--start'],
                   check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def upgrade(root):
    if root.is_symlink():
        raise ValueError('폰 폴더 링크 오류')
    root = root.resolve(strict=True)
    with service.lock(root, 'phone_clock_upgrade.lock'):
        # An already completed installation is a no-op, even while trading.
        if service.running(root):
            current = read_json(root/'phone_service_status.json')
            if current.get('service_version') == service.VERSION:
                running_tokens(root, HERE, service.VERSION)
                print('이미 1.1.2 실행 중입니다. 재시작하지 않았습니다.', flush=True)
                return
        old = verify_old(root)
        require_paused_flat_journal(root)
        _, pins = verified_installation(root)
        if service.config(root).get('mode') != 'run':
            raise ValueError('이 수정은 PC에서 폰으로 전환 완료한 host-v8용입니다.')
        tokens = running_tokens(root, old, 'phone-service-'+old.name.removeprefix('host-v'))
        boot = Path.home()/'.termux'/'boot'/'40-okx-home'
        if any(p.is_symlink() for p in (boot, boot.parent, boot.parent.parent)):
            raise ValueError('자동 시작 파일 링크 오류')
        boot_before = boot.read_bytes() if boot.exists() else None
        if boot_before is not None and ('# OKX phone service v'+old.name.removeprefix('host-v')+' managed boot hook').encode() not in boot_before:
            raise ValueError('기존 자동 시작 파일을 확인하지 못했습니다.')
        api = readonly_client(validate_keys(read_json(root/'phone_credentials.json')))
        try:
            first = read_flat_account(api, root, pins)
            time.sleep(2)
            if read_flat_account(api, root, pins) != first:
                raise ValueError('설치 전 계정이 바뀌었습니다.')
            require_paused_flat_journal(root)
            print('신규 진입 중지·보유/주문 0 확인. 기존 실행기를 정상 종료합니다.', flush=True)
            save_json(root/'phone_update_result.json', dict(version=VERSION, phase='stopping', observed_at=time.time()))
            service.request_stop(root, wait=25)
            wait_released(root, tokens)
            try:
                require_paused_flat_journal(root)
                if read_flat_account(api, root, pins) != first:
                    raise ValueError('정상 종료 후 계정이 바뀌었습니다.')
                service.boot_script(root)
                service.start(root, enable=True)
                wait_ready(root)
            except Exception:
                try:
                    rollback(root, old, boot, boot_before)
                except Exception:
                    raise ValueError('설치 보류: 실행 상태 재확인이 필요합니다. 기록을 지우거나 중복 시작하지 마세요.') from None
                save_json(root/'phone_update_result.json', dict(version=VERSION, phase='rolled_back', observed_at=time.time()))
                raise ValueError('새 실행기 확인 실패. 기존 실행기를 신규 진입 중지 상태로 복원했습니다.') from None
            save_json(root/'phone_update_result.json', dict(version=VERSION, phase='installed',
                service_version=service.VERSION, core_files_unchanged=True, settings_unchanged=True,
                new_entries_paused=True, observed_at=time.time()))
            print('1.1.2 설치 완료 · 시각 조회 공유/원본 규칙/SL/설정/로그인 유지', flush=True)
            print('아이폰에서 새로고침 → 1.1.2 문구 확인 → 실거래 시작에서 확인하세요.', flush=True)
            print('활동·설정에서 폰 업데이트 확인·설치를 사용할 수 있습니다.', flush=True)
        finally:
            api.session.close()


if __name__ == '__main__':
    os.umask(0o077)
    try:
        upgrade(Path.home()/'okx-phone')
    except Exception as error:
        print('설치 보류:', str(error) if isinstance(error, ValueError) else type(error).__name__+' · 계정/연결 확인 실패. 주문을 변경하지 않았습니다.', flush=True)
        sys.exit(1)
