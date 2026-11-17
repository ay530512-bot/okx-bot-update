"""One reserved, serialized trend slot. No exchange writer outside RuleEngine.

Pure signal functions mirror top1_15_entry3/dip_only. Live admission retains
the original 90s expiry, book, freshness, cash, rounding and protection guards.
Ranking uses the complete eligible OKX universe, not a partially loaded scan.
"""
import copy
import functools
import hashlib
import inspect
import json
import math
from pathlib import Path
from types import FunctionType

STEP = 900000
HOUR = 3600000
DAY = 86400000
ROUTE = 'top1_15kst_dip130'
STATE = 'phone_trend130'
EXCLUDED = {'BTC', 'ETH', 'SOL', 'BTCDOM', 'DEFI', 'BLUEBIRD', 'USDC', 'TUSD', 'BUSD', 'FDUSD'}


def is_signal(s):
    return bool(s and (s.get('trend130') or s.get('pattern') == ROUTE
                      or str(s.get('signal_id', '')).startswith('tr130-')))


def is_owned(o):
    return bool(o and (is_signal(o.get('v4_signal')) or (o.get('holding_rule') or {}).get('trend130')))


def is_reserved(s):
    from phone_morning_short import is_signal as morning_signal
    return is_signal(s) or morning_signal(s)


def reserved_owned(o):
    from phone_morning_short import is_owned as morning_owned
    return is_owned(o) or morning_owned(o)


def in_window(t):
    # UTC06 == KST15; UTC17 == next KST02. Entry window only; held positions keep management.
    return 6 * HOUR <= int(t) % DAY < 17 * HOUR


def completed(values, t, step, required):
    b = [r for r in values if int(r[0]) + step <= t]
    if len(b) < required or int(b[-1][0]) != t // step * step - step:
        raise ValueError('최신 확정봉 대기')
    for r in b:
        if len(r) < 6 or not all(math.isfinite(float(x)) for x in r[:6]):
            raise ValueError('봉 수치 오류')
        if min(r[1:5]) <= 0 or r[5] < 0 or not r[3] <= min(r[1], r[4]) <= max(r[1], r[4]) <= r[2]:
            raise ValueError('봉 범위 오류')
    if any(int(y[0])-int(x[0]) != step for x, y in zip(b, b[1:])):
        raise ValueError('봉 간격 오류')
    return b


def atr(b):
    if len(b) < 15:
        raise ValueError('ATR 자료 부족')
    a = b[-15:]
    return sum(max(y[2]-y[3], abs(y[2]-x[4]), abs(y[3]-x[4])) for x, y in zip(a, a[1:])) / 14


def uptrend(h):
    if len(h) < 55:
        return False
    ma = sum(r[4] for r in h[-50:])/50
    prev = sum(r[4] for r in h[-53:-3])/50
    return h[-1][4] > ma > prev


def breakout(b, h):
    return len(b) >= 55 and uptrend(h) and b[-1][4] > max(r[2] for r in b[-21:-1])


def advance(arm, b, h, previous_h, t, eligible, previous_eligible):
    """Call once per completed15m. No future bar, touch fill, or intrabar arm."""
    if not eligible or not uptrend(h):
        return None, None
    last = b[-1]
    if arm and last[0] >= arm['t'] and last[4] <= arm['level']:
        a = atr(b[:-1])
        proof = dict(action='LONG', reference=last[4], atr=a,
                     structural_stop=last[4]-2*a,
                     channel_high=max(r[2] for r in b[-21:-1]),
                     channel_low=min(r[3] for r in b[-21:-1]),
                     confirmation_ms=int(last[0]), route721=ROUTE,
                     armed_ms=arm['t'], dip_level=arm['level'],
                     hour_atr=atr(h), trend130=True)
        return None, proof
    event = (breakout(b, h) and len(previous_h) >= 55
             and not (previous_eligible and breakout(b[:-1], previous_h)))
    if arm is None and event:
        arm = dict(t=t, level=last[4]-.5*atr(b[:-1]))
    return arm, None


