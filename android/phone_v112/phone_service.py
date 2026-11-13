#!/usr/bin/env python3
"""Home-phone supervisor. Remote setup is read-only; handover is explicit.

No exchange orders are placed here. Existing Q2X owns all execution/recovery.
No kill escalation: a managing worker may refuse graceful shutdown.
"""
import argparse
from contextlib import contextmanager
import fcntl
import http.client
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import time

from phone_account import save_json, atomic_private
import phone_remote as remote

HERE = Path(__file__).resolve().parent
VERSION = 'phone-service-10'
MARKER = '# OKX phone service v10 managed boot hook'
LEGACY_MARKER = '# OKX phone service v2 managed boot hook'
LEGACY_MARKERS = ('# OKX phone service v9 managed boot hook', '# OKX phone service v8 managed boot hook', '# OKX phone service v7 managed boot hook', LEGACY_MARKER, '# OKX phone service v3 managed boot hook', '# OKX phone service v4 managed boot hook', '# OKX phone service v5 managed boot hook', '# OKX phone service v6 managed boot hook')


@contextmanager
def lock(root, name):
    path = root/name
    if path.is_symlink():
        raise ValueError('실행 잠금 파일 링크 오류')
    with path.open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('실행 중인 폰 프로그램이 있습니다. Termux의 기존 화면에서 CTRL 다음 C를 눌러 조회를 끝내세요.')
        yield


def running(root, name='phone_service.lock'):
    try:
        with lock(root, name):
            return False
    except ValueError:
        return True


def config(root):
    from phone_host import read_json
    data = read_json(root/'phone_service.json')
    if data.get('mode') not in ('watch', 'run') or type(data.get('enabled')) is not bool:
        raise ValueError('상시 실행 설정 오류')
    if data['mode'] == 'watch' and (root/'phone_owner.json').exists():
        raise ValueError('이미 폰으로 매매를 넘겼습니다. 조회 설정으로 변경하지 않습니다.')
    if data['mode'] == 'run' and not (root/'phone_owner.json').is_file():
        raise ValueError('최초 PC 전환이 완료되지 않았습니다.')
    return data


def worker_command(root, mode):
    args = [sys.executable, '-B', str(HERE/'phone_host.py'), '--root', str(root)]
    if mode == 'run':
        args.append('--run')
    elif mode != 'watch':
        raise ValueError('실행 모드 오류')
    return args


def boot_script(root, home=None):
    home = Path(home or Path.home())
    directory = home/'.termux'/'boot'
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError('자동 시작 폴더 링크 오류')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory/'40-okx-home'
    if path.is_symlink() or (path.exists() and not any(m in path.read_text() for m in (MARKER, *LEGACY_MARKERS))):
        raise ValueError('동일 이름의 기존 자동 시작 파일은 변경하지 않았습니다.')
    shell = shutil.which('sh') or '/bin/sh'
    wake = shutil.which('termux-wake-lock')
    lines = ['#!'+shell, MARKER]
    if wake:
        lines.append(shlex.quote(wake))
    command = [sys.executable, '-B', str(HERE/'phone_service.py'), '--root', str(root), '--boot']
    lines.append('exec ' + shlex.join(command) + ' >>' + shlex.quote(str(root/'boot.log')) + ' 2>&1')
    atomic_private(path, ('\n'.join(lines)+'\n').encode())
    path.chmod(0o700)


def trim_log(path):
    # Child logs are opened O_APPEND. Retain a bounded tail in the same inode.
    if path.is_symlink():
        raise ValueError('로그 파일 링크 오류')
    if path.exists() and path.stat().st_size > 4*1024*1024:
        with path.open('r+b') as stream:
            stream.seek(-1024*1024, os.SEEK_END)
            data = stream.read()
            stream.seek(0); stream.write(data); stream.truncate()


def spawn_logged(command, root, name):
    path = root/name
    trim_log(path)
    with path.open('ab', buffering=0) as output:
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                close_fds=True, start_new_session=True)


def retry_delay(failures):
    return min(60, 2 ** min(max(failures, 1), 6))


