#!/usr/bin/env python3
"""Android headless host. Default = read-only; first ownership requires flat account.

Does not remotely verify/stop a PC. --takeover requires the operator to stop it.
Owned restarts retain Q2X's journal and original recovery/continuity semantics.
"""
import argparse
import copy
import fcntl
import getpass
import hashlib
import importlib.abc
import json
import os
import queue
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

from phone_account import atomic_private, save_json, validate_keys, readonly_client, validate_config, finite

VERSION = 'phone-host-3'
PORT = 8768
ACK = 'PC 종료 완료'
KST = timezone(timedelta(hours=9))


class NoTk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'tkinter' or fullname.startswith('tkinter.') or fullname == '_tkinter':
            raise ImportError('Android host must not load Tk')


def read_json(path):
    if path.is_symlink():
        raise ValueError('symbolic link rejected')
    return json.loads(path.read_text(encoding='utf-8'))


def verified_installation(root):
    pinned = read_json(Path(__file__).with_name('phone_sources.json'))
    meta = read_json(root / 'phone_installation.json')
    if meta.get('source_files') != pinned['files']:
        raise ValueError('Q2X 원본 파일 목록 불일치')
    source = Path(meta['source_path'])
    if source.is_symlink():
        raise ValueError('source link rejected')
    for relative, expected in pinned['files'].items():
        p = source / relative
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('Q2X 원본이 변경되었습니다.')
    for p in source.rglob('*'):
        rel = p.relative_to(source)
        if p.is_symlink() or (p.is_file() and '__pycache__' not in rel.parts and rel.as_posix() not in pinned['files']):
            raise ValueError('Q2X 원본 폴더에 추가 파일이 있습니다.')
    sys.path.insert(0, str(source))
    sys.meta_path.insert(0, NoTk())
    validate_config(root, meta['config_sha256'])
    from phone_clock import install
    install()  # After original-source verification, before any API client.
    return source, dict(source_sha256=pinned['archive_sha256'], config_sha256=meta['config_sha256'])


def identity(snapshot):
    cfg = snapshot['config']
    if str(cfg.get('acctLv')) != '2' or cfg.get('posMode') != 'long_short_mode':
        raise ValueError('계정 모드 불일치 · 자동 변경하지 않습니다.')
    uid = str(cfg.get('uid') or '')
    if not uid:
        raise ValueError('계정 식별값을 확인할 수 없습니다.')
    return hashlib.sha256(('okx:' + uid).encode()).hexdigest()


def checkpoint(api):
    snap = api.snapshot()
    account = identity(snap)
    algos = api.pending_algos(full=True)
    n = sum(finite(p.get('pos', '0')) != 0 for p in snap['positions'])
    counts = dict(positions=n, orders=len(snap['orders']), algos=len(algos))
    if any(counts.values()):
        raise ValueError('전환 보류: 보유 {positions} / 미체결 {orders} / 조건주문 {algos}. PC에서 계속 관리하세요.'.format(**counts))
    return account


def prepare_runtime(root, pins):
    runtime = root / 'runtime-q2x'
    if runtime.is_symlink():
        raise ValueError('runtime link rejected')
    runtime.mkdir(mode=0o700, exist_ok=True)
    original = (root / 'strategy_config.json').read_bytes()
    if hashlib.sha256(original).hexdigest() != pins['config_sha256']:
        raise ValueError('사용자 설정 변경 감지')
    target = runtime / 'strategy_config.json'
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.read_bytes() != original:
            raise ValueError('폰 실행 설정 불일치 · 덮어쓰지 않습니다.')
    else:
        atomic_private(target, original)
    return runtime


