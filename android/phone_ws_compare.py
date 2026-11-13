#!/usr/bin/env python3
"""Five-minute public WS control beside a running phone bot.

No engine imports, credentials, private API, orders, configuration changes or
signals to existing processes. One additional public connection at a time.
Only this diagnostic's child may be terminated at its deadline.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time

VERSION = 'phone-ws-compare-1'
KST = timezone(timedelta(hours=9))
HOST = 'ws.okx.com'
URL = 'wss://ws.okx.com/ws/v5/public'
CHANNELS = ('tickers', 'trades', 'books5', 'mark-price')
SYMBOL = 'AAVE-USDT-SWAP'


def stamp():
    return datetime.now(KST).isoformat(timespec='seconds')


def tail(root, relative, limit=524288):
    path = root / relative
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            return ''
        with path.open('rb') as f:
            f.seek(max(0, os.fstat(f.fileno()).st_size-limit))
            return f.read(limit).decode('utf-8', errors='replace')
    except OSError:
        return ''


def service(root):
    try:
        row = json.loads(tail(root, 'phone_service_status.json', 16384))
        if not isinstance(row, dict):
            return {}
    except ValueError:
        return {}
    result = {}
    for key in ('host_pid', 'host_restarts', 'remote_restarts'):
        value = row.get(key)
        result[key] = value if type(value) is int and value >= 0 else None
    for key in ('host_process_running', 'remote_process_running'):
        value = row.get(key)
        result[key] = value if type(value) is bool else None
    for key, choices in (('state', ('running', 'stopping', 'stopped')), ('mode', ('run', 'watch'))):
        result[key] = row.get(key) if row.get(key) in choices else 'unknown'
    observed = row.get('observed_at')
    result['record_age_s'] = round(time.time()-observed, 1) if type(observed) in (int, float) and math.isfinite(observed) else None
    return result


def engine_events(text, start, end):
    """Allowlist only. Do not echo log lines or infer channels from bare errors."""
    result = []
    for line in text.splitlines():
        match = re.match(r'^(\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s', line)
        if not match:
            continue
        try:
            dt = datetime.strptime(str(end.year)+'-'+match[1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST)
            if dt > end+timedelta(days=1):
                dt = dt.replace(year=dt.year-1)
        except ValueError:
            continue
        if not start <= dt <= end:
            continue
        tags = []
        for phrase in ('BrokenPipeError', 'WebSocketConnectionClosedException', 'WebSocketTimeoutException',
                       '계정 WS 스냅샷 지연', '공개 WS: 연결', '계정 WS: 수신 확인',
                       '연결·계정 대조', '진입 신호 대기', '연결 끊김/재연결'):
            if phrase in line:
                tags.append(phrase)
        for channel in ('공개', '계정'):
            for error in ('BrokenPipeError', 'WebSocketConnectionClosedException', 'WebSocketTimeoutException'):
                if channel+' WS: '+error in line:
                    tags.append(channel+' WS 오류 확인')
        for code in ('50011', '50040', '50102'):
            if re.search(r'\bOKX\s+'+code+r'\b', line):
                tags.append('OKX '+code)
        if tags:
            result.append({'time_kst': match[1], 'signals': tags})
    return result[-120:]


def close_category(data):
    """Record the close code, but never arbitrary peer text."""
    if not isinstance(data, bytes) or len(data) < 2:
        return None, 'no_reason'
    code = struct.unpack('!H', data[:2])[0]
    reason = data[2:].decode('utf-8', errors='replace').lower()
    category = 'other_redacted' if reason else 'no_reason'
    for words, label in ((('rate', 'too many'), 'rate_limit'),
                         (('timeout', 'idle'), 'timeout_or_idle'),
                         (('restart', 'upgrade', 'maintenance'), 'service_restart')):
        if any(word in reason for word in words):
            category = label
            break
    return code, category


def observer_class(websocket, metrics, mono=time.monotonic):
    class Observed(websocket.WebSocket):
        def recv_frame(self):
            frame = super().recv_frame()
            now = mono()
            previous = metrics.get('_last_frame', now)
            metrics['max_frame_gap_s'] = max(metrics.get('max_frame_gap_s', 0), now-previous)
            metrics['_last_frame'] = now
            metrics['frames'] = metrics.get('frames', 0)+1
            if frame.opcode == websocket.ABNF.OPCODE_CLOSE:
                metrics['close_code'], metrics['close_reason_category'] = close_category(frame.data)
            if frame.opcode == websocket.ABNF.OPCODE_PING:
                metrics['protocol_ping_frames'] = metrics.get('protocol_ping_frames', 0)+1
            return frame
    return Observed


def public_connect(websocket, cls):
    sock = None
    # IPv4 and verified TLS/SNI match the original Q2X public transport.
    for info in socket.getaddrinfo(HOST, 443, socket.AF_INET, socket.SOCK_STREAM):
        sock = socket.socket(info[0], info[1], info[2])
        sock.settimeout(5)
        try:
            sock.connect(info[4])
            break
        except OSError:
            sock.close()
            sock = None
    if sock is None:
        raise OSError('public_connect_failed')
    try:
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=HOST)
        ws = websocket.create_connection(URL, timeout=5, socket=sock, class_=cls,
                                         redirect_limit=0)
        ws.settimeout(1)
        return ws
    except BaseException:
        sock.close()
        raise


def observe_session(ws, metrics, until, websocket, mono=time.monotonic):
    args = [{'channel': channel, 'instId': SYMBOL} for channel in CHANNELS]
    metrics['stage'] = 'subscribe'
    ws.send(json.dumps({'op': 'subscribe', 'args': args}))
    last_ping = mono()
    pending_ping = None
    counts = Counter()
    metrics.update(text_ping_sent=0, text_pong_received=0, subscribe_acks=0)
    try:
        while mono() < until:
            now = mono()
            # Same 20-second ping policy as the running public-stream loop.
            if now-last_ping >= 20:
                metrics['stage'] = 'send_ping'
                ws.send('ping')
                metrics['text_ping_sent'] += 1
                if pending_ping is None:
                    pending_ping = now
                last_ping = now
            metrics['stage'] = 'receive'
            try:
                msg = ws.recv()
            except websocket.WebSocketTimeoutException:
                metrics['receive_timeouts'] = metrics.get('receive_timeouts', 0)+1
                continue
            if not msg:
                metrics['ended_by'] = 'peer_close'
                return
            if msg == 'pong':
                metrics['text_pong_received'] += 1
                if pending_ping is not None:
                    metrics['max_text_pong_wait_s'] = max(metrics.get('max_text_pong_wait_s', 0), mono()-pending_ping)
                    pending_ping = None
                continue
            metrics['stage'] = 'parse_public_message'
            obj = json.loads(msg)
            if obj.get('event') in ('error', 'notice'):
                code = str(obj.get('code', ''))
                if re.fullmatch(r'\d{1,8}', code):
                    metrics.setdefault('server_codes', []).append(code)
                    metrics['server_codes'] = metrics['server_codes'][-10:]
                if obj['event'] == 'error':
                    metrics['ended_by'] = 'server_error'
                    return
            if obj.get('event') == 'subscribe':
                metrics['subscribe_acks'] += 1
            channel = obj.get('arg', {}).get('channel')
            if channel in CHANNELS and obj.get('data'):
                counts[channel] += 1
        metrics['ended_by'] = 'diagnostic_duration'
    finally:
        metrics['messages_by_channel'] = dict(counts)
        metrics['pending_text_pong_age_s'] = round(mono()-pending_ping, 3) if pending_ping is not None else None


def worker(seconds):
    import websocket
    until = time.monotonic()+seconds
    attempts = []
    # Bounded, one connection at a time; no request loops or REST probes.
    while time.monotonic() < until and len(attempts) < 8:
        started = time.monotonic()
        metrics = {'started_kst': stamp(), 'stage': 'connect', 'frames': 0}
        ws = None
        try:
            cls = observer_class(websocket, metrics)
            ws = public_connect(websocket, cls)
            metrics['connected_kst'] = stamp()
            metrics['connect_seconds'] = round(time.monotonic()-started, 3)
            observe_session(ws, metrics, until, websocket)
        except Exception as error:
            metrics['error_type'] = type(error).__name__
            metrics['ended_by'] = 'exception'
        finally:
            metrics['ended_kst'] = stamp()
            metrics['duration_s'] = round(time.monotonic()-started, 3)
            last_frame = metrics.pop('_last_frame', None)
            metrics['last_frame_age_s'] = round(time.monotonic()-last_frame, 3) if last_frame is not None else None
            captured = dict(metrics)
            if ws is not None:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
            # Do not confuse our end-of-test close handshake with a peer failure.
            attempts.append(captured)
        if metrics.get('ended_by') == 'diagnostic_duration':
            break
        time.sleep(min(max(0, until-time.monotonic()), min(60, 10*2**(len(attempts)-1))))
    return {'websocket_client_version': str(websocket.__version__), 'attempts': attempts}


def boottime():
    try:
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        return time.monotonic()


def run(root, seconds):
    print('=== 공개 시세 연결 대조 · 매매 변경 없음 ===', flush=True)
    print('5분 동안 충전·와이파이·Termux 화면을 유지해 주세요. 공개 연결 1개만 추가합니다.', flush=True)
    start = datetime.now(KST)
    started = time.monotonic()
    initial = service(root)
    changes = []
    previous = initial
    gaps = []
    previous_tick = boottime()
    max_gap = 0
    report = {'version': VERSION, 'started_kst': start.isoformat(timespec='seconds'),
              'duration_requested_s': seconds, 'service_start': initial,
              'screen_state': 'not_measured', 'endpoint': URL, 'symbol': SYMBOL,
              'channels': CHANNELS, 'bot_or_credentials_imported': False}
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--worker', '--seconds', str(seconds)],
                                 stdout=output, stderr=subprocess.DEVNULL)
        next_progress = 30
        try:
            while child.poll() is None and time.monotonic()-started < seconds+30:
                time.sleep(1)
                current_tick = boottime()
                gap = current_tick-previous_tick
                previous_tick = current_tick
                max_gap = max(max_gap, gap)
                if gap >= 2:
                    gaps.append({'time_kst': stamp(), 'interval_s': round(gap, 3)})
                    gaps = gaps[-30:]
                current = service(root)
                fields = ('host_pid', 'host_restarts', 'remote_restarts', 'host_process_running', 'remote_process_running')
                if any(current.get(k) != previous.get(k) for k in fields):
                    changes.append({'time_kst': stamp(), **current})
                    changes = changes[-30:]
                previous = current
                if time.monotonic()-started >= next_progress:
                    print('대조 진행 '+str(min(seconds, int(time.monotonic()-started)))+'/'+str(seconds)+'초', flush=True)
                    next_progress += 30
        finally:
            if child.poll() is None:
                # Only this newly spawned diagnostic child. Never the trading PID.
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
                report['probe_deadline_exceeded'] = True
        output.seek(0)
        try:
            report['public_control'] = json.loads(output.read(131072))
        except ValueError:
            report['public_control'] = {'error_type': 'ProbeResultUnavailable', 'exit_code': child.returncode}
    end = datetime.now(KST)
    report.update(ended_kst=end.isoformat(timespec='seconds'), service_end=service(root),
                  service_changes=changes, diagnostic_max_interval_s=round(max_gap, 3),
                  diagnostic_gaps=gaps,
                  engine_events=engine_events(tail(root, 'runtime-q2x/bot_log.txt'), start, end))
    report['limitations'] = [
        '대조는 별도 프로세스·1종목이며 실제 봇의 전체 구독 부하와 다름',
        '대조 연결의 종료 코드이며 실제 봇 연결의 종료 코드는 아님',
        '일치/불일치만으로 와이파이·Android·거래소·코드 중 원인 확정 불가',
        '스케줄 간격은 점검 프로세스 값, 엔진 지연·화면 상태 측정 아님',
        '진입 차단 횟수는 로그 중복 가능, 수신·체결 정상 증명 아님']
    text = json.dumps(report, ensure_ascii=False, indent=2)
    target = Path.home()/'OKX_PHONE_WS_COMPARE_RESULT.json'
    if target.is_symlink():
        print('결과 파일이 링크여서 저장하지 않습니다.', flush=True)
    else:
        fd, name = tempfile.mkstemp(prefix='.okx-ws-report-', dir=target.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(text+'\n')
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        print('결과 저장: ~/OKX_PHONE_WS_COMPARE_RESULT.json', flush=True)
    print(text, flush=True)
    print('=== 끝 · 기존 매매/설정/로그인/프로세스 재시작 변경 없음 ===', flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.home()/'okx-phone')
    parser.add_argument('--seconds', type=int, default=300, choices=range(1, 601), metavar='1..600')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.worker:
        try:
            print(json.dumps(worker(options.seconds), ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({'error_type': type(exc).__name__}))
    else:
        run(options.root, options.seconds)
