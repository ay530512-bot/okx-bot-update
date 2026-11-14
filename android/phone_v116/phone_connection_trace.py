#!/usr/bin/env python3
"""Observe an existing engine; never reconnect, change freshness or place orders.

Transport errors/generations are sampled once per second. The connection lock
is acquired nonblocking. File I/O occurs only on this observer's daemon thread.
Recovery observations are captured before the original pipeline updates its
stored connection key. These are observations, not an atomic branch trace.
"""
from collections import deque
from datetime import datetime, timezone, timedelta
import json
import argparse
import math
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import time

VERSION = 'phone-connection-trace-2'
FILENAME = 'phone_connection_trace.json'
KST = timezone(timedelta(hours=9))
ERRORS = ('WebSocketConnectionClosedException', 'WebSocketTimeoutException',
          'BrokenPipeError', 'ConnectionResetError', 'ConnectionAbortedError',
          'PublicPeerClosed', 'TimeoutError', 'OSError', 'SSLError', 'gaierror', 'ValueError',
          'JSONDecodeError', 'RuntimeError', 'TypeError', 'KeyError')
LABELS = set(ERRORS) | {'other_redacted', 'public_subscription_rejected',
    'account_subscription_rejected', 'account_login_failed', 'manual_reconnect',
    'not_connected', 'connection_check', 'other_recovery', 'periodic_change',
    'pipeline_recovery', 'public_generation_changed', 'account_generation_changed',
    'public_disconnected', 'account_disconnected', 'account_snapshot_stale',
    'initial_connection_key', 'observation_changed_or_other_reason', VERSION,
    'phone-public-ws-1', 'waiting', 'dns', 'tcp', 'tls', 'handshake',
    'subscribe', 'unsubscribe', 'ping', 'receive', 'feed', 'closed'}


