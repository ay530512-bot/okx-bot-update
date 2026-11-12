#!/usr/bin/env python3
"""Read-only connection diagnostics. No login, stop, config write or OKX access.

Reads only service metadata and bounded remote/service logs. Never opens API
credentials, strategy configuration, trading journals or Tailscale state content.
Raw CLI status (including AuthURL/User/Peer) is discarded, never printed/saved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

VERSION = 'phone-remote-check-1'
BIN_HASHES = {
    'arm64': '2e547c5e8acb4e9dc7c3ae576c302346044bd2f30958515cca5b7a91fb5cd636',
    'amd64': 'a781895a86932424dce380c8b445c77b8568dd2248a7fed20ba77ce3cb221185',
}
STATES = {'NoState', 'InUseOtherUser', 'NeedsLogin', 'NeedsMachineAuth', 'Stopped', 'Starting', 'Running'}
LOG_MARKERS = ('panic:', 'fatal error:', 'fatal:', 'operation not permitted', 'permission denied',
               'unexpected eof', 'signal: killed', 'out of memory', 'failed', 'error:',
               'no space left', 'read-only file system', 'no such file', 'segmentation', 'sigsys')


def tail(path, limit=96*1024):
    if path.is_symlink() or not path.is_file():
        return ''
    with path.open('rb') as stream:
        size = os.fstat(stream.fileno()).st_size
        stream.seek(max(0, size-limit))
        return stream.read(limit).decode('utf-8', errors='replace')


def mask(text, root=None):
    if root:
        text = text.replace(str(root), '[PHONE]')
    text = re.sub(r'https?://\S+', '[URL]', text, flags=re.I)
    text = re.sub(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[EMAIL]', text, flags=re.I)
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b', '[IP]', text)
    text = re.sub(r'(?<!\w)(?:[0-9a-f]{0,4}:){2,}[0-9a-f:%]{0,20}', '[IP6]', text, flags=re.I)
    text = re.sub(r'\b[\w.-]+\.ts\.net(?::\d+)?', '[TAILNET]', text, flags=re.I)
    text = re.sub(r'\b(?:tskey-[\w-]+|(?:privkey|nodekey|machinekey|authkey):\S+)', '[KEY]', text, flags=re.I)
    text = re.sub(r'((?:token|secret|password|authorization|api.?key)\s*[=:]\s*)\S+', r'\1[HIDDEN]', text, flags=re.I)
    text = re.sub(r'\b[\w+/=-]{24,}\b', '[ID]', text)
    # Strip terminal escape/control characters before showing any log-derived text.
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return ''.join(c for c in text if c >= ' ' or c in '\n\t')


def metadata(root):
    path = root/'phone_service_status.json'
    try:
        if path.is_symlink() or path.stat().st_size > 16384:
            raise ValueError()
        row = json.loads(path.read_text())
        result = {}
        for key in ('pid', 'host_restarts', 'remote_restarts'):
            value = row.get(key)
            result[key] = value if type(value) is int and value >= 0 else None
        for key in ('host_process_running', 'remote_process_running'):
            result[key] = row.get(key) if type(row.get(key)) is bool else None
        result['state'] = row.get('state') if row.get('state') in ('running', 'stopping', 'stopped') else 'unknown'
        result['mode'] = row.get('mode') if row.get('mode') in ('watch', 'run') else 'unknown'
        value = row.get('observed_at')
        result['age_seconds'] = max(0, round(time.time()-value)) if type(value) in (int, float) else None
        return result
    except (OSError, ValueError, TypeError, OverflowError):
        return dict(state='unavailable')


def local_status(root, run=subprocess.run):
    binary = None
    for arch, digest in BIN_HASHES.items():
        candidate = root/f'tailscale-1.104.6-{arch}'/'tailscale'
        if candidate.parent.is_symlink() or candidate.is_symlink() or not candidate.is_file():
            continue
        if candidate.stat().st_size > 80*1024*1024:
            continue
        if hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
            binary = candidate
            break
    if binary is None:
        return dict(state='binary_not_verified')
    try:
        response = run([str(binary), '--socket='+str(root/'remote-private'/'ts.sock'),
                        'status', '--json'], capture_output=True, text=True, timeout=8, check=False)
        try:
            value = json.loads(response.stdout)
            if not isinstance(value, dict):
                raise ValueError()
            state = value.get('BackendState')
            return dict(state=state if state in STATES else 'unknown', exit_code=response.returncode)
        except (ValueError, TypeError):
            error = (response.stderr or '').lower()
            reason = 'EOF' if 'eof' in error else ('daemon_unreachable' if any(x in error for x in ('failed to connect', 'connection refused', 'no such file')) else 'status_unreadable')
            return dict(state=reason, exit_code=response.returncode)
    except subprocess.TimeoutExpired:
        return dict(state='timeout')
    except OSError:
        return dict(state='cannot_execute')


def signals(log):
    low = log.lower()
    flags = []
    for label, needles in (
        ('프로세스 패닉', ('panic:', 'fatal error:')),
        ('권한 거부', ('operation not permitted', 'permission denied')),
        ('메모리/강제 종료 기록', ('out of memory', 'signal: killed')),
        ('저장 오류', ('no space left', 'read-only file system')),
        ('연결 중단 기록', ('unexpected eof',)),
        ('인증서 오류', ('x509:', 'certificate signed by unknown authority')),
        ('DNS 오류', ('no such host', 'dns lookup failed')),
    ):
        if any(n in low for n in needles):
            flags.append(label)
    return flags


def diagnostic(root, pause=time.sleep, status=local_status):
    first = metadata(root)
    state1 = status(root)
    pause(3)
    second = metadata(root)
    state2 = status(root)
    # Preserve the first panic plus its package/function names, even if later
    # reconnect attempts append less specific errors. Paths/keys are masked.
    log = tail(root/'remote.log')
    lines = log.splitlines()
    selected = []
    for i, line in enumerate(lines):
        if any(k in line.lower() for k in LOG_MARKERS):
            selected.append(line)
            if 'panic:' in line.lower() or 'fatal error:' in line.lower():
                selected.extend(lines[i+1:i+5])
    selected += [line for line in tail(root/'service.log', 8192).splitlines()
                 if any(k in line.lower() for k in LOG_MARKERS)]
    hints = list(dict.fromkeys(mask(s, root)[:220] for s in selected))[-8:]
    state_file = root/'remote-private'/'tailscaled.state'
    state_size = None
    if not state_file.is_symlink() and state_file.is_file():
        state_size = state_file.stat().st_size
    return dict(version=VERSION, service_before=first, service_after=second,
                tailscale_before=state1, tailscale_after=state2,
                state_file_exists=state_size is not None, state_file_bytes=state_size,
                log_signals=signals(log), log_hints=hints)


def display(data):
    s = data['service_after']
    print('=== 폰 원격 연결 진단 (읽기만) ===')
    print('실행기:', s.get('state'), '/ 모드:', s.get('mode'), '/ 기록 경과:', s.get('age_seconds'), '초')
    print('조회 실행:', s.get('host_process_running'), '/ 원격 실행:', s.get('remote_process_running'))
    print('재시작 횟수(조회/원격):', s.get('host_restarts'), '/', s.get('remote_restarts'))
    print('Tailscale 상태:', data['tailscale_before']['state'], '→', data['tailscale_after']['state'])
    print('로그인 저장파일:', '있음' if data['state_file_exists'] else '없음', '/ 크기:', data['state_file_bytes'])
    print('로그 신호:', ', '.join(data['log_signals']) or '분류된 오류 없음')
    for i, text in enumerate(data['log_hints'], 1):
        print(f'{i}. {text}')
    print('=== 끝 · API/주문/설정/로그인 변경 없음 ===')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.home()/'okx-phone')
    args = parser.parse_args()
    if args.root.is_symlink():
        raise ValueError('폰 폴더 링크 오류')
    root = args.root.resolve(strict=True)
    display(diagnostic(root))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('진단 중단:', type(exc).__name__, '· 파일 삭제/재설치하지 마세요.')
