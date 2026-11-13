#!/usr/bin/env python3
"""Standalone read-only delay check for an already-running phone host.

No engine imports, credentials, signed requests, state writes, process signals,
login, reconnect, or configuration changes. Prints allowlisted diagnostics only.
Public IPv4 time probes run in bounded subprocesses, independent of the bot.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import http.client
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import time

VERSION = 'phone-delay-check-1'
KST = timezone(timedelta(hours=9))
LOGS = ('runtime-q2x/bot_log.txt', 'host.log')
ERROR_NAMES = ('WebSocketTimeoutException', 'WebSocketConnectionClosedException',
               'ConnectionResetError', 'ConnectionAbortedError', 'BrokenPipeError',
               'ConnectTimeout', 'ReadTimeout', 'TimeoutError', 'ConnectionError',
               'SSLError', 'gaierror', 'PermissionError', 'MemoryError',
               'RuntimeError', 'ValueError', 'OSError')


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def read_bounded(root, relative, size=262144):
    path = root / relative
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            return ''
        with path.open('rb') as stream:
            stream.seek(max(0, os.fstat(stream.fileno()).st_size-size))
            return stream.read(size).decode('utf-8', errors='replace')
    except OSError:
        return ''


def service(root):
    try:
        data = json.loads(read_bounded(root, 'phone_service_status.json', 16384))
        if not isinstance(data, dict):
            return {}
    except ValueError:
        return {}
    out = {k: data.get(k) if data.get(k) in values else 'unknown' for k, values in
           {'state': ('running', 'stopping', 'stopped'), 'mode': ('watch', 'run')}.items()}
    for k in ('host_process_running', 'remote_process_running'):
        out[k] = data.get(k) if type(data.get(k)) is bool else None
    for k in ('host_restarts', 'remote_restarts', 'remote_last_exit_code', 'host_pid'):
        out[k] = number(data.get(k))
    observed = number(data.get('observed_at'))
    out['record_age_seconds'] = round(time.time()-observed, 1) if observed else None
    return out


def classify(line):
    """Never echo raw logs: they may contain keys, account details or auth URLs."""
    tags = []
    for name in ERROR_NAMES:
        if re.search(r'(?<![A-Za-z])'+name+r'(?![A-Za-z])', line):
            tags.append(name)
    for code in ('50011', '50040', '50110', '50102', '50113', '50123'):
        if re.search(r'\bOKX\s+'+code+r'\b', line):
            tags.append('OKX '+code)
    for phrase, label in (
        ('스냅샷 지연', '계정 WS 스냅샷 지연'),
        ('공개 WS: 미연결', '공개 WS 미연결'),
        ('계정 WS: 미연결', '계정 WS 미연결'),
        ('계정 WS 로그인 실패', '계정 WS 로그인 실패'),
        ('계정 WS 구독 오류', '계정 WS 구독 오류'),
        ('복구 대조 대기', '계정/주문 대조 보류'),
        ('연결 끊김/재연결', '연결 복구 진입'),
        ('기록 외 조건주문', '미인식 조건주문 대조'),
        ('가격·체결·호가 WebSocket 데이터 지연', '주문 전 종목 데이터 지연'),
        ('주문 직전 WS 지연', '주문 전 종목 데이터 지연'),
        ('금지된 시스템', '시스템 호출 종료'),
        ('SIGSYS', '시스템 호출 종료'),
        ('panic:', '프로세스 패닉')):
        if phrase in line:
            tags.append(label)
    return sorted(set(tags))


def log_summary(text, now):
    rows = []
    counts = Counter()
    for line in text.splitlines():
        match = re.match(r'^(\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s', line)
        if not match:
            continue
        try:
            stamp = datetime.strptime(str(now.year)+'-'+match[1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST)
            if stamp > now+timedelta(days=1):
                stamp = stamp.replace(year=stamp.year-1)
        except ValueError:
            continue
        if not 0 <= (now-stamp).total_seconds() <= 3600:
            continue
        tags = classify(line)
        if tags:
            counts.update(tags)
            rows.append({'time_kst': match[1], 'signals': tags})
    return {'counts': dict(counts), 'recent': rows[-12:]}


def process(pid):
    if type(pid) is not int or pid <= 0:
        return {}
    try:
        text = Path('/proc', str(pid), 'status').read_text()
        return {label: int(m[1]) for key, label in (('Threads', 'threads'), ('VmRSS', 'rss_kib'))
                if (m := re.search(r'^'+key+r':\s+(\d+)', text, re.M))}
    except OSError:
        return {}


class PublicIPv4(http.client.HTTPSConnection):
    def connect(self):
        failure = None
        for family, kind, proto, _, address in socket.getaddrinfo(self.host, 443, socket.AF_INET, socket.SOCK_STREAM):
            sock = socket.socket(family, kind, proto)
            sock.settimeout(4)
            try:
                sock.connect(address)
                self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
                return
            except Exception as exc:
                sock.close()
                failure = exc
        raise failure or OSError('No IPv4 address')


def public_probe():
    started = time.monotonic()
    wall = time.time()
    connection = PublicIPv4('www.okx.com', timeout=4)
    result = {'ok': False}
    try:
        connection.request('GET', '/api/v5/public/time', headers={'User-Agent': VERSION})
        response = connection.getresponse()
        result['http_status'] = response.status
        value = json.loads(response.read(16384))
        if response.status == 200 and value.get('code') == '0':
            server = float(value['data'][0]['ts'])/1000
            result['ok'] = math.isfinite(server)
            if result['ok']:
                result['approx_clock_offset_s'] = round(server-(wall+time.time())/2, 3)
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    finally:
        connection.close()
    result['elapsed_s'] = round(time.monotonic()-started, 3)
    return result


def run(root, skip_probe=False):
    print('=== 폰 매매 지연 점검 · 읽기 전용 ===', flush=True)
    print('실행 중인 매매는 그대로 유지합니다. 약 10~30초 소요.', flush=True)
    start = service(root)
    ticks = []
    previous = time.monotonic()
    for _ in range(30):
        time.sleep(.2)
        current = time.monotonic()
        ticks.append(current-previous)
        previous = current
    probes = []
    if not skip_probe:
        for _ in range(3):
            try:
                done = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--public-probe'],
                                      capture_output=True, text=True, timeout=6, check=False)
                probes.append(json.loads(done.stdout) if done.returncode == 0 else {'ok': False, 'error_type': 'ProbeProcessExit'})
            except subprocess.TimeoutExpired:
                probes.append({'ok': False, 'error_type': 'ProbeDeadline6s'})
            except (ValueError, OSError):
                probes.append({'ok': False, 'error_type': 'ProbeUnavailable'})
    now = datetime.now(KST)
    end = service(root)
    report = {'version': VERSION, 'checked_kst': now.isoformat(timespec='seconds'),
              'service_start': start, 'service_end': end,
              'host_process': process(end.get('host_pid')),
              'diagnostic_process_max_interval_s': round(max(ticks), 3),
              'public_time_ipv4_probes': probes,
              'engine_log_last_hour': log_summary(read_bounded(root, LOGS[0]), now),
              'host_log_signal_counts_bounded_tail': dict(Counter(tag for line in read_bounded(root, LOGS[1]).splitlines() for tag in classify(line)))}
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print('화면의 계정 자료 나이와 계정 WS 수신 나이는 다른 값입니다.')
    print('최근 오류 기록이 없거나 공개 API가 빨라도 매매 연결 정상의 증명은 아닙니다.')
    print('스케줄 간격은 이 점검 프로세스 값이며 매매 엔진 지연을 직접 측정하지 않습니다.')
    print('host.log 신호는 과거 기록을 포함합니다. 원인 확정/수정 결과가 아닙니다.')
    print('=== 끝 · API 키/주문/설정/재시작 변경 없음 ===')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.home()/'okx-phone')
    parser.add_argument('--public-probe', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--skip-probe', action='store_true')
    args = parser.parse_args()
    if args.public_probe:
        print(json.dumps(public_probe()))
    else:
        run(args.root, args.skip_probe)
