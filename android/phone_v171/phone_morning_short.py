"""KST05-08 top-gainer failed rebound. No exchange writer outside RuleEngine.

Defaults are an explicit, unbacktested interpretation of 'large pullback'.
Uses the shared KST09-open / current-price ranking, full eligible universe.
The entry clock never limits protection of an already filled position.
"""
import copy
import hashlib
import math
from pathlib import Path

STEP = 900000
HOUR = 3600000
DAY = 86400000
ROUTE = 'top1_morning_failed_rebound150'
STATE = 'phone_morning150'
PULLBACK_PCT = .02
PULLBACK_ATR = 1.5
REBOUND_ATR = .5
STOP_BUFFER_ATR = .2
TRAIL_ATR = 2.
LOOKBACK = 24


def is_signal(s):
    return bool(s and (s.get('morning150') or s.get('pattern') == ROUTE
                      or str(s.get('signal_id', '')).startswith('ms150-')))


def is_owned(o):
    return bool(o and (is_signal(o.get('v4_signal')) or (o.get('holding_rule') or {}).get('morning150')))


def in_window(t):
    return 5 * HOUR <= (int(t) + 9 * HOUR) % DAY < 8 * HOUR


def pattern(b):
    """Only closed candles; require ordered peak, dip, rebound, fresh breakdown.

    The confirmation is bearish, below the previous candle low, and below the
    rebound high. At least one green rebound candle must follow the dip. The
    latest qualifying swing high within six hours is the reference high.
    """
    from phone_trend_slot import atr
    if len(b) < 30:
        return None
    a = atr(b[:-1])
    if not math.isfinite(a) or a <= 0:
        return None
    last, prev = b[-1], b[-2]
    if not (last[4] < last[1] and last[4] < prev[3]):
        return None
    for i in range(len(b)-4, max(0, len(b)-LOOKBACK-1), -1):
        peak = b[i]
        if not (peak[2] > b[i-1][2] and peak[2] >= b[i+1][2]):
            continue
        # Exclude the rebound and confirmation from the pullback trough.
        j = min(range(i+1, len(b)-2), key=lambda k: (b[k][3], -k))
        trough = b[j]
        rebound = b[j+1:-1]
        if not rebound:
            continue
        high_bar = max(rebound, key=lambda r: (r[2], r[0]))
        drop = peak[2]-trough[3]
        if (drop < max(peak[2]*PULLBACK_PCT, PULLBACK_ATR*a)
                or high_bar[2]-trough[3] < REBOUND_ATR*a
                or not any(r[4] > r[1] for r in rebound)
                or max(r[2] for r in b[i+1:]) >= peak[2]
                or last[2] >= high_bar[2]):
            continue
        stop = high_bar[2]+STOP_BUFFER_ATR*a
        return dict(action='SHORT', reference=last[4], atr=a, structural_stop=stop,
                    confirmation_ms=int(last[0]), route721=ROUTE, morning150=True,
                    peak_ms=int(peak[0]), peak=peak[2], trough_ms=int(trough[0]), trough=trough[3],
                    rebound_ms=int(high_bar[0]), rebound_high=high_bar[2],
                    pullback_pct=drop/peak[2], pullback_atr=drop/a,
                    channel_high=peak[2], channel_low=trough[3])
    return None


def rank_rows(rows, t):
    from phone_trend_slot import completed
    hour, day = t//HOUR*HOUR, t//DAY*DAY
    ranks = []
    for row in rows:
        h = completed(row['live_frames'].get('1H', []), hour, HOUR, 1)
        opening = next((r[1] for r in h if int(r[0]) == day), None)
        if not opening:
            raise ValueError('09시 기준봉 대기')
        gain = h[-1][4]/opening-1
        if gain > 0:
            ranks.append((gain, row['symbol']))
    if not ranks:
        return None
    gain, symbol = min(ranks, key=lambda x: (-x[0], x[1]))
    return dict(symbol=symbol, gain=gain, rank=1, hour=hour, day=day)