def rank_rows(rows, t):
    """All rows have to supply the same closed-hour mark and KST09 open."""
    if not in_window(t):
        return None
    hour, day = t//HOUR*HOUR, t//DAY*DAY
    ranked = []
    for row in rows:
        h = completed(row['live_frames'].get('1H', []), hour, HOUR, 1)
        opening = next((r[1] for r in h if int(r[0]) == day), None)
        if not opening:
            raise ValueError('09시 기준봉 대기')
        gain = h[-1][4]/opening-1
        if gain > 0:
            ranked.append((gain, row['symbol']))
    if not ranked:
        return None
    gain, symbol = min(ranked, key=lambda x: (-x[0], x[1]))
    return dict(symbol=symbol, gain=gain, rank=1, hour=hour, day=day)


def slot_counts(e, snapshot=None):
    records = e.records()
    # A partially filled/submitted record still occupies its full slot.
    occupied = {(r['symbol'], r['direction']) for r in records}
    trends = {(r['symbol'], r['direction']) for r in records if reserved_owned(r)}
    for raw in (snapshot or {}, getattr(e, 'raw_snapshot', None) or {}):
        for p in raw.get('positions', []):
            if float(p.get('pos') or 0):
                occupied.add((p['instId'], p.get('posSide', 'unknown')))
        for p in raw.get('orders', []) + raw.get('manual_orders', []):
            reduce = str(p.get('reduceOnly', '')).lower() == 'true'
            close_side = (p.get('posSide'), p.get('side')) in (('long', 'sell'), ('short', 'buy'))
            if not reduce and not close_side:
                occupied.add((p['instId'], p.get('posSide', 'unknown')))
    return len(occupied), len(trends), len(occupied-trends)


def require_slot(e, signal, snapshot=None):
    from okx_core import BotError
    from phone_morning_short import is_signal as morning_signal, in_window as morning_window
    if morning_signal(signal) and not morning_window(e.api.now_ms()):
        raise BotError('오전 숏 신규 진입 시간 종료 · KST05~08')
    if is_signal(signal) and not in_window(e.api.now_ms()):
        raise BotError('추세 신규 진입 시간 종료 · KST15시~다음02시')
    total, trend, common = slot_counts(e, snapshot)
    if total >= 4 or (is_reserved(signal) and trend >= 1) or (not is_reserved(signal) and common >= 3):
        raise BotError('자리 배분: 기존 세 규칙 최대3 · 추세롱/오전숏 전용 최대1 · 전체 최대4')
    raw = snapshot or getattr(e, 'raw_snapshot', None) or {}
    symbols = {r['symbol'] for r in e.records()} | {
        p['instId'] for p in raw.get('positions', []) if float(p.get('pos') or 0)}
    symbols |= {p['instId'] for p in raw.get('orders', []) + raw.get('manual_orders', [])}
    if signal.get('symbol') in symbols:
        raise BotError('보유/미체결 동일 종목 중복 진입 금지')


def permitted(row, cfg):
    from okx_pattern15 import allowed
    return row['symbol'].split('-')[0] not in EXCLUDED and allowed(row['instrument'], cfg)


def snapshot_ranks(e, t):
    from phone_live_rank import selected, selected_rows
    rank = selected(e)
    return selected_rows(e, rank), rank, None


