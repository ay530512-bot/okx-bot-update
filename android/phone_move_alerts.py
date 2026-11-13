#!/usr/bin/env python3
"""Independent OKX public-price Telegram alerts. Never imports the trading bot.

Only GET public instruments/15m candles and POST Telegram sendMessage are allowed.
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

VERSION = 'phone-move-alerts-2-15m-10pct'
WINDOW = 900
THRESHOLD = 0.10
KST = timezone(timedelta(hours=9))
MARKER = '# OKX public move alerts v1 (independent of trading)'
BASE = 'https://openapi.okx.com'
ENDPOINTS = {'/api/v5/public/instruments?instType=SWAP'}
CANDLE_PATH = r'/api/v5/market/candles\?instId=[A-Z0-9]{1,24}-USDT-SWAP&bar=15m&limit=3'


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


def candle_signal(symbol, rows, target, now):
    """Return (confirmed target found, alert). Never use partial or older bars."""
    if target % WINDOW or not 0 <= now - (target + WINDOW) < WINDOW:
        return False, None
    for row in rows:
        try:
            if len(row) < 9 or str(row[8]) != '1' or int(row[0]) != target * 1000:
                continue
            opening, high, low, close = map(float, row[1:5])
            if not all(math.isfinite(p) and p > 0 for p in (opening, high, low, close)):
                continue
            if high < max(opening, close) or low > min(opening, close):
                continue
        except (IndexError, KeyError, ValueError, TypeError, OverflowError):
            continue
        change = close / opening - 1
        if abs(change) + 1e-12 < THRESHOLD:
            return True, None
        return True, dict(symbol=symbol, direction='up' if change > 0 else 'down',
                          change=change, price=close, baseline=opening,
                          start=target, end=target + WINDOW, detected_at=now)
    return False, None


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
    if path not in ENDPOINTS and not re.fullmatch(CANDLE_PATH, path):
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
    lines = ['[OKX 15분봉 ±10%] 확정봉 시가 → 종가 기준']
    for alert in alerts:
        label = '급등' if alert['direction'] == 'up' else '급락'
        start = datetime.fromtimestamp(alert['start'], KST).strftime('%m/%d %H:%M:%S')
        end = datetime.fromtimestamp(alert['end'], KST).strftime('%m/%d %H:%M:%S')
        lines.append(f"{label} {alert['symbol']} {alert['change']:+.2%}\n"
                     f"{alert['baseline']:.8g} → {alert['price']:.8g} USDT\n{start}~{end} KST")
    if omitted:
        lines.append(f'추가 {omitted}종은 다음 묶음으로 전송 대기 중')
    lines.append('시세 알림입니다. 자동 진입·청산 지시가 아닙니다.')
    return '\n\n'.join(lines)


def state_load(directory):
    path = directory / 'candle_state.json'
    state = read_json(path) if path.exists() else {'seen': {}}
    if not isinstance(state.get('seen'), dict):
        raise ValueError('알림 중복 방지 기록 확인 필요')
    return state


def reserve(state, alerts, now):
    for alert in alerts:
        state['seen'][alert['symbol'] + ':' + str(alert['start'])] = alert['end']
    state['seen'] = {k: v for k, v in state['seen'].items() if now - float(v) < 172800}


def eligible(state, alert, now):
    key = alert['symbol'] + ':' + str(alert['start'])
    return key not in state['seen'] and 0 <= now - alert['end'] < WINDOW


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
        state = state_load(directory)
        universe, instruments_seen, next_send, failures = set(), 0., 0., 0
        pending, retries, todo = {}, {}, deque()
        cycle, checked = None, 0
        def status(**fields):
            write_private(directory / 'status.json', dict(version=VERSION, pid=os.getpid(),
                checked_kst=datetime.now(KST).isoformat(), **fields))
        while not stop.is_set():
            delay = .5  # At most two sequential public candle requests/second.
            attempted_symbol = None
            try:
                if not read_json(directory / 'enabled.json').get('enabled'):
                    break
                token, chat = credentials(root)
                recipient = hashlib.sha256((token + ':' + chat).encode()).hexdigest()
                if state.get('recipient') not in (None, recipient):
                    raise ValueError('텔레그램 대상 변경 확인 필요')
                state['recipient'] = recipient
                if not universe or time.monotonic() - instruments_seen > 3600:
                    config = read_json(root / 'strategy_config.json')
                    excluded = set(config.get('selection', {}).get('stock_linked_symbols', []))
                    instruments = public('/api/v5/public/instruments?instType=SWAP')
                    universe = {i['instId'] for i in instruments if allowed(i, excluded)}
                    if not universe:
                        raise ValueError('암호화폐 시세 목록 확인 필요')
                    instruments_seen = time.monotonic()
                now = time.time()
                target = int(now // WINDOW) * WINDOW - WINDOW
                if target != cycle:
                    cycle, checked, retries, pending = target, 0, {}, {}
                    todo = deque(sorted(universe))
                if now < target + WINDOW + 3:
                    delay = 1
                elif todo:
                    symbol = todo[0]
                    attempted_symbol = symbol
                    # On errors, retain this symbol until backoff/retry or the next candle.
                    rows = public('/api/v5/market/candles?instId=' + symbol + '&bar=15m&limit=3')
                    now = time.time()
                    confirmed, alert = candle_signal(symbol, rows, target, now)
                    todo.popleft()
                    if not confirmed and retries.get(symbol, 0) < 1:
                        retries[symbol] = 1
                        todo.append(symbol)
                    if confirmed:
                        checked += 1
                    if alert and eligible(state, alert, now):
                        pending[symbol] = alert
                else:
                    delay = 5
                failures = 0
                now = time.time()
                pending = {k: a for k, a in pending.items()
                           if a['symbol'] in universe and eligible(state, a, now)}
                sent = state.get('last_delivery', 'none')
                if time.monotonic() >= next_send and (pending or not state.get('welcome_attempted')):
                    alerts = sorted(pending.values(), key=lambda a: (-abs(a['change']), a['symbol']))
                    batch = alerts[:20]
                    welcome = not state.get('welcome_attempted')
                    text = ('[15분봉 ±10% 알림 연결]\n암호화폐 USDT 무기한 전체\n'
                            '확정 15분봉의 시가 대비 종가 +10% 이상 / −10% 이하\n'
                            '동일 종목·동일 봉은 1회 · 종목별 순차 확인으로 전송 지연 가능\n'
                            '매매·진입·SL 설정은 변경하지 않았습니다.' if welcome else
                            message(batch, max(0, len(alerts) - 20)))
                    previous = dict(state['seen'])
                    state['welcome_attempted'] = True
                    if not welcome:
                        reserve(state, batch, now)
                    state['last_delivery'] = 'attempting'
                    write_private(directory / 'candle_state.json', state)
                    try:
                        sent, send_delay = telegram(token, chat, text)
                    except Exception:
                        sent, send_delay = 'unknown_delivery', 60
                    if sent in ('rate_limited', 'rejected'):
                        state['seen'] = previous
                        if welcome:
                            state['welcome_attempted'] = False
                    elif not welcome:
                        for alert in batch:
                            pending.pop(alert['symbol'], None)
                    state['last_delivery'] = sent
                    state['last_delivery_kst'] = datetime.now(KST).isoformat()
                    write_private(directory / 'candle_state.json', state)
                    next_send = time.monotonic() + send_delay
                status(state='scanning' if todo else 'waiting_next_candle',
                       universe=len(universe), confirmed_symbols=checked, remaining=len(todo),
                       candle_start=cycle, telegram=sent, scope='crypto_usdt_perpetuals',
                       bar='15m', threshold_percent=10, confirmed_only=True)
            except Exception as error:
                if attempted_symbol and todo and todo[0] == attempted_symbol and str(error) != 'public_rate_limit':
                    todo.popleft()
                    if retries.get(attempted_symbol, 0) < 1:
                        retries[attempted_symbol] = 1
                        todo.append(attempted_symbol)
                failures += 1
                delay = min(900, 30 * 2 ** min(failures - 1, 5))
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
            print('15분봉 ±10% 알림 실행 요청 완료 · 최근 확정봉부터 순차 확인합니다.')
            print('실제 텔레그램 연결 여부는 도착한 [15분봉 ±10% 알림 연결] 메시지로 확인하세요.')
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
        install_lock = directory / 'install.lock'
        if install_lock.is_symlink():
            raise ValueError('설치 잠금 링크 오류')
        with install_lock.open('a') as install_handle:
            fcntl.flock(install_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            credentials(root)
            read_json(root / 'strategy_config.json')
            source = Path(__file__).read_text(encoding='utf-8')
            target = directory / 'phone_move_alerts.py'
            if running(directory) and (not target.exists() or target.read_text(encoding='utf-8') != source):
                print('기존 급변 알림만 중지하고 15분봉 ±10% 기준으로 교체합니다.')
                write_private(directory / 'enabled.json', {'enabled': False})
                deadline = time.monotonic() + 30
                while running(directory) and time.monotonic() < deadline:
                    time.sleep(.25)
                if running(directory):
                    raise ValueError('기존 알림 종료를 확인하지 못했습니다. 강제 종료하지 않습니다.')
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
