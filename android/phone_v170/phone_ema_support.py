"""Independent OR entry for the live leader's rising 15m EMA20 support.

No orders or new network readers. The existing serialized coordinator owns
admission, slots, expiry, liquidity and exchange protection. A live rebound
requires two actually observed prices; a closed-bar rebound keeps close+90s.
Both routes use the existing trend-position sizing and exit management.
"""
import copy
import hashlib
import json
import math

STATE = 'phone_ema_support170'
ROUTE = 'top1_ema20_support170'
STEP = 900000
TTL = 90000


def is_signal(s):
    return bool(s and s.get('pattern') == ROUTE)


def context(b):
    # Fix the EMA input length so REST(100) and the rolling cache agree exactly.
    if len(b) < 55:
        raise ValueError('EMA20 확정봉 55개 대기')
    b = b[-55:]
    value = sum(r[4] for r in b[:20])/20
    values = [value]
    for r in b[20:]:
        value += (r[4]-value)*2/21
        values.append(value)
    from phone_trend_slot import atr
    return dict(context_volume=b[-1][5]/(sum(r[5] for r in b[-21:-1])/20) if sum(r[5] for r in b[-21:-1]) else None, ema20=values[-1], previous_ema=values[-2], rising=values[-1]>values[-2],
                atr=atr(b), baseline_ms=int(b[-1][0]),
                fingerprint=hashlib.sha256(json.dumps([[float(x) for x in r[:6]] for r in b],
                    separators=(',',':')).encode()).hexdigest())


def closed_proof(b, now):
    c = context(b); last = b[-1]; start = int(last[0])+STEP
    if not start <= now <= start+TTL:
        return None, '확정봉 지지 반등 90초 경과'
    if not c['rising']:
        return None, 'EMA20 상승 방향 대기'
    # The previous close is above its own causal EMA; the confirmation's low
    # touches the EMA band and closes bullish back above the updated EMA.
    if not (b[-2][4] >= c['previous_ema'] and
            last[3] <= max(c['ema20'],c['previous_ema']) <= last[2] and
            last[4] > c['ema20'] and last[4] > last[1]):
        return None, 'EMA20 눌림·지지 회복 대기'
    return dict(c, mode='closed', reference=last[4], support_low=last[3],
                confirmation_ms=int(last[0]), trigger_ms=start, quote_ms=None), None


def observed_proof(state, b, q, now):
    c = context(b); bar = now//STEP*STEP
    if not q:
        return None, '실시간 체결가 대기'
    try:
        price, stamp = float(q['last']), int(q['ts'])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, '실시간 체결가 대기'
    if not math.isfinite(price) or price<=0 or not 0<=now-stamp<=15000 or stamp<bar:
        return None, '실시간 체결가 갱신 대기'
    arm = state.get('touch')
    if arm and (arm['bar_ms']!=bar or arm['fingerprint']!=c['fingerprint']):
        state['touch'] = arm = None
    if not c['rising'] or b[-1][4] < c['ema20']:
        state['touch'] = None
        return None, 'EMA20 상승·위쪽 눌림 대기'
    if price <= c['ema20']:
        # Persist a real touch, not a hypothetical fill or a chart interpolation.
        if not arm:
            state['touch'] = dict(bar_ms=bar, fingerprint=c['fingerprint'],
                                  touch_ms=stamp, support_low=price)
        elif price < arm['support_low']:
            arm['support_low'] = price
        return None, 'EMA20 접촉 확인 · 위로 회복 대기'
    if arm and stamp > arm['touch_ms']:
        return dict(c, mode='live', reference=price, support_low=arm['support_low'],
                    confirmation_ms=int(b[-1][0]), trigger_ms=now, quote_ms=stamp,
                    touch_ms=arm['touch_ms'], bar_ms=bar), None
    return None, 'EMA20 눌림·지지 회복 대기'


def make_signal(symbol, proof, rank, now):
    from phone_trend_slot import make_signal as trend_signal
    p = dict(proof, action='LONG', structural_stop=proof['reference']-2*proof['atr'],
             route721=ROUTE, armed_ms=proof['trigger_ms'], trend130=True)
    s = trend_signal(symbol, p, rank, now)
    # One support entry per symbol/candle, shared across live and closed evidence.
    bar = proof.get('bar_ms', proof['confirmation_ms'])
    key = symbol+'|'+str(rank['day'])+'|'+str(bar)
    s.update(pattern=ROUTE, signal_id='ema170-'+hashlib.sha256(key.encode()).hexdigest()[:24],
             valid_from_ms=proof['trigger_ms'], expires_ms=proof['trigger_ms']+TTL,
             reason='상승1위 · 상승 EMA20 접촉 후 지지 회복 · 기존 추세 OR · 5배',
             regime='상승1위 EMA20 지지 반등')
    s['decision_record']['source'] = ROUTE
    return s