def make_signal(symbol, proof, rank, now):
    start = proof['confirmation_ms']+STEP
    key = symbol+'|'+str(start)+'|'+str(proof['armed_ms'])
    return dict(symbol=symbol, action='LONG', leverage=5, strategy='band_flow',
                pattern=ROUTE, trend130=True, rule_channel701=True, free_ai=True, pattern15=True,
                stop=proof['structural_stop'], target=None, margin_fraction=.25,
                signal_id='tr130-'+hashlib.sha256(key.encode()).hexdigest()[:24],
                atr=proof['atr'], level=proof['structural_stop'],
                reason='추세 전용1자리 · KST15시~다음02시 상승1위 · 돌파 후 0.5ATR 눌림 종가 · 5배 전량 추적',
                regime='상승1위 추세 눌림', ma={}, bb={}, rsi={}, retest=False, adaptive=False,
                setup_frame='15m', execution_frame='15m', at_ms=now,
                valid_from_ms=start, expires_ms=start+90000,
                entry_reference=proof['reference'], entry_gap=proof['reference'],
                selection=dict(activity={}, asset_category='1', change=rank['gain'], mover_rank=1,
                               ranking_start_ms=rank['day'], rank_hour_ms=rank['hour'], ranking_basis=rank.get('basis'),
                               rank_observed_ms=rank.get('observed_ms')),
                holding_rule=dict(band_flow=True, free_ai=True, pattern15=True, rule_channel701=True,
                                  trend130=True, frame='1H', target=None, target_mode='trend130',
                                  max_hold_seconds=259200, partial=False),
                decision_record=dict(source=ROUTE, frames={}, volume_wick_proof=proof,
                                     evidence704=dict(score=0), rank130=rank))


def prewarm_symbols(e, now):
    from phone_live_rank import prewarm
    return prewarm(e, now)