def supervise(root):
    with lock(root, 'phone_service.lock'):
        initial = config(root)
        if not initial['enabled']:
            return
        if running(root, 'phone_host.lock'):
            raise ValueError('기존 폰 실행기가 켜져 있습니다. 중복 실행하지 않습니다.')
        wake = shutil.which('termux-wake-lock')
        if wake:
            subprocess.run([wake], check=False, timeout=10)
        stop = [False]
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.__setitem__(0, True))
        daemon = None
        worker = None
        daemon_next = worker_next = 0
        daemon_failures = worker_failures = 0
        daemon_start = worker_start = 0
        daemon_last_exit = daemon_last_exit_at = None
        worker_stop_sent = False
        disabled = False
        next_report = 0
        request = root/'phone_stop_request.json'
        while True:
            now = time.monotonic()
            # Normal stop is persisted; reboot must not undo an operator stop.
            if request.exists():
                if request.is_symlink():
                    raise ValueError('종료 요청 링크 오류')
                stop[0] = True
                worker_stop_sent = False
                request.unlink()
            if stop[0]:
                if not disabled:
                    save_json(root/'phone_service.json', dict(initial, enabled=False))
                    disabled = True
                if worker and worker.poll() is None:
                    if not worker_stop_sent:
                        worker.terminate()  # Q2X pauses; refuses quit with owned positions.
                        worker_stop_sent = True
                else:
                    if daemon and daemon.poll() is None:
                        daemon.terminate()
                        try:
                            daemon.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            pass
                    save_json(root/'phone_service_status.json', dict(state='stopped', observed_at=time.time(), pid=os.getpid()))
                    return
            # Connectivity failure never restarts a healthy managing worker.
            if daemon and daemon.poll() is not None:
                daemon_last_exit = daemon.returncode
                daemon_last_exit_at = time.time()
                daemon_failures = 1 if now-daemon_start > 300 else daemon_failures+1
                daemon_next = now+retry_delay(daemon_failures)
                daemon = None
            if daemon is None and now >= daemon_next:
                try:
                    daemon = spawn_logged(remote.daemon_command(root), root, 'remote.log')
                    daemon_start = now
                except Exception:
                    daemon_failures += 1
                    daemon_next = now+retry_delay(daemon_failures)
            if worker and worker.poll() is not None and not stop[0]:
                code = worker.returncode
                worker = None
                if code == 0:
                    stop[0] = True
                    continue
                worker_failures = 1 if now-worker_start > 300 else worker_failures+1
                worker_next = now+retry_delay(worker_failures)
            if worker is None and not stop[0] and now >= worker_next:
                try:
                    worker = spawn_logged(worker_command(root, initial['mode']), root, 'host.log')
                    worker_start = now
                except Exception:
                    worker_failures += 1
                    worker_next = now+retry_delay(worker_failures)
            if now >= next_report:
                next_report = now+5
                save_json(root/'phone_service_status.json', dict(
                    pid=os.getpid(), service_version=VERSION,
                    state='stopping' if stop[0] else 'running', mode=initial['mode'],
                    host_process_running=bool(worker and worker.poll() is None),
                    remote_process_running=bool(daemon and daemon.poll() is None),
                    host_pid=worker.pid if worker else None, remote_pid=daemon.pid if daemon else None,
                    remote_last_exit_code=daemon_last_exit, remote_last_exit_at=daemon_last_exit_at,
                    host_restarts=worker_failures, remote_restarts=daemon_failures, observed_at=time.time()))
                for name in ('host.log', 'remote.log', 'service.log', 'boot.log'):
                    trim_log(root/name)
            time.sleep(.5)


def start(root, enable=False):
    value = config(root)
    if running(root):
        if (root/'phone_stop_request.json').exists() or not value['enabled']:
            raise ValueError('정상 종료 대기 중입니다. 보유분 관리를 끝낸 후 다시 시작하세요.')
        return
    if running(root, 'phone_host.lock'):
        raise ValueError('기존 조회 실행기를 CTRL 다음 C로 끝낸 후 다시 실행하세요.')
    if enable:
        value['enabled'] = True
        save_json(root/'phone_service.json', value)
    if not value['enabled']:
        return
    request = root/'phone_stop_request.json'
    if request.is_symlink():
        raise ValueError('종료 요청 파일 링크 오류')
    if request.exists():
        request.unlink()
    child = spawn_logged([sys.executable, '-B', str(HERE/'phone_service.py'), '--root', str(root), '--supervise'], root, 'service.log')
    for _ in range(40):
        if running(root):
            return
        if child.poll() is not None:
            raise ValueError('백그라운드 시작 실패 · service.log를 확인해야 합니다.')
        time.sleep(.25)
    raise ValueError('백그라운드 시작 확인이 지연되고 있습니다.')


def request_stop(root, wait=20):
    value = config(root)
    save_json(root/'phone_service.json', dict(value, enabled=False))
    if running(root):
        save_json(root/'phone_stop_request.json', dict(requested_at=time.time()))
    end = time.monotonic()+wait
    while running(root) and time.monotonic() < end:
        time.sleep(.25)
    if running(root):
        raise ValueError('종료 대기 중입니다. 보유분이 있으면 보호 관리를 계속합니다. 강제 종료하지 마세요.')


def wait_ui(hostname):
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection('127.0.0.1', 8768, timeout=2)
        try:
            connection.request('GET', '/', headers={'Host': hostname})
            result = connection.getresponse()
            body = result.read(2*1024*1024)
            if result.status == 200 and b'phone-host-notice' in body:
                return
        except OSError:
            pass
        finally:
            connection.close()
        time.sleep(.5)
    raise ValueError('폰 대시보드 준비를 확인하지 못했습니다. PC는 유지하고 --status 결과를 확인하세요.')


