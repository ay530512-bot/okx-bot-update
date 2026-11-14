"""Position-preserving handover, with an explicit legacy drain transition.

Only allowlisted GETs are made by the upgrader. Never closes positions, cancels
orders, changes strategy/configuration/credentials, or force-kills a process.
"""
import hashlib
import json
import os
import copy
import secrets
import signal
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
VERSION = 'phone-upgrade-1.1.8'


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
            raise ValueError('기존 실행기 원본이 다릅니다. 자동 교체하지 않았습니다.')
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
    deadline = time.monotonic()+45
    while (any(token is not None and process_token(pid) == token for pid, token in tokens.items())
           or service.running(root) or service.running(root, 'phone_host.lock')
           or not transport_released(root)):
        if time.monotonic() >= deadline:
            raise ValueError('정상 종료를 기다리고 있습니다. 강제 종료하지 마세요.')
        time.sleep(.25)


def journal_path(root):
    return root/'runtime-q2x'/'bot_state.json'


def result(root, phase, **extra):
    save_json(root/'phone_update_result.json', dict(version=VERSION, phase=phase,
              observed_at=time.time(), **extra))


def inspect_account(api, root, pins):
    from phone_handover import validate_protected
    snapshot = api.snapshot()
    verify_owner(root, pins, snapshot)
    verify_restart_journal(root/'runtime-q2x', snapshot)
    journal = read_json(journal_path(root))
    return validate_protected(journal, snapshot, api.pending_algos(full=True))