def scan(e):
    now = e.api.now_ms(); t = now//STEP*STEP
    state = e.journal.data.setdefault(STATE, dict(arm=None, pending=None, last=0))
    try:
        rows, rank, _ = snapshot_ranks(e, t)
        key = (rank['day'], rank['symbol']) if rank else (now//DAY*DAY, None)
        previous_key = tuple(state.get('leader_key') or ())
        changed = key != previous_key
        if changed:
            state.update(arm=None, pending=None, leader_key=key, last=0, replay_needed=True)
            e.journal.save()
        state['rank'] = rank
        if not in_window(now):
            e.phone_trend_status = '현재 1위 추적 중 · 롱 신규 진입 KST15시~다음02시'
            if state.get('arm') or state.get('pending'):
                state.update(arm=None, pending=None); e.journal.save()
            return None
        if state.get('last') != t:
            arm, proof, row = state.get('arm'), None, None
            if rank:
                row = rows[0]
                b = completed(row['live_frames'].get('15m', []), t, STEP, 55)
                h = completed(row['live_frames'].get('1H', []), t, HOUR, 55)
                ph = completed(row['live_frames'].get('1H', []), t-STEP, HOUR, 55)
                if state.get('replay_needed'):
                    # Re-evaluate this leader's completed setup in the current
                    # entry session. Only the latest close may produce a signal;
                    # prior confirmations are consumed, never given a new 90s.
                    arm, proof = replay_setup(b, h, t)
                else:
                    if state.get('last') != t-STEP: arm = None
                    arm, proof = advance(arm, b, h, ph, t, True, in_window(t-STEP))
                if arm: arm = dict(arm, symbol=rank['symbol'])
            pending = make_signal(rank['symbol'], proof, rank, now) if proof else None
            if pending:
                e.phone_trend_timing = dict(input_published_ms=row.get('observed_ms'),
                    rank_inputs_captured_ms=row.get('cache_read_ms'),
                    computation_submitted_ms=now, computation_published_ms=e.api.now_ms())
            state.update(last=t, arm=arm, pending=pending, replay_needed=False)
            e.journal.save()
            e.phone_trend_status = ('눌림 확인·주문 검사 대기' if pending else
                '현재 상승1위 눌림 종가 대기' if arm else '현재 상승1위 새 돌파 신호 대기')
    except (ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
        e.phone_trend_status = str(error)
        if state.get('pending') or state.get('arm') or state.get('last'):
            state.update(arm=None, pending=None, last=0, replay_needed=True); e.journal.save()
        return None
    s = state.get('pending')
    if not s: return None
    if not s['valid_from_ms'] <= now <= s['expires_ms']:
        e.phone_trend_status = '눌림 신호 90초 만료 · 다음 새 돌파 신호 대기'
    elif s['symbol']+':'+s['signal_id'] in e.journal.data.get('seen_signals', {}):
        e.phone_trend_status = '처리한 추세 신호 · 다음 새 돌파 신호 대기'
    else:
        return copy.deepcopy(s)
    state['pending'] = None; e.journal.save()
    return None


def replay_setup(b, h, t):
    """Apply unchanged candle predicates to a newly selected leader, causally."""
    session_start = t//DAY*DAY+6*HOUR
    arm, proof = None, None
    for end in range(55, len(b)+1):
        at = int(b[end-1][0])+STEP
        if at < session_start or not in_window(at): continue
        hours = [r for r in h if r[0]+HOUR <= at]
        previous = [r for r in h if r[0]+HOUR <= at-STEP]
        arm, current = advance(arm, b[:end], hours, previous, at, True, at > session_start)
        proof = current if at == t else None
    return arm, proof


def validate_entry(e, s, price):
    from okx_core import BotError
    from okx_band_flow import rows as parse
    now = e.api.now_ms()
    try:
        if not is_signal(s) or s.get('leverage') != 5 or s.get('action') != 'LONG':
            raise ValueError('추세 신호/배율 불일치')
        if (Path(e.root).parent/'phone_trend_activation_hold').exists():
            raise ValueError('새 실행기 준비 확인 후 추세 진입 재개')
        if not in_window(now):
            raise ValueError('추세 신규 진입 시간 종료 · KST15시~다음02시')
        if not s['valid_from_ms'] <= now <= s['expires_ms']:
            raise ValueError('추세 신호 90초 만료')
        require_slot(e, s)
        state = e.journal.data.get(STATE, {})
        if (state.get('pending') or {}).get('signal_id') != s['signal_id']:
            raise ValueError('저장된 추세 신호 불일치')
        _, rank, _ = snapshot_ranks(e, now//STEP*STEP)
        if not rank or rank['symbol'] != s['symbol'] or rank['day'] != s['selection']['ranking_start_ms']:
            raise ValueError('상승1위 변경')
        braw = parse(e.api.public('/api/v5/market/candles', instId=s['symbol'], bar='15m', limit='100'), '15m', now)
        hraw = parse(e.api.public('/api/v5/market/candles', instId=s['symbol'], bar='1H', limit='100'), '1H', now)
        b = completed(braw, now, STEP, 55); h = completed(hraw, now, HOUR, 55)
        v = s['decision_record']['volume_wick_proof']
        a = atr(b[:-1]); last = b[-1]
        if (not uptrend(h) or last[0] != v['confirmation_ms']
                or last[0] < v['armed_ms'] or last[4] > v['dip_level']
                or abs(last[4]-v['reference']) > abs(last[4])*1e-10
                or abs(a-v['atr']) > max(1e-12, a*1e-9)):
            raise ValueError('추세 원래 확정봉 변경')
        price = float(price)
        if (not math.isfinite(price) or not 0 < price-s['stop'] < .09*price
                or abs(price-v['reference']) > .5*v['atr']):
            raise ValueError('추세 진입 호가/손절 범위 이탈')
        if any(r[0] >= s['valid_from_ms'] and r[3] <= s['stop'] for r in braw):
            raise ValueError('추세 대기 중 초기SL 도달')
        from phone_live_rank import check
        check(e, s)
        return v
    except (ValueError, KeyError, TypeError) as error:
        raise BotError(str(error)) from None


def observe_trend(e, snapshot, p, o):
    """Reuse the WS observed-mark buffer; never latch incumbent half exits."""
    from okx_core import BotError
    if o.get('direction') != 'long' or float(o.get('leverage') or 0) != 5:
        raise BotError('추세 보유 기록 방향/배율 불일치 · 거래소 보호 유지, 대조 필요')
    entry, mark = float(p.get('avgPx') or 0), float(p.get('markPx') or 0)
    if min(entry, mark) <= 0:
        return p
    now = e.api.now_ms(); state = o.setdefault('profit_state714', {})
    peak = max(entry, mark, float(state.get('peak_mark') or entry))
    if hasattr(e, 'profit_lock714'):
        with e.profit_lock714:
            buf = e.profit_marks714.pop(o['client_id'], None)
        if (buf and int(o.get('entry_ms') or 0) <= buf['last_ms'] <= now
                and buf['side'] == 1 and abs(float(buf['entry'])-entry) <= entry*1e-8):
            peak = max(peak, buf['peak'])
            if now-buf['last_ms'] <= 15000:
                mark = buf['last']; p = dict(p, markPx=str(mark))
    changed = dict(state)
    state.update(peak_mark=peak, peak_roe=max(0., (peak/entry-1)*float(o['leverage'])), entry=entry, side=1)
    # Never invent peaks during downtime, and never reduce an existing target.
    if state != changed:
        state['observed_ms'] = now; e.journal.save()
    return p


def manage(e, snap, p, o):
    from okx_profit_guard714 import effective_stop
    from okx_core import BotError
    if o.get('direction') != 'long' or float(o.get('leverage') or 0) != 5:
        raise BotError('추세 보유 기록 방향/배율 불일치 · 거래소 보호 유지, 대조 필요')
    now = e.api.now_ms(); mark = float(p['markPx'])
    if mark <= effective_stop(o):
        e.close(snap, '추세 전량 보호 SL 도달'); return True
    if now-int(o['entry_ms']) >= 259200000:
        e.close(snap, '추세 최대72시간 만료'); return True
    bars = e.chart_job(o['symbol']) or {}
    try:
        h = completed(bars.get('1H', []), now, HOUR, 15)
        a = atr(h)
    except ValueError:
        return False  # Existing exchange stop continues; no stale ATR tightening.
    state = o.setdefault('profit_state714', {})
    target = max(effective_stop(o), float(state.get('peak_mark') or mark)-2*a)
    if target > effective_stop(o):
        state.update(desired_stop=target, stop_reason='추세 최고 관측가격 − 2×1시간 ATR')
        e.journal.save()
    if mark <= target:
        e.close(snap, '추세 전량 추적 SL 도달'); return True
    if target <= float(o['stop_px']) or now-o.get('trend_amend_ms', 0) < 2000:
        return False
    e.trail(snap, p, o, target)
    o['trend_amend_ms'] = now; e.journal.save()
    return True


def install(source):
    """Called after performance patches, before constructing the live engine."""
    import okx_channel701 as channel
    import okx_autonomous as auto
    import okx_risk732 as risk
    import okx_profit_guard714 as guard
    import okx_dashboard_data as dashboard
    import okx_search_capacity as capacity
    import phone_morning_short as morning
    if getattr(channel, '_phone_trend130', False):
        return
    pins = json.loads(Path(__file__).with_name('phone_sources.json').read_text())['files']
    for mod in (channel, auto, risk, guard, dashboard, capacity):
        path = Path(mod.__file__)
        if path.resolve().parent != Path(source).resolve() or hashlib.sha256(path.read_bytes()).hexdigest() != pins[path.name]:
            raise ValueError('추세 연결 원본 검증 실패: '+path.name)
    original_check, original_manage = channel.check_entry, channel.management
    original_leverage, original_cap, original_observe = auto.valid_leverage, risk.cap_plan, guard.observe
    original_dashboard = dashboard.dashboard_snapshot

    def check(e, s, price):
        require_slot(e, s)
        if morning.is_signal(s):
            return morning.validate_entry(e, s, price)
        from phone_ema_support import is_signal as support_signal, validate_entry as support_check
        if support_signal(s):
            return support_check(e, s, price)
        return validate_entry(e, s, price) if is_signal(s) else original_check(e, s, price)

    def cap(e, plan, instrument, s, direction, snapshot, fee):
        require_slot(e, s, snapshot)
        return original_cap(e, plan, instrument, s, direction, snapshot, fee)

    def valid(s, cfg):
        if morning.is_signal(s):
            return (s.get('action') == 'SHORT' and type(s.get('leverage')) is int and s['leverage'] == 5
                    and s.get('symbol','').split('-')[0] not in EXCLUDED)
        if is_signal(s):
            return (s.get('action') == 'LONG' and type(s.get('leverage')) is int and s['leverage'] == 5
                    and s.get('symbol','').split('-')[0] not in EXCLUDED)
        return original_leverage(s, cfg)

    # Change only the required-leverage expression; keep all admission code.
    text = inspect.getsource(risk.prepare_plan)
    anchor = "required = 5 if s.get('click716') else leverage(i['instId'])"
    if text.count(anchor) != 1:
        raise ValueError('추세 배율 연결 기준 불일치')
    text = text.replace(anchor, "required = 5 if (s.get('click716') or _phone_is_trend130(s)) else leverage(i['instId'])")
    namespace = {}; exec(compile(text, str(source)+'/okx_risk732.py<trend130>', 'exec'), namespace)
    risk._phone_is_trend130 = is_reserved
    risk.prepare_plan = FunctionType(namespace['prepare_plan'].__code__, risk.__dict__, 'prepare_plan')

    # A full portfolio still needs fresh ranking inputs for a long-to-short
    # reversal. The original capacity return value and order limits stay full.
    text = inspect.getsource(capacity.sync)
    anchor = 'engine.universe.set_search_paused(full)'
    if text.count(anchor) != 1:
        raise ValueError('전환 탐색 연결 기준 불일치')
    text = text.replace(anchor, 'engine.universe.set_search_paused(full and not _phone_reversal_search(engine))')
    namespace = {}; exec(compile(text, str(source)+'/okx_search_capacity.py<morning150>', 'exec'), namespace)
    capacity._phone_reversal_search = morning.needs_reversal_search
    capacity.sync = FunctionType(namespace['sync'].__code__, capacity.__dict__, 'sync')

    def project(snapshot, records, *args):
        result = original_dashboard(snapshot, records, *args)
        symbols = {r['symbol'] for r in records if is_owned(r)}
        morning_symbols = {r['symbol'] for r in records if morning.is_owned(r)}
        for row in result['positions']:
            if row['symbol'] in morning_symbols and row.get('source') == 'auto':
                row.update(partial_price=None, partial_note='오전 숏 · 절반 익절 없음',
                           protection_note='전용1자리 · 5배 숏 · 전량 15분 ATR 추적 · 최대72시간',
                           reason='상승1위 큰 눌림 후 반등 실패 · 오전 숏',
                           exit_estimate_note='보호 SL 예상액: 수수료·펀딩·슬리피지 제외')
            if row['symbol'] in symbols and row.get('source') == 'auto':
                row.update(partial_price=None, partial_note='추세 전용 · 절반 익절 없음',
                           protection_note='추세1자리 · 5배 · 전량 1시간 ATR 추적 · 최대72시간',
                           reason=('상승1위 EMA20 지지 반등 · 추세 전용' if any(r['symbol']==row['symbol'] and (r.get('v4_signal') or {}).get('pattern')=='top1_ema20_support170' for r in records) else '상승1위 돌파 후 눌림 진입 · 추세 전용'),
                           exit_estimate_note='보호 SL 예상액: 수수료·펀딩·슬리피지 제외')
        return result

    channel.check_entry = check
    def management(e, sn, p, o):
        if morning.is_owned(o):
            return morning.manage(e, sn, p, o)
        if is_owned(o):
            if morning.maybe_switch(e, sn, p, o):
                return True
            return manage(e, sn, p, o)
        return original_manage(e, sn, p, o)
    channel.management = management
    auto.valid_leverage = valid; risk.cap_plan = cap
    guard.observe = lambda e, sn, p, o: (morning.observe(e, sn, p, o) if morning.is_owned(o)
        else observe_trend(e, sn, p, o) if is_owned(o) else original_observe(e, sn, p, o))
    dashboard.dashboard_snapshot = project
    from phone_live_rank import install_submission_guard
    install_submission_guard()
    channel._phone_trend130 = True