def take_ownership(root, runtime, api, pins, ack, wait=time.sleep):
    if ack != ACK:
        raise ValueError('PC 종료 확인 문구가 일치하지 않습니다.')
    marker = root / 'phone_owner.json'
    if marker.exists() or marker.is_symlink():
        raise ValueError('이미 폰 전환 기록이 있습니다. --run을 사용하세요.')
    # Never turn an orphaned journal into a fresh session.
    if any(p.name != 'strategy_config.json' for p in runtime.iterdir()):
        raise ValueError('기존 실행 기록이 있어 신규 전환을 중지했습니다. 파일을 삭제하지 마세요.')
    first = checkpoint(api)
    wait(2)
    second = checkpoint(api)
    if first != second:
        raise ValueError('전환 조회 중 계정 변경')
    record = dict(version=VERSION, **pins, account_sha256=first,
                  operator_confirmed_pc_stopped=True, pc_remotely_verified=False,
                  first_start_pending=True,
                  created_at=datetime.now(KST).isoformat())
    save_json(marker, record)
    return record


def verify_owner(root, pins, snapshot):
    owner = read_json(root / 'phone_owner.json')
    for key, value in pins.items():
        if owner.get(key) != value:
            raise ValueError('폰 전환 당시 소스/설정과 다릅니다.')
    if owner.get('account_sha256') != identity(snapshot):
        raise ValueError('폰 운용 계정 불일치')
    return owner


def verify_restart_journal(runtime, snapshot):
    path = runtime / 'bot_state.json'
    if not path.exists():
        raise ValueError('폰 운용 기록이 없습니다. 새 기록으로 덮어쓰지 않습니다.')
    journal = read_json(path)
    account = hashlib.sha256(str(snapshot['config']['uid']).encode()).hexdigest()
    if journal.get('account') and journal['account'] != account:
        raise ValueError('폰 주문 기록의 계정이 다릅니다.')
    if any(p.is_symlink() for p in runtime.rglob('*')):
        raise ValueError('폰 실행 폴더의 파일 링크를 확인하세요.')


def verify_service_start(root, runtime, api, pins):
    """A fresh handover may precede first engine construction; never reset old data."""
    snap = api.snapshot()
    owner = verify_owner(root, pins, snap)
    if (runtime/'bot_state.json').exists():
        verify_restart_journal(runtime, snap)
        return
    if not owner.get('first_start_pending'):
        raise ValueError('폰 운용 기록이 없습니다. 새 기록으로 덮어쓰지 않습니다.')
    if any(p.name != 'strategy_config.json' for p in runtime.iterdir()):
        raise ValueError('최초 기동 전 기존 실행 기록을 확인해야 합니다. 삭제하지 마세요.')
    if checkpoint(api) != owner['account_sha256']:
        raise ValueError('최초 기동 계정 불일치')


def remote_host(root):
    path = root/'phone_remote.json'
    if not path.exists():
        return ''
    from phone_remote import valid_host
    value = read_json(path)
    name = value.get('https_host', '')
    if not valid_host(name) or value.get('public_access') is not False or value.get('transport') != 'private-tailscale-serve':
        raise ValueError('폰 원격 주소 설정 오류')
    return name


def auth_config(root, module):
    path = root / 'phone_access.json'
    if path.exists():
        value = read_json(path)
        if not module.valid_config(dict(value, https_host='')):
            raise ValueError('폰 화면 암호 설정 오류')
        return dict(value, https_host='')
    print('폰 화면에 사용할 비밀번호를 정하세요 (8자 이상, 입력 중 화면에 표시되지 않음).', flush=True)
    first = getpass.getpass('비밀번호: ')
    second = getpass.getpass('한 번 더: ')
    if first != second or not 8 <= len(first) <= 128:
        raise ValueError('비밀번호가 다르거나 8자 미만입니다.')
    value = dict(module.credential(first), https_host='')
    save_json(path, value)
    return value


