#!/usr/bin/env python3
"""Independent OKX public-price Telegram alerts. Never imports the trading bot.

Only GET public instruments/tickers and POST Telegram sendMessage are allowed.
All mutable files live in ~/okx-phone/move-alerts-v1; existing bot files are read-only.
"""
import argparse
from collections import deque
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

VERSION = 'phone-move-alerts-1'
POLL, WINDOW, GAP, COOLDOWN = 15, 300, 45, 1800
THRESHOLD = 0.03
KST = timezone(timedelta(hours=9))
MARKER = '# OKX public move alerts v1 (independent of trading)'
BASE = 'https://openapi.okx.com'
ENDPOINTS = {'/api/v5/public/instruments?instType=SWAP',
             '/api/v5/market/tickers?instType=SWAP'}


def read_json(path):
    if path.is_symlink():
        raise ValueError('파일 링크를 사용할 수 없습니다.')
    return json.loads(path.read_text(encoding='utf-8'))


def write_private(path, value):
    if path.is_symlink():
        raise ValueError('파일 링크를 사용할 수 없습니다.')
    fd, name = tempfile.mkstemp(prefix='.alert-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def credentials(root):
    data = read_json(root / 'phone_notifications.json')
    token, chat = data.get('TELEGRAM_BOT_TOKEN', ''), data.get('TELEGRAM_CHAT_ID', '')
    if (not isinstance(token, str) or not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token)
            or not isinstance(chat, str) or not re.fullmatch(r'-?\d+|@[A-Za-z0-9_]{5,}', chat)):
        raise ValueError('기존 텔레그램 토큰/대화 ID 설정을 확인하세요.')
    return token, chat


def allowed(instrument, excluded):
    symbol = instrument.get('instId', '')
    return (bool(re.fullmatch(r'[A-Z0-9]{1,24}-USDT-SWAP', symbol))
            and symbol not in excluded and instrument.get('state') == 'live'
            and instrument.get('instCategory') == '1' and instrument.get('groupId') != '6'
            and instrument.get('settleCcy') == 'USDT' and instrument.get('ctType') == 'linear'
            and instrument.get('ctValCcy') == symbol.split('-')[0])