def snapshot_rank(e, t):
    from phone_live_rank import selected, selected_rows
    rank = selected(e)
    return selected_rows(e, rank), rank


def pattern_key(symbol, proof):
    # One rebound structure, even if further bearish candles follow it.
    return '|'.join(str(x) for x in (symbol, proof['peak_ms'], proof['trough_ms'], proof['rebound_ms']))


def make_signal(symbol, proof, rank, now):
    start = proof['confirmation_ms']+STEP
    return dict(symbol=symbol, action='SHORT', leverage=5, strategy='band_flow',
                pattern=ROUTE, morning150=True, rule_channel701=True, free_ai=True, pattern15=True,
                stop=proof['structural_stop'], target=None, margin_fraction=.25,
                signal_id='ms150-'+hashlib.sha256(pattern_key(symbol, proof).encode()).hexdigest()[:24],
                atr=proof['atr'], level=proof['structural_stop'],
                reason='오전 숏 · KST05~08 상승1위 · 큰 눌림 후 낮은 반등 고점·재하락 · 5배 전량 추적',
                regime='상승1위 눌림 후 반등 실패', ma={}, bb={}, rsi={}, retest=False, adaptive=False,
                setup_frame='15m', execution_frame='15m', at_ms=now,
                valid_from_ms=start, expires_ms=start+90000,
                entry_reference=proof['reference'], entry_gap=proof['reference'],
                selection=dict(activity={}, asset_category='1', change=rank['gain'], mover_rank=1,
                               ranking_start_ms=rank['day'], rank_hour_ms=rank['hour'], ranking_basis=rank.get('basis'),
                               rank_observed_ms=rank.get('observed_ms')),
                holding_rule=dict(band_flow=True, free_ai=True, pattern15=True, rule_channel701=True,
                                  morning150=True, frame='15m', target=None, target_mode='morning150',
                                  max_hold_seconds=259200, partial=False),
                decision_record=dict(source=ROUTE, frames={}, volume_wick_proof=proof,
                                     evidence704=dict(score=0), rank150=rank))