def scan(e):
    from phone_trend_slot import snapshot_ranks, completed, in_window
    state = e.journal.data.setdefault(STATE, dict(pending=None,touch=None,leader_key=None))
    before = copy.deepcopy(state)
    e.phone_support_diagnostic = {}
    status = 'EMA20 지지 반등 검사 대기'
    result = None
    try:
        now=e.api.now_ms(); rows,rank,_=snapshot_ranks(e,now//STEP*STEP)
        key=[rank['day'],rank['symbol']] if rank else None
        if state.get('leader_key')!=key:
            state.update(leader_key=key,pending=None,touch=None)
        if not in_window(now):
            state.update(pending=None,touch=None)
            status='EMA20 신규 진입 KST15시~다음02시'
            return None
        if not rank:
            status='상승 1위 대기';return None
        b=completed(rows[0]['live_frames'].get('15m',[]),now,STEP,55)
        c=context(b)
        detail=dict(symbol=rank['symbol'],observed_ms=now,ema20=c['ema20'],
                    baseline_ms=c['baseline_ms'],rising=c['rising'])
        e.phone_support_diagnostic=detail
        pending=state.get('pending')
        if pending:
            seen=rank['symbol']+':'+pending['signal_id'] in e.journal.data.get('seen_signals',{})
            if now>pending['expires_ms'] or seen:
                state['pending']=None
                status='EMA20 신호 처리·만료 · 다음 지지 반등 대기'
                return None
            status='EMA20 지지 반등 확인 · 주문 검사 대기'
            result=copy.deepcopy(pending);return result
        p,status=closed_proof(b,now)
        if not p:
            stream=getattr(e,'stream',None)
            q=stream.read(rank['symbol'],'tickers',15,now) if stream else None
            p,status=observed_proof(state,b,q,now)
        if p:
            s=make_signal(rank['symbol'],p,rank,now)
            # Seen IDs and the original expiry are durable; failed/expired
            # observations cannot get a new 90s just by rescanning/restarting.
            ledger=state.setdefault('observed_signals',{})
            prior=ledger.get(s['signal_id']) or {}
            if prior.get('signal_id')==s['signal_id']:
                s['valid_from_ms']=prior['valid_from_ms'];s['expires_ms']=prior['expires_ms']
            if (rank['symbol']+':'+s['signal_id'] in e.journal.data.get('seen_signals',{})
                    or now>s['expires_ms']):
                status='EMA20 해당 봉 처리·만료 · 다음 지지 반등 대기'
                return None
            ledger[s['signal_id']]={k:s[k] for k in ('signal_id','valid_from_ms','expires_ms')}
            # Keep identities through the candle close, including leader churn.
            state['observed_signals']={k:v for k,v in ledger.items()
                if now-v['valid_from_ms']<=2*STEP+TTL}
            state.update(pending=s,touch=None)
            status='EMA20 지지 반등 확인 · 주문 검사 대기'
            result=copy.deepcopy(s)
        return result
    except (ValueError,KeyError,TypeError,IndexError,OverflowError) as error:
        status=str(error)
        # Data gaps invalidate a live touch. Keep pending's first expiry so a
        # reconnect cannot silently extend the original signal lifetime.
        state['touch']=None
        return None
    finally:
        e.phone_support_status=status
        if state!=before:e.journal.save()


def validate_entry(e,s,price):
    from okx_core import BotError
    from okx_band_flow import rows as parse
    from phone_trend_slot import completed,in_window,require_slot
    from phone_live_rank import check
    from pathlib import Path
    now=e.api.now_ms()
    try:
        if not is_signal(s) or s.get('action')!='LONG' or s.get('leverage')!=5:
            raise ValueError('EMA20 신호·방향·배율 불일치')
        if (Path(e.root).parent/'phone_trend_activation_hold').exists():
            raise ValueError('새 실행기 준비 확인 후 추세 진입 재개')
        if not in_window(now):raise ValueError('추세 신규 진입 시간 종료 · KST15시~다음02시')
        if not s['valid_from_ms']<=now<=s['expires_ms']:raise ValueError('EMA20 신호 90초 만료')
        require_slot(e,s);check(e,s)
        pending=e.journal.data.get(STATE,{}).get('pending')
        if (not pending or any(pending.get(k)!=s.get(k) for k in
                ('signal_id','stop','atr','valid_from_ms','expires_ms','entry_reference')) or
                pending['decision_record']['volume_wick_proof']!=s['decision_record']['volume_wick_proof']):
            raise ValueError('저장된 EMA20 신호 불일치')
        raw=parse(e.api.public('/api/v5/market/candles',instId=s['symbol'],bar='15m',limit='100'),'15m',now)
        b=completed(raw,now,STEP,55);c=context(b);p=s['decision_record']['volume_wick_proof']
        # A just-closed live-trigger bar may advance the baseline during its
        # 90s admission window. Validate the original closed prefix causally.
        original=[r for r in b if int(r[0])<=p['baseline_ms']]
        if len(original)<55 or context(original)['fingerprint']!=p['fingerprint']:
            raise ValueError('EMA20 원래 확정봉 변경')
        if p['mode']=='closed':
            verified,_=closed_proof(original,p['trigger_ms'])
            if not verified:raise ValueError('EMA20 지지 반등 조건 변경')
        elif p['mode']!='live' or not(p['touch_ms']<p['quote_ms']<=p['trigger_ms']):
            raise ValueError('EMA20 접촉·회복 관측 불일치')
        price=float(price)
        if (not math.isfinite(price) or price<=c['ema20'] or
                not 0<price-s['stop']<.09*price or abs(price-p['reference'])>.5*p['atr']):
            raise ValueError('EMA20 회복 이탈 또는 진입 호가·손절 범위 이탈')
        if any(r[0]>=p['trigger_ms']//STEP*STEP and r[3]<=s['stop'] for r in raw):
            raise ValueError('EMA20 대기 중 초기SL 도달')
        check(e,s)
        return p
    except (ValueError,KeyError,TypeError,IndexError,OverflowError) as error:
        raise BotError(str(error)) from None