class Detector:
    def __init__(self):
        self.history = {}

    def sample(self, row, now):
        try:
            symbol, stamp, price = row['instId'], int(row['ts']) / 1000, float(row['last'])
            if not math.isfinite(price) or price <= 0 or not -5 <= now - stamp <= 30:
                return None
        except (KeyError, ValueError, TypeError, OverflowError):
            return None
        series = self.history.setdefault(symbol, deque())
        if series and stamp <= series[-1][0]:
            return None  # duplicate / out-of-order exchange snapshots
        if series and stamp - series[-1][0] > GAP:
            series.clear()  # never bridge an outage
        series.append((stamp, price))
        target = stamp - WINDOW
        while len(series) > 1 and series[1][0] <= target:
            series.popleft()
        if not series or not 0 <= target - series[0][0] <= 30:
            return None
        change = price / series[0][1] - 1
        if abs(change) + 1e-12 < THRESHOLD:
            return None
        return dict(symbol=symbol, direction='up' if change > 0 else 'down',
                    change=change, price=price, baseline=series[0][1],
                    start=series[0][0], end=stamp, detected_at=now)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_json(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={
        'User-Agent': VERSION, 'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=8) as response:
            return response.status, json.loads(response.read(4_000_000))
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read(32_768))
        except Exception:
            body = {}
        return error.code, body


def public(path):
    if path not in ENDPOINTS:
        raise ValueError('공개 시세 주소만 허용합니다.')
    status, body = request_json(BASE + path)
    if status != 200 or body.get('code') != '0' or not isinstance(body.get('data'), list):
        raise RuntimeError('public_rate_limit' if status == 429 or body.get('code') == '50011'
                           else 'public_unavailable')
    return body['data']


def telegram(token, chat, text):
    status, body = request_json('https://api.telegram.org/bot' + token + '/sendMessage',
                                {'chat_id': chat, 'text': text})
    if status == 200 and body.get('ok') is True:
        return 'sent', 60
    if status == 429 or body.get('error_code') == 429:
        try:
            delay = max(60, int(body.get('parameters', {}).get('retry_after', 60)))
        except (TypeError, ValueError, OverflowError):
            delay = 60
        return 'rate_limited', delay
    return 'rejected', 60  # never log the token-bearing URL / response


def message(alerts, omitted=0):
    lines = ['[OKX 급등·급락 감지] 가격 기준 · 최근 약 5분']
    for alert in alerts:
        label = '급등' if alert['direction'] == 'up' else '급락'
        start = datetime.fromtimestamp(alert['start'], KST).strftime('%m/%d %H:%M:%S')
        end = datetime.fromtimestamp(alert['end'], KST).strftime('%m/%d %H:%M:%S')
        lines.append(f"{label} {alert['symbol']} {alert['change']:+.2%}\n"
                     f"{alert['baseline']:.8g} → {alert['price']:.8g} USDT\n{start}~{end} KST")
    if omitted:
        lines.append(f'동시 감지 {omitted}종 추가 · 변동률 상위 20종만 표시')
    lines.append('시세 알림입니다. 자동 진입·청산 지시가 아닙니다.')
    return '\n\n'.join(lines)


def state_load(directory):
    path = directory / 'state.json'
    state = read_json(path) if path.exists() else {'cooldown': {}}
    if not isinstance(state.get('cooldown'), dict):
        raise ValueError('알림 중복 방지 기록 확인 필요')
    return state


def reserve(state, alerts, now):
    for alert in alerts:
        state['cooldown'][alert['symbol'] + ':' + alert['direction']] = now
    state['cooldown'] = {k: v for k, v in state['cooldown'].items() if now - float(v) < COOLDOWN}


def eligible(state, alert, now):
    key = alert['symbol'] + ':' + alert['direction']
    previous = state['cooldown'].get(key)
    return previous is None or now - float(previous) >= COOLDOWN


def running(directory):
    path = directory / 'process.lock'
    if path.is_symlink():
        raise ValueError('잠금 파일 링크 오류')
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True


def run(root, directory):
    path = directory / 'process.lock'
    if path.is_symlink():
        raise ValueError('잠금 파일 링크 오류')
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        import threading
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *args: stop.set())
        signal.signal(signal.SIGINT, lambda *args: stop.set())
        detector, state = Detector(), state_load(directory)
        universe, instruments_seen, next_send, failures = set(), 0., 0., 0
        pending = {}
        def status(**fields):
            write_private(directory / 'status.json', dict(version=VERSION, pid=os.getpid(),
                checked_kst=datetime.now(KST).isoformat(), **fields))
        while not stop.is_set():
            began = time.monotonic()
            try:
                if not read_json(directory / 'enabled.json').get('enabled'):
                    break
                token, chat = credentials(root)
                recipient = hashlib.sha256((token + ':' + chat).encode()).hexdigest()
                if state.get('recipient') not in (None, recipient):
                    raise ValueError('텔레그램 대상 변경 확인 필요')
                state['recipient'] = recipient
                if not universe or began - instruments_seen > 3600:
                    config = read_json(root / 'strategy_config.json')
                    excluded = set(config.get('selection', {}).get('stock_linked_symbols', []))
                    instruments = public('/api/v5/public/instruments?instType=SWAP')
                    universe = {i['instId'] for i in instruments if allowed(i, excluded)}
                    if not universe:
                        raise ValueError('암호화폐 시세 목록 확인 필요')
                    instruments_seen = began
                    detector.history = {s: h for s, h in detector.history.items() if s in universe}
                    pending = {k: a for k, a in pending.items() if a['symbol'] in universe}
                rows = public('/api/v5/market/tickers?instType=SWAP')
                now = time.time()
                fresh = 0
                for row in rows:
                    if row.get('instId') not in universe:
                        continue
                    alert = detector.sample(row, now)
                    if alert and eligible(state, alert, now):
                        pending[(alert['symbol'], alert['direction'])] = alert
                    try:
                        fresh += -5 <= now - int(row['ts']) / 1000 <= 30
                    except (TypeError, KeyError, ValueError):
                        pass
                if not fresh:
                    raise RuntimeError('fresh_quotes_unavailable')
                failures = 0
                pending = {k: a for k, a in pending.items() if now - a['detected_at'] <= 60
                           and eligible(state, a, now)}
                sent = state.get('last_delivery', 'none')
                if time.monotonic() >= next_send and (pending or not state.get('welcome_attempted')):
                    alerts = sorted(pending.values(), key=lambda a: (-abs(a['change']), a['symbol']))
                    welcome = not state.get('welcome_attempted')
                    text = ('[급등·급락 알림 연결]\n암호화폐 USDT 무기한 전체 · 약 5분 가격 ±3%\n'
                            '같은 종목·방향 30분 중복 제한 · 첫 5분 시세 수집 중\n'
                            '매매 실행기·진입·SL 설정은 변경하지 않았습니다.' if welcome else
                            message(alerts[:20], max(0, len(alerts) - 20)))
                    # Persist before sending: an ambiguous network failure must not spam on restart.
                    previous = dict(state['cooldown'])
                    state['welcome_attempted'] = True
                    if not welcome:
                        reserve(state, alerts, now)
                    state['last_delivery'] = 'attempting'
                    write_private(directory / 'state.json', state)
                    try:
                        sent, delay = telegram(token, chat, text)
                    except Exception:
                        sent, delay = 'unknown_delivery', 60
                    if sent in ('rate_limited', 'rejected'):
                        state['cooldown'] = previous  # known rejected request; safe to retry while fresh
                        if welcome:
                            state['welcome_attempted'] = False
                    elif not welcome:
                        pending.clear()
                    state['last_delivery'] = sent
                    state['last_delivery_kst'] = datetime.now(KST).isoformat()
                    write_private(directory / 'state.json', state)
                    next_send = time.monotonic() + delay
                status(state='monitoring', universe=len(universe), fresh_quotes=fresh,
                       history_symbols=len(detector.history), telegram=sent,
                       scope='crypto_usdt_perpetuals', minimum_warmup_seconds=WINDOW)
                delay = max(1, POLL - (time.monotonic() - began))
            except Exception as error:
                failures += 1
                delay = min(900, 30 * 2 ** min(failures - 1, 5))
                # Exception text may contain credentials; only fixed class names are persisted.
                status(state='retry_wait', error_type=type(error).__name__, retry_seconds=delay)
            until = time.monotonic() + delay
            while not stop.is_set() and time.monotonic() < until:
                if not read_json(directory / 'enabled.json').get('enabled'):
                    stop.set()
                    break
                stop.wait(min(1, max(0, until - time.monotonic())))
        status(state='stopped')