def scan(e):
    from phone_trend_slot import completed
    now = e.api.now_ms(); t = now//STEP*STEP
    state = e.journal.data.setdefault(STATE, dict(pending=None, last=0))
    try:
        rows, rank = snapshot_rank(e, t)
        key = (rank['day'], rank['symbol']) if rank else (now//DAY*DAY, None)
        if tuple(state.get('leader_key') or ()) != key:
            state.update(pending=None, leader_key=key, last=0)
            e.journal.save()
        state['rank'] = rank
        if not in_window(now):
            e.phone_morning_status = '현재 1위로 숏 대기 대상 갱신 중 · 신규 진입 KST05:00~08:00 미만'
            if state.get('pending'):
                state['pending'] = None; e.journal.save()
            return None
        if state.get('last') != t:
            proof = None; row = None
            if rank:
                row = rows[0]
                b = completed(row['live_frames'].get('15m', []), t, STEP, 30)
                proof = pattern(b)
            pending = make_signal(rank['symbol'], proof, rank, now) if proof else None
            if pending and state.get('last_pattern') == pending['signal_id']:
                pending = None
            if pending:
                state['last_pattern'] = pending['signal_id']
                e.phone_morning_timing = dict(input_published_ms=row.get('observed_ms'),
                    rank_inputs_captured_ms=row.get('cache_read_ms'),
                    computation_submitted_ms=now, computation_published_ms=e.api.now_ms())
            state.update(last=t, pending=pending)
            e.journal.save()
            e.phone_morning_status = ('반등 실패 숏 확인·주문 검사 대기' if pending else
                                     '현재 상승1위 큰 눌림→반등 실패→재하락 대기')
    except (ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
        e.phone_morning_status = str(error)
        if state.get('pending') or state.get('last'):
            state.update(pending=None, last=0); e.journal.save()
        return None
    s = state.get('pending')
    if not s: return None
    if not s['valid_from_ms'] <= now <= s['expires_ms']:
        e.phone_morning_status = '오전 숏 신호 90초 만료 · 새 반등 구조 대기'
    elif s['symbol']+':'+s['signal_id'] in e.journal.data.get('seen_signals', {}):
        e.phone_morning_status = '처리한 오전 숏 신호 · 새 반등 구조 대기'
    else:
        return copy.deepcopy(s)
    state['pending'] = None; e.journal.save()
    return None


def prewarm_symbols(e, now):
    from phone_live_rank import prewarm
    return prewarm(e, now)


def validate_entry(e, s, price, closing_owned=None):
    from okx_core import BotError
    from okx_band_flow import rows as parse
    from phone_trend_slot import completed, require_slot
    now = e.api.now_ms()
    try:
        if not is_signal(s) or type(s.get('leverage')) is not int or s['leverage'] != 5 or s.get('action') != 'SHORT':
            raise ValueError('오전 숏 신호/방향/배율 불일치')
        if (Path(e.root).parent/'phone_trend_activation_hold').exists():
            raise ValueError('새 실행기 준비 확인 후 전용 진입 재개')
        if not in_window(now):
            raise ValueError('오전 숏 신규 진입 시간 종료 · KST05~08')
        if not s['valid_from_ms'] <= now <= s['expires_ms'] or not in_window(s['valid_from_ms']):
            raise ValueError('오전 숏 신호 90초 만료 또는 시간 밖 완료봉')
        if closing_owned is None:
            require_slot(e, s)
            verify_switch_flat(e, s)
        else:
            validate_switch_scope(e, s, closing_owned)
        if (e.journal.data.get(STATE, {}).get('pending') or {}).get('signal_id') != s['signal_id']:
            raise ValueError('저장된 오전 숏 신호 불일치')
        _, rank = snapshot_rank(e, now//STEP*STEP)
        if not rank or rank['symbol'] != s['symbol'] or rank['day'] != s['selection']['ranking_start_ms']:
            raise ValueError('상승1위 변경')
        raw = parse(e.api.public('/api/v5/market/candles', instId=s['symbol'], bar='15m', limit='100'), '15m', now)
        b = completed(raw, now, STEP, 30)
        proof = pattern(b)
        if proof != s['decision_record']['volume_wick_proof']:
            raise ValueError('오전 숏 원래 확정봉 신호 변경')
        if (s['stop'] != proof['structural_stop'] or s['valid_from_ms'] != proof['confirmation_ms']+STEP
                or s['expires_ms'] != s['valid_from_ms']+90000
                or s['signal_id'] != make_signal(s['symbol'], proof, rank, now)['signal_id']):
            raise ValueError('오전 숏 저장 신호 변경')
        price = float(price)
        if (not math.isfinite(price) or price <= 0 or not 0 < s['stop']-price < .09*price
                or abs(price-proof['reference']) > .5*proof['atr']):
            raise ValueError('오전 숏 진입 호가/손절 범위 이탈')
        if any(r[0] >= s['valid_from_ms'] and r[2] >= s['stop'] for r in raw):
            raise ValueError('오전 숏 대기 중 초기SL 도달')
        # A slow REST call must not carry an otherwise valid signal past 08:00.
        final_now = e.api.now_ms()
        if not in_window(final_now) or final_now > s['expires_ms']:
            raise ValueError('오전 숏 주문 직전 시간 종료 또는 신호 만료')
        from phone_live_rank import check
        check(e, s)
        return proof
    except (ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
        raise BotError(str(error)) from None


def switch_enabled(e):
    return (bool(getattr(e, 'enabled', False)) and not getattr(e, 'preview', False)
            and not getattr(e, 'user_paused', True) and not getattr(e, 'recovering', True)
            and not e.entry_cancel.is_set() and e.within_session()
            and not (e.journal.data.get('day') or {}).get('ended', False))


def validate_switch_scope(e, s, o):
    from okx_core import BotError
    from phone_trend_slot import is_owned as long_owned, slot_counts
    if (not long_owned(o) or o.get('direction') != 'long' or o.get('phase') != 'active'
            or not o.get('protection_verified') or e.journal.data.get('owned') is not o
            or not switch_enabled(e)):
        raise BotError('롱→숏 전환 운용/보유 상태 대기')
    total, reserved, _ = slot_counts(e)
    if total > 4 or reserved != 1:
        raise BotError('롱→숏 전환 자리 대조 실패')
    others = [r for r in e.records() if r['client_id'] != o['client_id']]
    if s['symbol'] in e.blocked_manual_symbols() or any(r['symbol'] == s['symbol'] for r in others):
        raise BotError('전환 대상에 별도 보유/수동 주문 존재')
    raw = getattr(e, 'raw_snapshot', None) or {}
    if any(p['instId'] == s['symbol'] and float(p.get('pos') or 0)
           and (p['instId'], p.get('posSide')) != (o['symbol'], 'long') for p in raw.get('positions', [])):
        raise BotError('전환 대상에 다른 포지션 존재')
    if any(p['instId'] in (s['symbol'], o['symbol']) for p in raw.get('orders', [])+raw.get('manual_orders', [])):
        raise BotError('전환 대상 미체결 대조 대기')


def verify_switch_flat(e, s):
    """Durable close intent is not a fill. Require exchange-confirmed flatness."""
    from okx_core import BotError, dec
    switch = e.journal.data.get(STATE, {}).get('switch')
    if not switch or switch.get('confirmed_ms'):
        return
    if not switch.get('close_id') or any(r['client_id'] == switch['long_client_id'] for r in e.records()):
        raise BotError('롱 청산 완료 대기 · 숏 주문 보류')
    raw = e.api.snapshot()
    if not 0 <= e.api.now_ms()-int(raw['ms']) <= 15000:
        raise BotError('전환 계좌 자료 지연')
    if any(p['instId'] == switch['long_symbol'] and p.get('posSide') == 'long'
           and dec(p.get('pos') or 0) != 0 for p in raw.get('positions', [])):
        raise BotError('롱 잔량 존재 · 숏 주문 보류')
    if any(p['instId'] == switch['long_symbol'] for p in raw.get('orders', [])):
        raise BotError('롱 미체결 정리 대기 · 숏 주문 보류')
    order = e.api.get('/api/v5/trade/order', instId=switch['long_symbol'], clOrdId=switch['close_id'])[0]
    if (order.get('state') != 'filled' or dec(order.get('accFillSz') or 0) != dec(switch['quantity'])
            or order.get('posSide') != 'long' or order.get('side') != 'sell'):
        raise BotError('롱 청산 체결 확인 대기 · 숏 주문 보류')
    if any(p['instId'] == switch['long_symbol'] and p.get('posSide') == 'long'
           for p in e.api.pending_algos(full=True)):
        raise BotError('롱 보호주문 정리 대기 · 숏 주문 보류')
    switch['confirmed_ms'] = e.api.now_ms()
    e.journal.save()


def maybe_switch(e, snap, p, o):
    """Called only by the serialized management of the original reserved long."""
    from okx_core import BotError
    if not in_window(e.api.now_ms()) or not switch_enabled(e):
        return False
    s = scan(e)
    if not s:
        return False
    e.stream.watch([s['symbol']]+[r['symbol'] for r in e.records()]+e.chat.watch())
    if not e.stream.ready(s['symbol'], e.cfg, e.api.now_ms()):
        e.phone_morning_status = '롱 유지 · 전환 대상 실시간 시세 대기'
        return False
    q = e.stream.read(s['symbol'], 'tickers', 15, e.api.now_ms())
    if not q or not q.get('last'):
        return False
    try:
        validate_entry(e, s, q['last'], closing_owned=o)
    except BotError as error:
        e.phone_morning_status = '롱 유지 · '+str(error)
        return False
    # Persist before the close request; never place a short here. Existing
    # reconciliation owns retries, full close, and protective-order cleanup.
    state = e.journal.data[STATE]
    state['switch'] = dict(signal_id=s['signal_id'], long_symbol=o['symbol'],
                           long_client_id=o['client_id'], quantity=o['quantity'],
                           requested_ms=e.api.now_ms(), target_symbol=s['symbol'], close_id=None)
    e.journal.save()
    e.phone_morning_status = '롱 청산 요청 → 실제 청산 확인 후 오전 숏 재검사'
    try:
        e.close(snap, '오전 상승1위 반등 실패 · 추세 롱→숏 전환')
    finally:
        state['switch']['close_id'] = o.get('close_id')
        e.journal.save()
    return True


def needs_reversal_search(e):
    from phone_trend_slot import is_owned as long_owned
    return in_window(e.api.now_ms()) and switch_enabled(e) and any(
        long_owned(o) and o.get('direction') == 'long' for o in e.records())


def observe(e, snapshot, p, o):
    from okx_core import BotError
    if o.get('direction') != 'short' or float(o.get('leverage') or 0) != 5:
        raise BotError('오전 숏 보유 기록 방향/배율 불일치 · 거래소 보호 유지')
    entry, mark = float(p.get('avgPx') or 0), float(p.get('markPx') or 0)
    if not all(math.isfinite(x) and x > 0 for x in (entry, mark)):
        return p
    now = e.api.now_ms(); state = o.setdefault('profit_state714', {})
    low = min(entry, mark, float(state.get('peak_mark') or entry))
    if hasattr(e, 'profit_lock714'):
        with e.profit_lock714:
            buf = e.profit_marks714.pop(o['client_id'], None)
        if (buf and int(o.get('entry_ms') or 0) <= buf['last_ms'] <= now
                and buf['side'] == -1 and abs(float(buf['entry'])-entry) <= entry*1e-8):
            low = min(low, buf['peak'])
            if now-buf['last_ms'] <= 15000:
                mark = buf['last']; p = dict(p, markPx=str(mark))
    before = dict(state)
    state.update(peak_mark=low, peak_roe=max(0., (1-low/entry)*5), entry=entry, side=-1)
    if state != before:
        state['observed_ms'] = now; e.journal.save()
    return p


def manage(e, snap, p, o):
    from okx_core import BotError
    from okx_profit_guard714 import effective_stop
    from phone_trend_slot import completed, atr
    if o.get('direction') != 'short' or float(o.get('leverage') or 0) != 5:
        raise BotError('오전 숏 보유 기록 방향/배율 불일치 · 거래소 보호 유지')
    # No entry-window check here: filled positions remain protected after08.
    now = e.api.now_ms(); mark = float(p['markPx'])
    if not math.isfinite(mark) or mark <= 0:
        return False
    if mark >= effective_stop(o):
        e.close(snap, '오전 숏 전량 보호 SL 도달'); return True
    if now-int(o['entry_ms']) >= 259200000:
        e.close(snap, '오전 숏 최대72시간 만료'); return True
    bars = e.chart_job(o['symbol']) or {}
    try:
        a = atr(completed(bars.get('15m', []), now, STEP, 15))
        if not math.isfinite(a) or a <= 0:
            return False
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        return False
    state = o.setdefault('profit_state714', {})
    target = min(effective_stop(o), float(state.get('peak_mark') or mark)+TRAIL_ATR*a)
    if target < effective_stop(o):
        state.update(desired_stop=target, stop_reason='오전 숏 최저 관측가격 + 2×15분 ATR')
        e.journal.save()
    if mark >= target:
        e.close(snap, '오전 숏 전량 추적 SL 도달'); return True
    if target >= float(o['stop_px']) or now-o.get('morning_amend_ms', 0) < 2000:
        return False
    e.trail(snap, p, o, target)
    o['morning_amend_ms'] = now; e.journal.save()
    return True
