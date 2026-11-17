"""Graceful update recovery for a paused, independently verified empty account.

Older handover code also rejects orphaned in-memory work flags. Never clear
those flags or kill their owner: use its serial pause/quit commands, which
refuse to quit if an owned position appears. All exchange access is GET-only.
"""
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

from phone_account import save_json
from phone_handover import load
from phone_migrate import process_token, transport_released
import phone_service as service

WATCHERS = []


def released(root, tokens):
    return (all(token is None or process_token(pid) != token for pid, token in tokens.items())
            and not service.running(root) and not service.running(root, 'phone_host.lock')
            and transport_released(root))


def complete(ack):
    if ack.get('flat_path'):
        path = Path(ack['flat_path'])
        row = load(path)
        row['phase'] = 'complete'
        save_json(path, row)


def start_watchdog(path):
    child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--recover', str(path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True)
    WATCHERS.append(child)
    if child.poll() is not None:
        raise ValueError('업데이트 복구 감시를 시작하지 못했습니다.')


def recover(path):
    """A dead installer never leaves a stopped phone without its prior service.

    No signal is sent here. In particular, a refused quit continues managing.
    Never start a second owner or overwrite an unrelated boot registration.
    """
    from phone_legacy_restart import restore_old, wait_old_ready
    path = Path(path)
    root = path.parent
    while True:
        row = load(path)
        if row['phase'] == 'complete':
            return
        pid, token = row['installer']
        if process_token(pid) != token:
            break
        time.sleep(.25)
    if row['phase'] == 'prepared':
        return  # The graceful stop was never requested.
    deadline = time.monotonic()+300
    tokens = dict(row['tokens'])
    while time.monotonic() < deadline:
        if load(path)['phase'] == 'complete':
            return
        if released(root, tokens):
            try:
                with service.lock(root, 'phone_clock_upgrade.lock'):
                    if load(path)['phase'] == 'complete':
                        return
                    if not released(root, tokens):
                        continue
                    restore_old(root, row)
                    wait_old_ready(root, Path(row['old']))
                    complete(dict(flat_path=str(path)))
                    return
            except ValueError:
                pass
        status = load(root/'phone_service_status.json')
        if (status.get('host_pid') != row['host_pid'] and status.get('state') == 'running'
                and status.get('host_process_running') and status.get('remote_process_running')
                and 0 <= time.time()-status.get('observed_at', 0) < 15
                and service.running(root) and service.running(root, 'phone_host.lock')):
            return  # Replacement/rollback already owns the runtime.
        time.sleep(.25)


def transition(root, old, target, tokens, api, pins, boot_before):
    from phone_button_upgrade import require_paused_flat_journal, read_flat_account, wait_released, result
    from phone_legacy_restart import restore_old, wait_old_ready
    # Check both local intent/unfinished records and the actual exchange twice.
    # No guessed flat state on errors, and no implicit pause of an active bot.
    account = None
    for _ in range(2):
        require_paused_flat_journal(root)
        current = read_flat_account(api, root, pins)
        require_paused_flat_journal(root)
        if account is not None and current != account:
            raise ValueError('업데이트 대조 중 계정이 변경되었습니다.')
        account = current
    status = load(root/'phone_service_status.json')
    host = status.get('host_pid')
    supervisor = status.get('pid')
    if (not status.get('host_process_running') or not 0 <= time.time()-status.get('observed_at', 0) < 30):
        raise ValueError('정상 종료 대상의 최근 상태를 확인하지 못했습니다.')
    for pid, name in ((host, 'phone_host.py'), (supervisor, 'phone_service.py')):
        if (type(pid) is not int or pid < 2 or tokens.get(pid) is None
                or process_token(pid) != tokens[pid]
                or str(old/name).encode() not in (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')):
            raise ValueError('정상 종료 대상 프로세스가 바뀌어 설치를 보류합니다.')
    path = root/('phone-flat-update-'+secrets.token_hex(16)+'.json')
    row = dict(phase='prepared', old=str(old), target=str(target), boot_hex=boot_before.hex(),
               installer=[os.getpid(), process_token(os.getpid())], host_pid=host,
               tokens=list(tokens.items()))
    save_json(path, row)
    start_watchdog(path)
    ack = dict(flat_path=str(path), requested=False)
    try:
        require_paused_flat_journal(root)
        if process_token(host) != tokens[host]:
            raise ValueError('정상 종료 대상 프로세스 변경 감지')
        result(root, 'preparing', message='진입 중지·보유/미체결/조건주문 없음 확인 · 정상 종료 후 업데이트')
        row['phase'] = 'stopping'
        save_json(path, row)
        os.kill(host, signal.SIGTERM)  # Host serializes pause + quit; no forced exit.
        wait_released(root, tokens)
        require_paused_flat_journal(root)
        if read_flat_account(api, root, pins) != account:
            raise ValueError('정상 종료 후 계정 대조 실패')
        require_paused_flat_journal(root)
        return ack
    except Exception:
        # This is before upgrade()'s ordinary rollback boundary. Restore here
        # if the graceful stop completed, including a post-stop GET failure.
        if released(root, tokens):
            restore_old(root, row)
            wait_old_ready(root, old)
            complete(ack)
        # If the host is still exiting, the watcher recovers after installer
        # death. A refused quit is never escalated to a forced stop.
        raise


def handover_or_flat(root, old, target, tokens, api, pins, boot_before):
    from phone_button_upgrade import request_handover, HandoverBusy
    for attempt in range(2):
        try:
            return request_handover(root, old, target)
        except HandoverBusy:
            if not attempt:
                time.sleep(1)  # Let a transient serial command batch finish.
    return transition(root, old, target, tokens, api, pins, boot_before)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--recover':
        recover(sys.argv[2])