def setup(root):
    from phone_host import verified_installation, auth_config
    from phone_mobile import mobile_module
    if (root/'phone_owner.json').exists():
        raise ValueError('이미 폰 매매가 시작되었습니다. 실행 중인 엔진은 변경하지 않았습니다. --status로 확인하세요.')
    if not running(root) and running(root, 'phone_host.lock'):
        raise ValueError('기존 조회 화면을 CTRL 다음 C로 끝낸 후 같은 설치 명령을 다시 실행하세요.')
    source, _ = verified_installation(root)
    auth_config(root, mobile_module(source))
    remote.install(root)
    # Downloads/verification finish before stopping the known watch-only host.
    from phone_migrate import prepare_watch_upgrade
    prepare_watch_upgrade(root)
    path = root/'phone_service.json'
    if not path.exists():
        save_json(path, dict(mode='watch', enabled=True))
    boot_script(root)
    start(root, enable=True)
    for _ in range(60):
        try:
            remote.status(root)
            break
        except (ValueError, subprocess.TimeoutExpired):
            time.sleep(.5)
    address = remote.configure(root)
    wait_ui(address.removeprefix('https://'))
    print('\n=== 집 폰 원격 조회 준비 ===', flush=True)
    print('아이폰: Tailscale 연결 → Safari에서 아래 주소', flush=True)
    print(address, flush=True)
    print('폴드3: http://127.0.0.1:8768', flush=True)
    print('폰 화면 비밀번호로 로그인하세요. Termux는 백그라운드에서 계속 실행합니다.', flush=True)
    print('현재 조회 모드 · 아직 PC가 매매합니다. 아이폰 접속 확인 후 전환하세요.', flush=True)
    print('화면 꺼짐 장시간 운용은 아직 미검증입니다. Termux 배터리를 제한 없음으로 설정하세요.', flush=True)
    print('재부팅 자동 시작: 같은 출처의 Termux:Boot 설치 후 아이콘을 한 번 열어야 합니다.', flush=True)


def handover(root):
    from phone_host import (ACK, verified_installation, prepare_runtime, take_ownership,
                            validate_keys, read_json, readonly_client)
    if (root/'phone_owner.json').exists():
        raise ValueError('이미 전환했습니다. --start를 사용하세요.')
    value = config(root)
    if value['mode'] != 'watch':
        raise ValueError('조회 상태에서만 최초 전환할 수 있습니다.')
    print('PC 신규 진입 중지 → 보유/미체결/조건주문 모두 0 → PC 프로그램 정상 종료 후에만 진행하세요.', flush=True)
    answer = input(f'완료했다면 "{ACK}" 입력: ').strip()
    if answer != ACK:
        raise ValueError('전환하지 않았습니다.')
    request_stop(root)
    try:
        with lock(root, 'phone_host.lock'):
            source, pins = verified_installation(root)
            runtime = prepare_runtime(root, pins)
            api = readonly_client(validate_keys(read_json(root/'phone_credentials.json')))
            try:
                take_ownership(root, runtime, api, pins, answer)
            finally:
                api.session.close()
            save_json(root/'phone_service.json', dict(mode='run', enabled=True))
    except Exception:
        # Rejected flat-account check restores observation only, never trades.
        if not (root/'phone_owner.json').exists():
            start(root, enable=True)
        raise
    start(root)
    print('폰 관리 실행 요청 완료. 화면에서 계정/보호 상태를 확인한 뒤 실거래 시작 → 확인을 누르세요.', flush=True)


def show_status(root):
    from phone_host import read_json, remote_host
    print('상시 실행기:', '실행 중' if running(root) else '중지')
    print('폰 매매 전환:', '전환 기록 있음' if (root/'phone_owner.json').exists() else '미전환 · PC 관리')
    if (root/'phone_service_status.json').exists():
        data = read_json(root/'phone_service_status.json')
        print('마지막 프로세스 상태:', data.get('state'), '/ 기록 경과', max(0, round(time.time()-data['observed_at'])), '초')
    name = remote_host(root)
    if name:
        print('아이폰 주소: https://'+name)
    print('폴드3 주소: http://127.0.0.1:8768')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.home()/'okx-phone')
    group = parser.add_mutually_exclusive_group()
    for flag in ('setup', 'start', 'stop', 'status', 'handover', 'supervise', 'boot'):
        group.add_argument('--'+flag, action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.root.is_symlink():
        raise ValueError('폰 폴더 링크 오류')
    root = args.root.resolve(strict=True)
    if args.supervise:
        supervise(root)
    elif args.boot:
        start(root)
    elif args.start:
        start(root, enable=True); show_status(root)
    elif args.stop:
        request_stop(root); show_status(root)
    elif args.handover:
        handover(root)
    elif args.status:
        show_status(root)
    else:
        try:
            setup(root)
        except Exception:
            print('\n설정이 끝나지 않아 읽기 전용 종료 기록을 함께 표시합니다.', flush=True)
            try:
                from phone_remote_check import display, diagnostic
                display(diagnostic(root))
            except Exception as diagnostic_error:
                print('종료 기록 확인 실패:', type(diagnostic_error).__name__, flush=True)
            raise


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n설정 입력을 끝냈습니다. 백그라운드 서비스는 유지됩니다. 같은 설치 명령으로 이어갈 수 있습니다.')
        sys.exit(1)
    except Exception as exc:
        print('진행 보류:', str(exc) if isinstance(exc, ValueError) else type(exc).__name__, flush=True)
        sys.exit(1)