def notification_settings(root, configure=False):
    path = root / 'phone_notifications.json'
    if configure:
        if (root / 'phone_owner.json').exists():
            raise ValueError('운용 시작 후 알림 대상 변경은 기존 기록 대조가 필요합니다.')
        token = getpass.getpass('Telegram Bot Token (폰에만 저장): ').strip()
        chat = getpass.getpass('Telegram Chat ID (폰에만 저장): ').strip()
        if not token or not chat or len(token) > 256 or len(chat) > 128:
            raise ValueError('알림 입력값을 확인하세요.')
        save_json(path, dict(TELEGRAM_BOT_TOKEN=token, TELEGRAM_CHAT_ID=chat))
    data = read_json(path) if path.exists() else {}
    if set(data) - {'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'} or any(not isinstance(v, str) for v in data.values()):
        raise ValueError('알림 설정 오류')
    return data


class View:
    def __init__(self, cfg, watch):
        self.watch = watch
        self.state = dict(chart_indicators=cfg.get('indicators', {}), live=False,
                          pause_reason='PC 운용 중 · 폰은 조회만 합니다.' if watch else '폰 계정·보호 주문 확인 중')
        self.positions = []
        self.activities = deque(maxlen=300)
        self.data_seen = 0
        self.update_notice = {}
        self.live_cache = {}

    def add(self, text):
        self.activities.appendleft((datetime.now(KST).strftime('%H:%M:%S'), str(text), None))

    def running_state(self):
        s = self.state
        if s.get('resume_pending'):
            return '폰 자동 재개 대기 · 계정/주문/SL 대조 중', ''
        if s.get('live'):
            ready = not s.get('recovering') and s.get('market_connected') and s.get('account_connected')
            return ('폰 실거래 가동 중' if ready else '폰 재연결·계정 확인 중'), ''
        return s.get('pause_reason') or '폰 신규 진입 중지 · 기존 보유분 관리', ''

    def receive(self, kind, value):
        if kind == 'position_live':
            from okx_live_display732 import apply_position
            row = value.get('row', {})
            self.live_cache[(row.get('instId'), row.get('posSide'))] = value
            self.live_cache = {k: v for k, v in self.live_cache.items() if int(time.time()*1000) - v.get('received_ms', 0) <= 5000}
            apply_position(self.positions, value)
        elif kind == 'dashboard':
            self.data_seen = time.monotonic()
            self.state.update({k: v for k, v in value.items() if k != 'positions'})
            self.positions = copy.deepcopy(value.get('positions', []))
            from okx_live_display732 import apply_position
            for event in self.live_cache.values():
                apply_position(self.positions, event)
        elif kind in ('status', 'entry_control', 'session_ui'):
            self.state.update(value)
        elif kind == 'click_gate':
            self.state['entry_gate'] = value
        elif kind == 'futures_market_error':
            self.state.setdefault('futures_market', {})['stale'] = True
            if self.watch:
                self.state['market_connected'] = False
        elif kind == 'futures_market':
            self.state[kind] = value
            if self.watch:
                self.state['market_connected'] = not value.get('stale', True)
        elif kind in ('connection_reset', 'error'):
            self.state.update(recovering=True, market_connected=False, account_connected=False)
            if kind == 'error':
                self.add(value)
        elif kind in ('log', 'decision', 'click_result'):
            self.add((value.get('text') or value.get('message') or str(value)) if isinstance(value, dict) else value)
            if kind == 'click_result' and 'entry_gate' in value:
                self.state['entry_gate'] = value['entry_gate']
        elif kind == 'v5mode':
            self.state.update(recovering=bool(value.get('recovering')), ended=bool(value.get('ended')))
        else:
            self.state[kind] = value


def watch_once(api, view):
    from okx_dashboard_data import dashboard_snapshot
    snap = api.snapshot()
    identity(snap)
    algos = api.pending_algos(full=True)
    rows = dashboard_snapshot(snap, [], None, False, True, False)
    for p in rows['positions']:
        p.update(source='PC', phase='폰 조회만', close_key=None,
                 reason='폰에서 관리하지 않는 보유분 · PC를 유지하세요.')
    view.receive('status', dict(equity=str(snap['equity']), available=str(snap['available']),
                               live=False, user_paused=True,
                               pause_reason=f"폰 조회 모드 · 보유 {len(rows['positions'])} / 미체결 {len(snap['orders'])} / 조건주문 {len(algos)} · 아직 PC를 끄지 마세요."))
    view.receive('dashboard', rows)


