"""Exact-input candidate selection memo; fresh execution-clock checks.

Cache only the small pattern result, never an entire candle array. All input
bytes and the completed-bar cutoff participate in cache validity. Final order
admission/position protection stay uncached and run original core checks.
"""
import ast
import functools
import hashlib
import inspect
from pathlib import Path
import threading
import time
from types import FunctionType
from phone_frozen_bars import FrozenBars


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('candidate patch anchor mismatch')
    return text.replace(old, new, 1)


def rejection(error):
    text = str(error)
    for match, label in (
        ('최신 완료봉 대기','최신 확정봉 대기'), ('완료봉 자료 부족','봉 자료 부족'),
        ('봉 수치 오류','봉 수치 오류'), ('봉 연속성 오류','봉 간격 오류'),
        ('90초 만료','90초 만료'), ('신호 만료','90초 만료'),
        ('손절 유효성','가격·손절 범위'), ('초기SL 도달','대기 중 손절선 도달'),
        ('원래 완료봉 신호 변경','원래 신호 변경'), ('진입 경로 변경','진입 경로 변경')):
        if match in text:
            return label
    return '자료·신호 검사 거절'


def install(channel, cache, pins):
    path = Path(inspect.getsourcefile(channel))
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pins['files'][path.name]:
        raise ValueError('candidate fast path source hash mismatch')
    original_packet, original_candidate, original_closed = channel.packet, channel.candidate, channel.closed
    state = threading.local()
    import okx_two_wick732 as patterns
    # The existing exact-input pattern wrapper was just installed by our caller.
    # Fold its pure original into one validation+selection cache so full bars
    # are serialized once and never deep-copied on a cache hit.
    original_select = inspect.unwrap(patterns.select)

    def select_validated(bars, hourly, now):
        with cache.timer.scope('signal.closed_validation.compute'):
            b = original_closed(bars, now)
        return original_select(b, hourly)
    memo_select = cache.wrap(select_validated, 'signal.validated_selection')

    def select_fast(bars, hourly, now):
        # Aligned integer timestamps make floor(now/15m) an EXACT equivalent
        # cutoff, including future/in-progress bars. Unusual input falls back.
        aligned = (type(now) is int and type(bars) in (list, tuple) and all(type(r) in (list, tuple) and len(r)>0
            and type(r[0]) is int and r[0] % 900000 == 0 for r in bars))
        if type(bars) is FrozenBars:
            aligned = type(now) is int and bars._aligned15
        return memo_select(bars, hourly, now//900000*900000) if aligned else select_validated(bars, hourly, now)

    def gate(label):
        d = getattr(state, 'diagnostic', None)
        if d is not None:
            d['reasons'][label] = d['reasons'].get(label, 0)+1

    def wait_for_market(e, symbol, signal, now):
        gate('실시간 자료 대기')
        d = getattr(state, 'diagnostic', None)
        if d is not None and len(d['waiting']) < 4:
            missing = e.stream.missing(symbol, e.cfg, now) if hasattr(e.stream,'missing') else []
            # Only known channel names and the already-public instrument ID.
            symbol = str(symbol)
            if len(symbol) <= 64 and all(c.isascii() and (c.isalnum() or c=='-') for c in symbol):
                d['waiting'].append(dict(symbol=symbol,
                    channels=[x for x in missing if x in ('tickers','trades','books5','mark-price')],
                    remaining_s=round(max(0,signal['expires_ms']-now)/1000,1)))

    channel._phone_select_validated = select_fast
    channel._phone_entry_gate = gate
    channel._phone_entry_rejection = rejection
    channel._phone_entry_wait = wait_for_market
    channel._phone_thaw_row = lambda row: dict(row, live_frames={
        name: bars.thaw() if type(bars) is FrozenBars else bars
        for name, bars in row.get('live_frames', {}).items()})
    tree = ast.parse(raw)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'packet')
    src = ast.unparse(node)
    src = replace_once(src, "frames = {}\n    b = closed(row.get('live_frames', {}).get('15m', []), now)", "frames = {}")
    src = replace_once(src, "v, or_status = select(b, row.get('live_frames', {}).get('1H'))", "v, or_status = _phone_select_validated(row.get('live_frames', {}).get('15m', []), row.get('live_frames', {}).get('1H'), now)\n    if not v:\n        return dict(entry_setups=[], or_status=or_status)\n    b = closed(row.get('live_frames', {}).get('15m', []), now)")
    src = replace_once(src, "b = closed(row.get('live_frames', {}).get('15m', []), now)",
                       "row = _phone_thaw_row(row)\n    b = closed(row.get('live_frames', {}).get('15m', []), now)")
    def compiled(text, name, defaults=None):
        ns = {}; exec(compile(text, str(path)+'<phone123>', 'exec'), ns)
        return FunctionType(ns[name].__code__, channel.__dict__, name, defaults)
    fast = compiled(src, 'packet', original_packet.__defaults__)

    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'candidate')
    src = ast.unparse(node)
    # Refresh after the complete scan, then again for each execution check.
    # The original <=500ms future tolerance remains unmodified.
    anchor = "e.channel_pending = {k: s for k, s in e.channel_pending.items()"
    src = replace_once(src, anchor, "now = e.api.now_ms()\n    for pending in e.channel_pending.values():\n        if now > pending['expires_ms']:\n            _phone_entry_gate('90초 만료')\n    "+anchor)
    anchor = "for symbol, s in sorted(e.channel_pending.items(), key=rank_item):"
    src = replace_once(src, anchor, anchor+"\n        now = e.api.now_ms()\n        if now > s['expires_ms']:\n            e.channel_pending.pop(symbol, None)\n            _phone_entry_gate('90초 만료')\n            continue")
    src = replace_once(src, "if not e.stream.ready(symbol, e.cfg, now):\n            continue", "if not e.stream.ready(symbol, e.cfg, now):\n            _phone_entry_wait(e, symbol, s, now)\n            continue")
    src = replace_once(src, "q = e.stream.read(symbol, 'tickers', 15, now)", "q = e.stream.read(symbol, 'tickers', 15, e.api.now_ms())")
    src = replace_once(src, "if not q or not q.get('last'):\n            continue", "if not q or not q.get('last'):\n            _phone_entry_gate('최신 체결가 대기')\n            continue")
    src = replace_once(src, "except (BotError, ValueError, KeyError):\n            continue", "except (BotError, ValueError, KeyError) as error:\n            _phone_entry_gate(_phone_entry_rejection(error))\n            continue")
    src = replace_once(src, "except BotError as err:\n            e.channel_pending.pop", "except BotError as err:\n            _phone_entry_gate(_phone_entry_rejection(err))\n            e.channel_pending.pop")
    src = replace_once(src, "if float(row['instrument'].get('lever') or 0) < s['leverage']:\n                continue", "if float(row['instrument'].get('lever') or 0) < s['leverage']:\n                _phone_entry_gate('거래소 배율 한도')\n                continue")
    src = replace_once(src, "if symbol + ':' + s['signal_id'] in e.journal.data.get('seen_signals', {}):\n                continue", "if symbol + ':' + s['signal_id'] in e.journal.data.get('seen_signals', {}):\n                _phone_entry_gate('이미 처리한 신호')\n                continue")
    src = replace_once(src, "if not v:\n                if p.get('or_status')", "if not v:\n                _phone_entry_gate('패턴 조건 미충족')\n                if p.get('or_status')")
    fixed_candidate = compiled(src, 'candidate')

    def enabled():
        return getattr(state,'candidate',False) and getattr(cache.timer.local,'group',None)=='optimized'
    @functools.wraps(original_candidate)
    def candidate(e):
        previous = state.__dict__.copy()
        state.candidate = True
        d = dict(observed_at=time.time(), reasons={}, waiting=[])
        state.diagnostic = d
        started = time.perf_counter(); result = None
        try:
            result = fixed_candidate(e)
            return result
        finally:
            d['duration_s'] = round(time.perf_counter()-started,3)
            d['pending'] = len(getattr(e,'channel_pending',{}))
            d['result'] = '주문 전 최종 검사로 전달' if result else '진입 후보 대기'
            d['observed_at'] = time.time()
            e.phone_entry_diagnostic = d  # Replace atomically; readers never mutate.
            state.__dict__.clear(); state.__dict__.update(previous)
    @functools.wraps(original_packet)
    def packet(*args, **kwargs):
        with cache.timer.scope('signal.packet_body'):
            if enabled():
                return fast(*args, **kwargs)
            # UI/manual consumers retain the original editable-list packet shape.
            if args:
                args = (channel._phone_thaw_row(args[0]),) + args[1:]
            else:
                kwargs = dict(kwargs, row=channel._phone_thaw_row(kwargs['row']))
            return original_packet(*args, **kwargs)
    @functools.wraps(original_closed)
    def closed(b,now,step=900000,required=22):
        with cache.timer.scope('signal.closed_validation.compute'):
            return original_closed(b.thaw() if type(b) is FrozenBars else b,now,step,required)
    channel.candidate=candidate;channel.packet=packet;channel.closed=closed