def numeric(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def error_label(value):
    if value is None:
        return None
    value = str(value)
    for known in ERRORS:
        if value == known:
            return known
    for prefix, label in (('공개 WS 구독 거절:', 'public_subscription_rejected'),
                          ('계정 WS 구독 오류:', 'account_subscription_rejected'),
                          ('계정 WS 로그인 실패:', 'account_login_failed')):
        if value.startswith(prefix):
            return label
    if value == '수동 재연결 중':
        return 'manual_reconnect'
    if value == '미연결':
        return 'not_connected'
    return 'other_redacted'


def connection_key(value):
    if isinstance(value, (tuple, list)) and len(value) == 2 and all(type(v) is int and v >= 0 for v in value):
        return list(value)
    return None


def error_code(value):
    match = re.fullmatch(r'(?:공개 WS 구독 거절|계정 WS 구독 오류|계정 WS 로그인 실패): (\d{1,8})', str(value))
    return int(match[1]) if match else None


def snapshot(engine, mono=time.monotonic):
    now = mono()
    stream = engine.stream
    public = {'lock_busy': True}
    if stream.lock.acquire(blocking=False):
        try:
            received = [item[1] for item in stream.data.values()
                        if isinstance(item, (tuple, list)) and len(item) >= 3
                        and item[2] == stream.generation and numeric(item[1]) is not None]
            public = dict(lock_busy=False, connected=bool(stream.connected),
                          generation=numeric(stream.generation), error=error_label(stream.error),
                          error_code=error_code(stream.error),
                          subscription_pairs=len(stream.active_pairs),
                          execution_symbols=len(stream.symbols), monitor_symbols=len(stream.monitor_symbols),
                          last_market_receive_age_s=round(now-max(received), 3) if received else None)
            transport = getattr(stream, '_public_transport', None)
            if isinstance(transport, dict):
                public['transport'] = {k: transport.get(k) for k in (
                    'version', 'stage', 'frames', 'text_pings', 'text_pongs',
                    'max_frame_gap_s', 'subscription_frames', 'last_subscription_bytes',
                    'disconnect_count')}
                last = transport.get('last_disconnect')
                public['transport']['last_disconnect'] = dict(last) if isinstance(last, dict) else None
                for source, dest in (('frame_at','frame_age_s'), ('pong_at','pong_age_s'),
                                     ('pending_ping_at','pending_ping_age_s')):
                    value = numeric(transport.get(source))
                    public['transport'][dest] = round(now-value, 3) if value is not None else None
        finally:
            stream.lock.release()
    account_stream = engine.account_stream
    received = numeric(account_stream.received)
    age = now-received if received and received > 0 else None
    account = dict(connected=bool(account_stream.connected),
                   generation=numeric(account_stream.generation), error=error_label(account_stream.error),
                   error_code=error_code(account_stream.error),
                   equity_seen=account_stream.equity is not None,
                   last_equity_receive_age_s=round(age, 3) if age is not None else None)
    account['fresh_at_observation'] = bool(account['connected'] and account['equity_seen'] and age is not None and age < 30)
    return dict(public=public, account=account,
                engine=dict(connection_key=connection_key(engine.connection_key),
                            recovering=bool(engine.recovering), good_snapshots=numeric(engine.good_snapshots),
                            entry_enabled=bool(engine.enabled), user_paused=bool(engine.user_paused),
                            entry_cancelled=bool(engine.entry_cancel.is_set())))


def triggers(value):
    public, account, engine = value['public'], value['account'], value['engine']
    result = []
    previous = engine['connection_key']
    if previous is None:
        result.append('initial_connection_key')
    else:
        for index, (name, row) in enumerate((('public', public), ('account', account))):
            if row.get('generation') is not None and previous[index] != row['generation']:
                result.append(name+'_generation_changed')
    if public.get('connected') is False:
        result.append('public_disconnected')
    if not account['connected']:
        result.append('account_disconnected')
    elif not account['fresh_at_observation']:
        result.append('account_snapshot_stale')
    return result or ['observation_changed_or_other_reason']


class Trace:
    def __init__(self, engine, root, mono=time.monotonic):
        self.engine, self.root, self.mono = engine, Path(root), mono
        self.events = deque(maxlen=120)
        self.pending = queue.Queue(maxsize=64)
        self.tick_started = None
        self.tick_last_s = None
        self.tick_max_s = 0
        self.tick_last_error = None
        self.samples = 0
        self.dropped = 0
        self.write_errors = 0
        self.last_signature = None
        self.last_sample = mono()
        self.max_sample_gap_s = 0
        self.latest = None
        self.thread = None

    def record(self, row):
        self.events.append(row)
        if row.get('reason_kind') != 'connection_check':
            return
        names = {'public_generation_changed':'공개 시세 재연결', 'account_generation_changed':'계정 연결 재연결',
                 'public_disconnected':'공개 시세 끊김', 'account_disconnected':'계정 연결 끊김',
                 'account_snapshot_stale':'계정 자료 지연', 'initial_connection_key':'최초 연결 대조',
                 'observation_changed_or_other_reason':'현재 관측만으로 원인 미확정'}
        reason = ' · '.join(names.get(label, '원인 미확정') for label in row.get('observed_triggers', []))
        public, account = row['public'], row['account']
        text = ('연결 원인 관측: '+reason+' / 공개 오류 '+str(public.get('error') or '없음')+
                ' / 계정 오류 '+str(account.get('error') or '없음')+
                ' / 계정 자료 '+str(account.get('last_equity_receive_age_s'))+'초')
        try:
            self.engine.events.put_nowait(('log', text))
        except Exception:
            pass

    def capture(self, kind, reason_kind=None):
        try:
            value = snapshot(self.engine, self.mono)
            row = dict(time_kst=datetime.now(KST).isoformat(timespec='seconds'), kind=kind, **value)
            if reason_kind:
                row['reason_kind'] = reason_kind
                if reason_kind == 'connection_check':
                    row['observed_triggers'] = triggers(value)
            self.pending.put_nowait(row)
        except Exception:
            self.dropped += 1

    def wrap(self):
        original_pipeline = self.engine.pipeline
        original_tick = self.engine.tick
        def pipeline(phase, reason='', count=None):
            # Observational failures cannot suppress or change original behavior.
            if phase == 'recovery':
                self.capture('pipeline_recovery', 'connection_check' if str(reason).startswith('공개 WS:') else 'other_recovery')
            return original_pipeline(phase, reason, count)
        def tick():
            self.tick_started = self.mono()
            self.tick_last_error = None
            try:
                return original_tick()
            except BaseException as error:
                self.tick_last_error = error_label(type(error).__name__)
                raise
            finally:
                self.tick_last_s = self.mono()-self.tick_started
                self.tick_max_s = max(self.tick_max_s, self.tick_last_s)
                self.tick_started = None
        self.engine.pipeline = pipeline
        self.engine.tick = tick

    def sample(self):
        now = self.mono()
        self.max_sample_gap_s = max(self.max_sample_gap_s, now-self.last_sample)
        self.last_sample = now
        self.samples += 1
        value = snapshot(self.engine, self.mono)
        public, account, engine = value['public'], value['account'], value['engine']
        signature = (public.get('generation'), public.get('connected'), public.get('error'),
                     account['generation'], account['connected'], account['error'],
                     account['fresh_at_observation'], engine['recovering'])
        if not public['lock_busy'] and signature != self.last_signature:
            self.record(dict(time_kst=datetime.now(KST).isoformat(timespec='seconds'),
                             kind='periodic_change', **value))
            self.last_signature = signature
        for _ in range(64):
            try:
                self.record(self.pending.get_nowait())
            except queue.Empty:
                break
        self.latest = value

    def document(self):
        tick_started, tick_last = self.tick_started, self.tick_last_s
        return dict(version=VERSION, host_pid=os.getpid(), observed_at=time.time(),
                    samples=self.samples, dropped_observations=self.dropped, write_errors=self.write_errors,
                    max_observer_gap_s=round(self.max_sample_gap_s, 3),
                    engine_tick=dict(active_age_s=round(self.mono()-tick_started, 3) if tick_started is not None else None,
                                     last_duration_s=round(tick_last, 3) if tick_last is not None else None,
                                     max_duration_s=round(self.tick_max_s, 3), last_error=self.tick_last_error),
                    latest=self.latest, events=list(self.events))

    def persist(self):
        target = self.root/FILENAME
        if target.is_symlink():
            raise ValueError('trace_link')
        data = json.dumps(self.document(), ensure_ascii=False, allow_nan=False).encode()
        fd, name = tempfile.mkstemp(prefix='.connection-trace-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def run(self):
        while not self.engine.stop_event.is_set():
            try:
                self.sample()
                if self.samples % 5 == 1:
                    self.persist()
            except Exception:
                self.write_errors += 1
            self.engine.stop_event.wait(1)


def install(engine, root):
    if getattr(engine, '_phone_connection_trace', None) is not None:
        return engine._phone_connection_trace
    observer = Trace(engine, root)
    observer.wrap()
    engine._phone_connection_trace = observer
    observer.thread = threading.Thread(target=observer.run, daemon=True, name='phone-connection-observer')
    observer.thread.start()
    return observer


REPORT_KEYS = set('transport frames text_pings text_pongs max_frame_gap_s subscription_frames last_subscription_bytes disconnect_count last_disconnect stage close_code frame_age_s pong_age_s pending_ping_age_s version host_pid observed_at samples dropped_observations write_errors max_observer_gap_s engine_tick active_age_s last_duration_s max_duration_s last_error latest events time_kst kind reason_kind observed_triggers public account engine lock_busy connected generation error error_code subscription_pairs execution_symbols monitor_symbols last_market_receive_age_s equity_seen last_equity_receive_age_s fresh_at_observation connection_key recovering good_snapshots entry_enabled user_paused entry_cancelled'.split())


def sanitized(value):
    if isinstance(value, dict):
        return {k: sanitized(v) for k, v in value.items() if k in REPORT_KEYS}
    if isinstance(value, list):
        return [sanitized(v) for v in value[-120:]]
    if value is None or type(value) is bool or numeric(value) is not None:
        return value
    if isinstance(value, str) and (value in LABELS or re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00', value)):
        return value
    return 'other_redacted'


def report(root, *, summary_only=False):
    target = Path(root)/FILENAME
    if target.is_symlink() or target.stat().st_size > 262144:
        raise ValueError('trace_file_invalid')
    row = json.loads(target.read_text())
    if row.get('version') != VERSION:
        raise ValueError('trace_version_invalid')
    result = sanitized(row)
    observed = numeric(row.get('observed_at'))
    result['record_age_s'] = round(time.time()-observed, 1) if observed is not None else None
    # Keep terminal output practical; the phone retains up to 120 events.
    result['events'] = result.get('events', [])[-12:]
    if summary_only:
        print(json.dumps({k: result[k] for k in ('version', 'host_pid', 'record_age_s', 'engine_tick', 'latest') if k in result}, ensure_ascii=False, indent=2))
        print('--- 최근 연결 관측 (행별 JSON) ---')
        for row in result['events']:
            print(json.dumps(row, ensure_ascii=False, separators=(',', ':')))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    print('실제 봇 관측값 · 원자적 연결 스냅샷 아님 · 기록 추가만으로 연결 장애 해결을 뜻하지 않습니다.')
    print('기록 파일만 읽었습니다. API 조회/주문/설정/재시작 변경 없음.')


def collect(root, seconds=600, mono=time.monotonic, wait=time.sleep):
    print('설치 단계 종료. 모바일에서 공개 시세 복구 v1 확인 → 실거래 시작 확인 후 평소처럼 사용하세요.', flush=True)
    print('추가 명령 없이 10분 후 실제 봇의 기록을 자동 출력합니다. 매매 시작은 자동으로 누르지 않습니다.', flush=True)
    end = mono()+seconds
    while mono() < end:
        wait(min(30, max(0, end-mono())))
    report(root, summary_only=True)


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('--collect', action='store_true')
        args = parser.parse_args()
        if args.collect:
            collect(Path.home()/'okx-phone')
        else:
            report(Path.home()/'okx-phone', summary_only=True)
    except Exception as error:
        print('연결 기록을 읽지 못했습니다:', type(error).__name__)
        raise SystemExit(1)