def route_control(engine, command, mobile):
    if command['op'] not in {'prepare', 'confirm', 'pause', 'entry', 'close_one', 'close_all'}:
        mobile.complete_control(dict(request_id=command['request_id'], owner=command['owner'],
                                     status='failed', message='지원하지 않는 폰 명령입니다.'))
        return
    cmd = dict(command)
    if cmd['op'] == 'prepare':
        cmd['budget'] = engine.budget
    engine.send('mobile_control', **cmd)


def serve(root, runtime, source, settings, access, run_engine):
    from phone_mobile import mobile_module
    from okx_market716 import MarketFeed
    module = mobile_module(source)
    cfg = read_json(runtime / 'strategy_config.json')
    events = queue.Queue()
    view = View(cfg, watch=not run_engine)
    mobile = module.PhoneMobile(runtime, settings, dict(access, https_host=remote_host(root), controls_enabled=run_engine), port=PORT)
    engine = None
    api = None
    # Read-only watch never constructs a RuleEngine or private WS.
    if run_engine:
        from okx_v5 import RuleEngine
        engine = RuleEngine(runtime, settings, events)
        owner = read_json(root/'phone_owner.json')
        if owner.get('first_start_pending'):
            if not (runtime/'bot_state.json').is_file():
                raise ValueError('최초 운용 기록 저장을 확인하지 못했습니다.')
            owner['first_start_pending'] = False
            save_json(root/'phone_owner.json', owner)
    else:
        api = readonly_client({k: settings[k] for k in ('OKX_API_KEY', 'OKX_SECRET_KEY', 'OKX_PASSPHRASE')})
    market = MarketFeed(settings, events)
    stop_requested = threading.Event()
    previous = {s: signal.signal(s, lambda *_: stop_requested.set()) for s in (signal.SIGINT, signal.SIGTERM)}
    mobile.start()
    market.start()
    if engine:
        engine.start()
    print(f'\n폰 Chrome: http://127.0.0.1:{PORT}', flush=True)
    print(('폰 관리 시작 · 기존 실행 기록이 있으면 Q2X 복구 확인 후 자동 재개할 수 있습니다.' if args_resume(engine) else '폰 관리 시작 · 홈의 실거래 시작에서 확인 후 활성화합니다.') if engine else '조회 모드 · PC와 주문은 변경하지 않습니다.', flush=True)
    if not settings.get('TELEGRAM_BOT_TOKEN'):
        view.add('폰 Telegram 알림 미설정 · Termux --telegram에서 설정할 수 있습니다(최초 전환 전).')
    next_check = 0
    next_remote = 0
    quitting = False
    done = False
    try:
        while not done:
            if time.monotonic() >= next_remote:
                next_remote = time.monotonic() + 5
                try:
                    mobile.set_remote(remote_host(root))
                except Exception:
                    mobile.set_remote('')
            if stop_requested.is_set():
                stop_requested.clear()
                if engine:
                    engine.send('pause')
                    engine.send('quit')
                    # Q2X serial worker blocks quit if owned positions still exist.
                    print('신규 진입 중지 요청 · 보유분이 있으면 보호 관리를 계속합니다.', flush=True)
                    quitting = True
                    mobile.config['controls_enabled'] = False
                else:
                    break
            if api and time.monotonic() >= next_check:
                next_check = time.monotonic() + 15
                try:
                    watch_once(api, view)
                except Exception:
                    view.receive('error', '폰 계정 조회 지연 · 연결을 확인하세요. PC는 계속 관리합니다.')
            for _ in range(200):
                try:
                    kind, value = events.get_nowait()
                except queue.Empty:
                    break
                if kind == 'quit':
                    done = True
                elif kind == 'mobile_control_result':
                    if value.get('status') == 'prepared':
                        value = copy.deepcopy(value)
                        value['summary'] += [['진입 경로', '기존15m OR 두꼬리'], ['Q2X 추가 보호', '15분 확정 긴꼬리 반전 + 비용 반영 잔량 수익 시 청산'], ['실행 위치', '이 폰 · PC 프로그램은 계속 종료 상태로 유지'], ['폰 동작 확인', '실기기 장시간 운용·주문 및 보호 복구는 아직 미검증']]
                    mobile.complete_control(value)
                else:
                    try:
                        view.receive(kind, value)
                    except Exception:
                        view.add('화면 자료 표시 지연 · 주문 관리는 별도 실행 중입니다.')
            for _ in range(16):
                try:
                    command = mobile.control_commands.get_nowait()
                except queue.Empty:
                    break
                if engine and not quitting:
                    route_control(engine, command, mobile)
                else:
                    mobile.complete_control(dict(request_id=command['request_id'], owner=command['owner'], status='failed', message='조회 또는 종료 대기 상태입니다.'))
            try:
                mobile.capture(view)
            except Exception:
                # Presentation failure must never tear down a managing engine.
                pass
            time.sleep(.1)
    finally:
        market.stop()
        mobile.stop()
        if api:
            api.session.close()
        for s, handler in previous.items():
            signal.signal(s, handler)