def start(root, directory):
    if running(directory):
        print('급등·급락 알림이 이미 실행 중입니다. 중복 실행하지 않습니다.')
        return
    command = [sys.executable, '-B', str(directory / 'phone_move_alerts.py'), '--run', '--root', str(root)]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    for _ in range(20):
        if running(directory):
            print('급등·급락 알림 실행 요청 완료 · 첫 5분 시세 수집 후 감지합니다.')
            print('실제 텔레그램 연결 여부는 도착한 [급등·급락 알림 연결] 메시지로 확인하세요.')
            return
        time.sleep(.1)
    raise RuntimeError('알림 프로세스 시작 확인 실패 · --status로 확인하세요.')


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ('install', 'run', 'start', 'stop', 'status'):
        group.add_argument('--' + name, action='store_true')
    parser.add_argument('--root', type=Path, default=Path.home() / 'okx-phone')
    args = parser.parse_args()
    root = args.root.expanduser().absolute()
    directory = root / 'move-alerts-v1'
    if not root.is_dir() or root.is_symlink() or directory.is_symlink():
        raise ValueError('기존 폰 실행 폴더를 확인하세요.')
    directory.mkdir(mode=0o700, exist_ok=True)
    os.umask(0o077)
    if args.install:
        credentials(root)
        read_json(root / 'strategy_config.json')
        source = Path(__file__).read_text(encoding='utf-8')
        target = directory / 'phone_move_alerts.py'
        if running(directory) and (not target.exists() or target.read_text(encoding='utf-8') != source):
            raise ValueError('기존 알림을 --stop으로 중지한 뒤 다시 설치하세요.')
        write_private(target, source)
        boot = Path.home() / '.termux' / 'boot'
        if boot.is_symlink() or boot.parent.is_symlink():
            raise ValueError('자동 시작 폴더 링크 오류')
        boot.mkdir(parents=True, exist_ok=True)
        hook = boot / '95-okx-move-alerts'
        if hook.exists() and MARKER not in hook.read_text():
            raise ValueError('동일 이름의 다른 자동 시작 파일이 있습니다.')
        command = shlex.join([sys.executable, '-B', str(target), '--start', '--root', str(root)])
        write_private(hook, '#!/data/data/com.termux/files/usr/bin/sh\n' + MARKER + '\n' + command + '\n')
        hook.chmod(0o700)
        write_private(directory / 'enabled.json', {'enabled': True})
        print('알림 추가 설치 완료 · 기존 매매 파일/주문/SL/실행 프로세스 유지')
        start(root, directory)
    elif args.run:
        run(root, directory)
    elif args.start:
        if read_json(directory / 'enabled.json').get('enabled'):
            start(root, directory)
    elif args.stop:
        write_private(directory / 'enabled.json', {'enabled': False})
        print('알림 중지 예약 완료 · 진행 중인 조회/전송 종료 후 중지합니다. 매매는 유지됩니다.')
    else:
        status_path = directory / 'status.json'
        state = read_json(status_path) if status_path.exists() else {'state': 'not_started'}
        state['process_running'] = running(directory)
        print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        # No raw URL/response/credential disclosure even on a TLS/network error.
        print('알림 설정 실패: ' + type(error).__name__ + ' · 기존 매매에는 변경이 없습니다.')
        sys.exit(1)