def request_handover(root, folder, target):
    """Bound request to the installer and host processes; cancel race atomically."""
    from phone_handover import REQUEST, ACK, PROTOCOL, commit_lock
    row = read_json(root/'phone_service_status.json')
    pid = row.get('host_pid')
    if type(pid) is not int or pid < 2 or not row.get('host_process_running'):
        raise ValueError('인계할 실행 프로세스가 없습니다.')
    argv = (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
    if str(folder/'phone_host.py').encode() not in argv:
        raise ValueError('인계 프로세스 경로 불일치')
    r = dict(protocol=PROTOCOL, nonce=secrets.token_hex(16), created_at=time.time(),
             host_pid=pid, host_token=process_token(pid), installer_pid=os.getpid(),
             installer_token=process_token(os.getpid()), target=str(target))
    if r['host_token'] is None or r['installer_token'] is None:
        raise ValueError('인계 프로세스 식별 실패')
    save_json(root/REQUEST, r)
    deadline = time.monotonic()+65
    ack = None
    try:
        while time.monotonic() < deadline:
            if (root/ACK).exists():
                seen = read_json(root/ACK)
                if seen.get('nonce') == r['nonce']:
                    ack = seen
                    break
            time.sleep(.2)
    finally:
        with commit_lock(root):
            # If commit won the race, observe its ACK before removing request.
            if (root/ACK).exists():
                seen = read_json(root/ACK)
                if seen.get('nonce') == r['nonce']:
                    ack = seen
            if (root/REQUEST).exists() and read_json(root/REQUEST).get('nonce') == r['nonce']:
                (root/REQUEST).unlink()
    if not ack:
        raise ValueError('인계 응답 시간 초과 · 기존 실행기를 강제 종료하지 않았습니다.')
    if ack.get('phase') != 'released':
        raise ValueError(ack.get('message') or '인계 보류 · 기존 보호 관리 유지')
    if (ack.get('host_pid') != pid or ack.get('host_token') != r['host_token']
            or ack.get('target') != str(target)):
        raise ValueError('인계 응답 식별 불일치')
    return ack


def apply_late_stop(root, ack):
    """Only after all old processes exited. A late operator stop wins."""
    from phone_handover import CANCEL
    path = root/CANCEL
    if path.exists() and read_json(path).get('nonce') == ack.get('nonce'):
        row = read_json(journal_path(root))
        c = row['entry_continuity732']
        c.update(requested=False, event='operator_stop', reason='업데이트 인계 중 사용자가 중지',
                 ms=int(time.time()*1000))
        c['history'] = (c.get('history', [])+[dict(ms=c['ms'], event=c['event'], reason=c['reason'])])[-100:]
        save_json(journal_path(root), row)


def legacy_resume_allowed(before, after, signals_sent):
    """Restore only the updater's own pause; another operator action wins.

    Old pause+quit records explicit operator_stop. Each refused quit adds no
    quit event. Match the entire suffix, never infer intent from a timestamp.
    """
    c0, c1 = before.get('entry_continuity732', {}), after.get('entry_continuity732', {})
    if c0.get('requested') is not True or c1.get('requested') is not False:
        return False
    for key in ('schema', 'account', 'exchange', 'policy_hash', 'budget'):
        if c0.get(key) != c1.get(key):
            return False
    history = c1.get('history', [])
    previous = c0.get('history', [])
    if not previous:
        return False
    matches = [i for i, x in enumerate(history) if x == previous[-1]]
    if len(matches) != 1:
        return False
    suffix = history[matches[0]+1:]
    control = [(x.get('event'), x.get('reason')) for x in suffix
               if x.get('event') in ('operator_stop', 'started', 'auto_resumed')]
    expected = [('operator_stop', '사용자가 신규 진입 중지')]*signals_sent
    expected.append(('operator_stop', '사용자가 프로그램 종료'))
    return control == expected


def legacy_transition(root, old, tokens, api, pins):
    """One-time v13-v15 transition. No forced exit with owned positions.

    Signal the HOST, not its supervisor. If it refuses quit, supervision and
    normal protection remain running until the strategy naturally closes.
    """
    before = copy.deepcopy(read_json(journal_path(root)))
    if before.get('entry_continuity732', {}).get('schema') != 1:
        raise ValueError('기존 연속 운용 기록을 확인하지 못했습니다.')
    row = read_json(root/'phone_service_status.json')
    pid = row.get('host_pid')
    if type(pid) is not int or pid not in tokens or tokens[pid] is None:
        raise ValueError('구버전 실행 프로세스 확인 실패')
    argv = (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
    if str(old/'phone_host.py').encode() not in argv:
        raise ValueError('구버전 실행 경로 확인 실패')
    inspect_account(api, root, pins)
    print('구버전 최초 전환: 진입 자동 중지. 보유분은 기존 봇이 관리하며 자연 청산 뒤 설치합니다.', flush=True)
    result(root, 'legacy_wait', message='구버전 자동 진입 중지 · 기존 보유분 관리 후 설치',
           previous_requested=before['entry_continuity732'].get('requested'))
    signals_sent = 1
    def signal_host():
        if process_token(pid) != tokens[pid]:
            raise ValueError('구버전 프로세스가 바뀌어 중지 요청을 취소했습니다.')
        current_argv = (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
        if str(old/'phone_host.py').encode() not in current_argv:
            raise ValueError('구버전 프로세스 경로 변경 감지')
        os.kill(pid, signal.SIGTERM)
    signal_host()
    deadline = time.monotonic()+24*3600
    next_report = 0
    initial_token = tokens[pid]
    while process_token(pid) == initial_token:
        if time.monotonic() >= deadline:
            raise ValueError('24시간 대기 종료 · 설치하지 않았습니다. 기존 보유분 관리와 진입 중지 유지')
        current = read_json(journal_path(root))
        c = current.get('entry_continuity732', {})
        if c.get('requested') is False:
            try:
                require_paused_flat_journal(root)
                read_flat_account(api, root, pins)
            except ValueError:
                pass
            else:
                # One additional graceful quit after natural close, not polling
                # SIGTERM repeatedly. This is also used to identify our pauses.
                if signals_sent == 1:
                    # First signal may still be in its command batch. Give it
                    # time to finish before sending another signal.
                    time.sleep(3)
                    if process_token(pid) != initial_token:
                        break
                    require_paused_flat_journal(root)
                    read_flat_account(api, root, pins)
                    signal_host()
                    signals_sent += 1
        if time.monotonic() >= next_report:
            next_report = time.monotonic()+15
            result(root, 'legacy_wait', message='보유분 기존 관리 중 · 강제 청산/종료 없음')
        time.sleep(2)
    # A crash/restarted worker is not a completed update handover.
    wait_released(root, tokens)
    require_paused_flat_journal(root)
    read_flat_account(api, root, pins)
    after = read_json(journal_path(root))
    if legacy_resume_allowed(before, after, signals_sent):
        c = after['entry_continuity732']
        c.update(requested=True, event='update_resume_requested',
                 reason='업데이트 전 사용자 운용 요청 복구 · 계정/보호 대조 후 재개', ms=int(time.time()*1000))
        c['history'] = (c.get('history', [])+[dict(ms=c['ms'], event=c['event'], reason=c['reason'])])[-100:]
        save_json(journal_path(root), after)
    return dict(legacy=True, requested=after['entry_continuity732'].get('requested') is True)


def wait_ready(root):
    deadline = time.monotonic()+90
    while time.monotonic() < deadline:
        row = read_json(root/'phone_service_status.json')
        # Host readiness is not an unconditional entry authorization. The exact
        # Q2X startup/continuity checks independently gate actual activation.
        if (row.get('service_version') == service.VERSION and row.get('state') == 'running'
                and row.get('mode') == 'run' and row.get('host_process_running')
                and row.get('remote_process_running') and 0 <= time.time()-row.get('observed_at', 0) < 15):
            service.wait_ui(remote_host(root))
            return
        time.sleep(.5)
    raise ValueError('새 실행기 준비를 확인하지 못했습니다.')


def rollback(root, old, boot, boot_before):
    if service.running(root):
        row = read_json(root/'phone_service_status.json')
        if row.get('service_version') != service.VERSION:
            raise ValueError('복원 대상 외 실행기가 있어 중복 시작하지 않습니다.')
        tokens = running_tokens(root, HERE, service.VERSION)
        ack = request_handover(root, HERE, old)
        wait_released(root, tokens)
        apply_late_stop(root, ack)
    elif service.running(root, 'phone_host.lock') or not transport_released(root):
        raise ValueError('새 실행기 종료 미확인 · 중복 시작하지 않습니다.')
    atomic_private(boot, boot_before)
    boot.chmod(0o700)
    subprocess.run([sys.executable, '-B', str(old/'phone_service.py'), '--root', str(root), '--start'],
                   check=True, timeout=25, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def upgrade(root):
    if root.is_symlink():
        raise ValueError('폰 폴더 링크 오류')
    root = root.resolve(strict=True)
    with service.lock(root, 'phone_clock_upgrade.lock'):
        if service.running(root):
            current = read_json(root/'phone_service_status.json')
            if current.get('service_version') == service.VERSION:
                running_tokens(root, HERE, service.VERSION)
                print('이미 1.1.8 실행 중입니다. 재시작하지 않았습니다.', flush=True)
                return
        old = verify_old(root)
        _, pins = verified_installation(root)
        if service.config(root).get('mode') != 'run':
            raise ValueError('폰 운용 모드가 필요합니다.')
        tokens = running_tokens(root, old, 'phone-service-'+old.name.removeprefix('host-v'))
        boot = Path.home()/'.termux/boot/40-okx-home'
        if any(p.is_symlink() for p in (boot, boot.parent, boot.parent.parent)):
            raise ValueError('자동 시작 파일 링크 오류')
        boot_before = boot.read_bytes()
        api = readonly_client(validate_keys(read_json(root/'phone_credentials.json')))
        try:
            inspect_account(api, root, pins)
            result(root, 'preparing', message='기존 보유/손절 확인 · 운용 기록 인계 준비')
            if tokens:
                if (old/'phone_handover.py').is_file():
                    ack = request_handover(root, old, HERE)
                    wait_released(root, tokens)
                else:
                    ack = legacy_transition(root, old, tokens, api, pins)
            else:
                # Already stopped by the user: retain the persisted stop intent.
                if read_json(journal_path(root)).get('entry_continuity732', {}).get('requested') is not False:
                    raise ValueError('실행기 없는 활성 기록 · 먼저 기존 실행 상태를 확인하세요.')
                ack = dict(requested=False)
            try:
                if ack.get('phase') == 'released':
                    from phone_handover import digest
                    if digest(read_json(journal_path(root))) != ack['journal_sha']:
                        raise ValueError('인계 이후 운용 기록 변경 · 자동 교체 보류')
                    apply_late_stop(root, ack)
                # No broker writes. A stop filled during replacement is reconciled
                # by the existing core on restart; do not erase its journal.
                verified_installation(root)
                service.boot_script(root)
                result(root, 'starting', message='기록 인계 완료 · 계정/손절 대조 후 기존 운용 복구')
                service.start(root, enable=True)
                wait_ready(root)
            except Exception:
                try:
                    rollback(root, old, boot, boot_before)
                except Exception:
                    result(root, 'recovery_required', message='중복 시작 차단 · 실행기 상태 확인 필요')
                    raise ValueError('설치 보류: 관리 실행기 상태 확인 필요. 강제 종료하거나 기록을 지우지 마세요.') from None
                result(root, 'rolled_back', message='기존 실행기로 복원 · 원래 운용 요청/보호 대조 유지')
                raise ValueError('새 실행기 준비 실패. 기존 실행기로 복원했습니다.') from None
            result(root, 'installed', service_version=service.VERSION, core_files_unchanged=True,
                   settings_unchanged=True, handover_protocol=1,
                   resume_requested=read_json(journal_path(root)).get('entry_continuity732', {}).get('requested') is True,
                   message='설치 완료 · 기존 운용 요청 복구, 계정/보호 확인 전 신규 진입 차단')
            print('1.1.8 설치 완료 · 기존 매매 규칙/포지션 관리 기록/설정 유지', flush=True)
            print('아이폰 새로고침 후 1.1.8과 운용 상태를 확인하세요. 원래 중지 상태면 중지를 유지합니다.', flush=True)
        finally:
            api.session.close()


if __name__ == '__main__':
    os.umask(0o077)
    try:
        upgrade(Path.home()/'okx-phone')
    except Exception as error:
        try:
            result(Path.home()/'okx-phone', 'deferred', message=str(error) if isinstance(error, ValueError)
                   else '연결/실행 상태 확인 필요 · 주문 변경 없음')
        except Exception:
            pass
        print('설치 보류:', str(error) if isinstance(error, ValueError) else type(error).__name__+' · 연결/실행 상태 확인 필요. 주문을 변경하지 않았습니다.', flush=True)
        sys.exit(1)