def args_resume(engine):
    return bool(engine and getattr(engine, 'resume_pending', False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.home() / 'okx-phone')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--takeover', action='store_true')
    modes.add_argument('--run', action='store_true')
    modes.add_argument('--telegram', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root.resolve(strict=True)
    # Lock held for this process lifetime; no second phone worker.
    lock_path = root / 'phone_host.lock'
    if lock_path.is_symlink():
        raise ValueError('lock link rejected')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('폰 실행기가 이미 켜져 있습니다.')
        if (root / 'phone_owner.json').exists() and not (args.takeover or args.run or args.telegram):
            raise ValueError('이미 폰으로 전환했습니다. 보호 관리를 재개하려면 같은 명령에 --run을 붙이세요.')
        source, pins = verified_installation(root)
        keys = validate_keys(read_json(root / 'phone_credentials.json'))
        from phone_mobile import mobile_module
        access = auth_config(root, mobile_module(source))
        notices = notification_settings(root, configure=args.telegram)
        if args.telegram:
            print('알림 정보를 폰에 저장했습니다. 테스트 메시지는 보내지 않았습니다.')
            return
        runtime = prepare_runtime(root, pins)
        settings = dict(keys, **notices, TRADING_EXCHANGE='okx', _EXCHANGE_ROOT=str(runtime))
        run_engine = args.takeover or args.run
        if run_engine:
            api = readonly_client(keys)
            try:
                if args.takeover:
                    print('PC에서 신규 진입을 중지하고 보유/미체결/조건주문이 모두 0인지 확인한 뒤 PC 프로그램을 정상 종료하세요.', flush=True)
                    print('PC 원격 종료 여부는 자동 확인할 수 없습니다. 두 기기를 동시에 운용하지 마세요.', flush=True)
                    take_ownership(root, runtime, api, pins, input(f'완료했다면 "{ACK}" 입력: ').strip())
                else:
                    verify_service_start(root, runtime, api, pins)
                # No stale handover snapshot: recheck identity before starting worker.
                verify_owner(root, pins, api.snapshot())
            finally:
                api.session.close()
        serve(root, runtime, source, settings, access, run_engine)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Raw exchange exceptions may include private values: do not echo them.
        if isinstance(exc, ValueError):
            print('폰 실행 보류:', str(exc), flush=True)
        else:
            print('폰 실행 보류:', type(exc).__name__, '· 기존 파일을 삭제하지 말고 오류 종류를 알려주세요.', flush=True)
        sys.exit(1)
