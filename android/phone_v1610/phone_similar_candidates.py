"""Pure similarity evidence and ordering of ALREADY VALID common candidates.

This is an uncalibrated similarity score, never a return/win probability or an
entry signal. No API calls, subscriptions, sizing or strategy thresholds.
Completed-bar features run in the existing bounded worker and exact-input cache.
"""
import copy
import math

STEP = 900000
HOUR = 3600000
FIELD = 'similarity_reference169'
THRESHOLD = 75  # Ranking hint only; candidates below it are still considered.


def closed(rows, cutoff, step):
    bars = [r for r in (rows or ()) if r[0]+step <= cutoff]
    if len(bars) < 55 or bars[-1][0]+step != cutoff//step*step:
        raise ValueError('completed history unavailable')
    bars = bars[-220:]
    for i, r in enumerate(bars):
        if len(r) < 6 or r[0] % step or (i and r[0]-bars[i-1][0] != step):
            raise ValueError('candle interval')
        if not all(math.isfinite(float(x)) for x in r[:6]):
            raise ValueError('nonfinite candle')
        if min(r[1:5]) <= 0 or r[5] < 0 or not (r[3] <= min(r[1], r[4]) <= max(r[1], r[4]) <= r[2]):
            raise ValueError('candle range')
    return bars


def ema(values, period=20):
    result = [sum(values[:period])/period]
    for value in values[period:]:
        result.append(result[-1]+2/(period+1)*(value-result[-1]))
    return result


def rsi(values):
    diffs = [b-a for a, b in zip(values, values[1:])]
    up = sum(max(d, 0) for d in diffs[:14])/14
    down = sum(max(-d, 0) for d in diffs[:14])/14
    for d in diffs[14:]:
        up = (up*13+max(d, 0))/14
        down = (down*13+max(-d, 0))/14
    return 50 if up == down == 0 else 100 if down == 0 else 100-100/(1+up/down)


def features(bars, hourly, cutoff):
    try:
        b, h = closed(bars, cutoff, STEP), closed(hourly, cutoff, HOUR)
        prices, hp = [r[4] for r in b], [r[4] for r in h]
        ranges = [max(b[i][2]-b[i][3], abs(b[i][2]-b[i-1][4]), abs(b[i][3]-b[i-1][4])) for i in range(1, len(b))]
        atr = sum(ranges[-14:])/14
        hr = [max(h[i][2]-h[i][3], abs(h[i][2]-h[i-1][4]), abs(h[i][3]-h[i-1][4])) for i in range(1, len(h))]
        ha = sum(hr[-14:])/14
        baseline = sum(r[5] for r in b[-21:-1])/20
        if min(atr, ha, baseline) <= 0:
            return None
        m, hm = ema(prices), ema(hp)
        mid = sum(prices[-20:])/20
        sd = (sum((p-mid)**2 for p in prices[-20:])/20)**.5
        if sd <= 0:
            return None
        shape = []
        for i in range(len(b)-8, len(b)):
            _, o, hi, lo, c, *_ = b[i]
            shape.extend(((c-b[i-1][4])/atr, (c-o)/atr,
                          (hi-max(o,c))/atr, (min(o,c)-lo)/atr))
        relative = b[-1][5]/baseline
        volume = [math.log1p(relative), math.log1p(sum(r[5] for r in b[-3:])/3/baseline),
                  math.log1p(sum(r[5] for r in b[-5:] if r[4]<r[1])/5/baseline)]
        return dict(schema=1, candle_ms=b[-1][0]+STEP, hourly_ms=h[-1][0]+HOUR,
                    chart=shape, indicators=[rsi(prices)/100, (prices[-1]-m[-1])/atr/4,
                    (m[-1]-m[-6])/atr, (prices[-1]-mid)/(2*sd),
                    (hp[-1]-hm[-1])/ha/4, (hm[-1]-hm[-6])/ha],
                    volume=volume, relative_volume=round(relative, 3))
    except (ValueError, TypeError, IndexError, KeyError, ArithmeticError):
        # Missing comparison data never changes the original signal verdict.
        return None


