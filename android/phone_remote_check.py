#!/usr/bin/env python3
"""Read-only connection diagnostics. No login, stop, config write or OKX access.

Reads only service metadata and bounded remote/service logs. Never opens API
credentials, strategy configuration, trading journals or Tailscale state content.
Raw CLI status (including AuthURL/User/Peer) is discarded, never printed/saved.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import time

VERSION = 'phone-remote-check-3'
BIN_HASHES = {
    'android-arm64-r1': 'ca27b5c24dfa6bbe63385ff58049bdadea74364dc01b4d4b2873bd16f3256d06',
    'arm64': '2e547c5e8acb4e9dc7c3ae576c302346044bd2f30958515cca5b7a91fb5cd636',
    'amd64': 'a781895a86932424dce380c8b445c77b8568dd2248a7fed20ba77ce3cb221185',
}
STATES = {'NoState', 'InUseOtherUser', 'NeedsLogin', 'NeedsMachineAuth', 'Stopped', 'Starting', 'Running'}
LOG_MARKERS = ('panic:', 'fatal error:', 'fatal:', 'operation not permitted', 'permission denied',
               'unexpected eof', 'signal: killed', 'out of memory', 'failed', 'error:',
               'no space left', 'read-only file system', 'no such file', 'segmentation', 'sigsys')
CRITICAL_MARKERS = ('panic:', 'fatal error:', 'fatal:', 'sigsys:', 'sigsegv:',
                    'sigabrt:', 'signal: killed', 'out of memory',
                    'exiting process with status', 'must be enabled',
                    'logging is required', 'log upload is required',
                    'no space left', 'read-only file system')


def tail(path, limit=512*1024):
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
    # Validate candidates: a clock such as 08:04:21 is NOT an IPv6 address.
    def hide_ip6(match):
        try:
            ipaddress.IPv6Address(match.group())
            return '[IP6]'
        except ValueError:
            return match.group()
    text = re.sub(r'(?<![\w:])(?:[0-9a-f]{0,4}:){2,}[0-9a-f]{0,4}(?:%[\w.-]+)?',
                  hide_ip6, text, flags=re.I)
    text = re.sub(r'\b[\w.-]+\.ts\.net(?::\d+)?', '[TAILNET]', text, flags=re.I)
    text = re.sub(r'\b(?:tskey-[\w-]+|(?:privkey|nodekey|machinekey|authkey):\S+)', '[KEY]', text, flags=re.I)
    text = re.sub(r'((?:token|secret|password|authorization|api.?key)\s*[=:]\s*)\S+', r'\1[HIDDEN]', text, flags=re.I)
    text = re.sub(r'\b((?:o?node|machine|ts2021|legacy)=)\[[^\]]*\]', r'\1[ID]', text)
    text = re.sub(r'("(?:DisplayName|LoginName|UserName|HostName|DNSName)"\s*:\s*)"[^"]*"',
                  r'\1"[HIDDEN]"', text, flags=re.I)
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
        value = row.get('remote_last_exit_code')
        result['remote_last_exit_code'] = value if type(value) is int else None
        result['service_version'] = row.get('service_version') if row.get('service_version') == 'phone-service-3' else 'legacy'
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
        ('금지된 시스템 호출 종료', ('sigsys:',)),
        ('권한 관련 기록(종료 원인 확정 아님)', ('operation not permitted', 'permission denied')),
        ('메모리/강제 종료 기록', ('out of memory', 'signal: killed')),
        ('저장 오류', ('no space left', 'read-only file system')),
        ('연결 중단 기록', ('unexpected eof',)),
        ('인증서 오류', ('x509:', 'certificate signed by unknown authority')),
        ('DNS 오류', ('no such host', 'dns lookup failed')),
    ):
        if any(n in low for n in needles):
            flags.append(label)
    return flags


def exit_context(log, root):
    """Keep crash evidence even when a new startup appends routine warnings.

    A log boundary is not proof of a crash: the supervisor's actual exit code
    was not recorded by host-v2. Never label ordinary fallback warnings fatal.
    """
    lines = log.splitlines()
    starts = [i for i, line in enumerate(lines) if 'Program starting:' in line]
    critical = [i for i, line in enumerate(lines)
                if any(word in line.lower() for word in CRITICAL_MARKERS)]
    selected = []
    if critical:
        # The last actual fatal/signal header survives a long Go stack dump.
        index = critical[-1]
        selected.extend(lines[max(0, index-2):index+6])
    if len(starts) >= 2:
        index = starts[-1]
        # No error-word filter: log.Fatal/normal exit may have neither 'error'
        # nor 'fatal'. Preserve the end of the previous daemon instance.
        previous = [line for line in lines[starts[-2]:index]
                    if line.strip() and 'logtail started' not in line
                    and 'You have disabled logging.' not in line]
        selected.extend(previous[-12:])
    elif not critical:
        selected.extend([line for line in lines if line.strip()][-12:])
    clean = list(dict.fromkeys(mask(line, root)[:320] for line in selected))
    return dict(starts_in_log_tail=len(starts), critical_header_found=bool(critical),
                before_restart=clean[:20])


def diagnostic(root, pause=time.sleep, status=local_status):
    first = metadata(root)
    state1 = status(root)
    pause(3)
    second = metadata(root)
    state2 = status(root)
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
                log_signals=signals(log), log_hints=hints, exit_context=exit_context(log, root))


def display(data):
    s = data['service_after']
    print('=== 폰 원격 연결 진단 (읽기만) ===')
    print('실행기:', s.get('state'), '/ 모드:', s.get('mode'), '/ 기록 경과:', s.get('age_seconds'), '초')
    print('조회 실행:', s.get('host_process_running'), '/ 원격 실행:', s.get('remote_process_running'))
    print('재시작 횟수(조회/원격):', s.get('host_restarts'), '/', s.get('remote_restarts'))
    print('Tailscale 상태:', data['tailscale_before']['state'], '→', data['tailscale_after']['state'])
    print('로그인 저장파일:', '있음' if data['state_file_exists'] else '없음', '/ 크기:', data['state_file_bytes'])
    print('로그 신호:', ', '.join(data['log_signals']) or '분류된 오류 없음')
    context = data['exit_context']
    print('로그 내 시작 횟수:', context['starts_in_log_tail'], '/ 최근 원격 종료코드:',
          s.get('remote_last_exit_code') if s.get('remote_last_exit_code') is not None else '기록 없음')
    print('아래는 과거 종료 기록이며 현재 연결 상태는 위 상태값으로 확인합니다.')
    print('--- 종료 직전 기록 (민감정보 가림) ---')
    for i, text in enumerate(context['before_restart'], 1):
        print(f'{i}. {text}')
    if not context['before_restart']:
        print('종료 직전 기록을 확보하지 못했습니다. 원인 미확정입니다.')
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