def install_worker(channel, cache):
    original = channel._phone_worker_packet
    memo = cache.wrap(features, 'signal.similarity169')
    def packet(row, cfg, now, *args, **kwargs):
        result = original(row, cfg, now, *args, **kwargs)
        values = row.get('live_frames', {})
        result[FIELD] = memo(values.get('15m'), values.get('1H'), now//STEP*STEP)
        return result
    channel._phone_worker_packet = packet


def attach(signal, packet):
    value = (packet or {}).get(FIELD)
    if value and value.get('candle_ms') == signal.get('valid_from_ms'):
        signal[FIELD] = copy.deepcopy(value)


def capture_selected(signal, rows):
    """One selected reserved signal can precede the background publication.

    Capture only that symbol's existing immutable completed candles; no fetch,
    no wait for a worker and no changed entry verdict if comparison is missing.
    """
    if FIELD in signal:
        return
    row = next((r for r in rows if r['symbol'] == signal['symbol']), None)
    if row:
        values = row.get('live_frames', {})
        attach(signal, {FIELD: features(values.get('15m'), values.get('1H'), signal['valid_from_ms'])})


def anchor(engine):
    records = []
    for owned in engine.records():
        s = owned.get('v4_signal', {})
        if (s.get('click716') or s.get('user_chat_order') or
                owned.get('phase') not in ('active', 'protecting', 'resizing') or
                not (owned.get('has_fill') or owned.get('fill_px'))):
            continue
        if s.get('pattern15') or s.get('trend130') or s.get('morning150'):
            records.append(owned)
    if not records:
        return None, '첫 자동 체결 대기'
    # Equal timestamps retain the journal's slot order, not random client IDs.
    first = min(records, key=lambda r: r.get('entry_ms', 0))
    value = first.get('v4_signal', {}).get(FIELD)
    if not value:
        return None, '기준 포지션의 진입 당시 비교 자료 없음 · 다음 자동 진입부터 적용'
    return dict(symbol=first['symbol'], action=first['direction'].upper(),
                features=value, entry_ms=first['entry_ms']), '기존 조건 통과 후보 중 유사 종목 우선 검토'


def compare(left, right):
    if not left or not right or left.get('schema') != 1 or right.get('schema') != 1:
        return None
    parts = {}
    for key, count in (('chart', 32), ('indicators', 6), ('volume', 3)):
        a, b = left.get(key, []), right.get(key, [])
        if len(a) != count or len(b) != count:
            return None
        try:
            distance = sum(min(abs(x-y), 4) for x,y in zip(a,b))/count
            if not math.isfinite(distance): return None
        except (TypeError, ValueError):
            return None
        parts[key] = round(100/(1+distance), 1)
    parts['score'] = round(.4*parts['chart']+.35*parts['indicators']+.25*parts['volume'], 1)
    return parts


def ordered(items, reference, original_key):
    def key(item):
        old = original_key(item)
        s = item[1]
        score = compare(reference['features'], s.get(FIELD)) if reference and s.get('action') == reference['action'] else None
        priority = score is not None and score['score'] >= THRESHOLD
        # Retain older-expiring signals first. Unavailable/low similarity never
        # rejects an otherwise valid original signal or starves its examination.
        return (old[0], 0 if priority else 1, -score['score'] if priority else 0, *old[1:])
    return sorted(items, key=key) if reference else sorted(items, key=original_key)


def view(reference, status, packets, pending, now):
    result = dict(status=status, observed_ms=now, candidates=[], threshold=THRESHOLD)
    if not reference:
        return result
    result.update(reference_symbol=reference['symbol'], action=reference['action'],
                  reference_ms=reference['features']['candle_ms'])
    candidates = []
    for symbol, packet in packets.items():
        value = packet.get(FIELD)
        if not value or value.get('candle_ms') != now//STEP*STEP:
            continue
        score = compare(reference['features'], value)
        if not score or score['score'] < THRESHOLD:
            continue
        s = pending.get(symbol)
        passed = bool(s and s.get('action') == reference['action'] and s['valid_from_ms'] <= now <= s['expires_ms'])
        candidates.append(dict(symbol=symbol, **score, relative_volume=value['relative_volume'],
                               status='기존 봉 조건 통과 · 최종 검사 대기' if passed else '기존 진입 조건 대기',
                               passed=passed))
    result['candidates'] = sorted(candidates, key=lambda r: (-r['score'], r['symbol']))[:3]
    if not candidates:
        result['status'] = '유사도 75 이상 후보 대기 · 기존 규칙 검사는 계속'
    return result
