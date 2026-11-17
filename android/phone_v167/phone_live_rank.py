"""One continuously refreshed KST09/live-price ranking, with no network fetches.

Consumes the existing full-market REST cache and monitoring WebSocket. Ranking
does not require all symbols' candles; the selected strategy still validates
its own completed candles. Missing live prices never promote a runner-up.
"""
import copy
import functools
import math
import threading

DAY = 86400000
HOUR = 3600000
_INIT = threading.Lock()


def phase(now):
    hour = (now + 9*HOUR) % DAY / HOUR
    if 2 <= hour < 5: return 'wait_short'
    if 5 <= hour < 8: return 'short'
    if 8 <= hour < 15: return 'wait_long'
    return 'long'


class Ranking:
    def __init__(self, engine):
        self.engine = engine
        self.lock = threading.RLock()
        self.value = None

    def read(self, force=False):
        with self.lock:
            now = self.engine.api.now_ms()
            if not force and self.value and 0 <= now-self.value['observed_ms'] < 1000:
                return self.value
            self.value = self.collect(now)
            return self.value

    def collect(self, now):
        from phone_trend_slot import permitted
        from phone_trend_inputs import listed_after_reference
        e = self.engine
        market = getattr(getattr(e, 'universe', None), 'full_market', None)
        data = market.market() if market is not None else {}
        instruments, quotes = data.get('instruments', {}), data.get('quotes', {})
        day = now//DAY*DAY
        out = dict(observed_ms=now, day=day, basis='kst09_live', phase=phase(now),
                   ready=False, universe=len(instruments), eligible=0, quotes_ready=0,
                   missing_quotes=[], baseline_ineligible_count=0, baseline_ineligible=[],
                   leader=None, rows=[])
        stream = getattr(e, 'stream', None)
        if stream is not None and hasattr(stream, 'monitor'):
            stream.monitor(instruments.keys())
        for symbol, instrument in instruments.items():
            if not permitted(dict(symbol=symbol, instrument=instrument), e.cfg):
                continue
            if listed_after_reference(symbol, instrument, day, now):
                out['baseline_ineligible_count'] += 1
                if len(out['baseline_ineligible']) < 8:
                    out['baseline_ineligible'].append(dict(symbol=symbol,
                        reason='09시 이후 상장 · 다음 09시부터 순위 비교'))
                continue
            out['eligible'] += 1
            q = quotes.get(symbol, {})
            try:
                live = stream.read(symbol, 'tickers', 15, now) if stream is not None else None
                if isinstance(live, dict) and int(live.get('ts', 0)) >= int(q.get('ts', 0)):
                    # Never transplant yesterday's reference into today's price.
                    q = dict(q, **live) if int(q.get('ts', 0))//DAY == int(live.get('ts', 0))//DAY else live
                last, base, ts = float(q['last']), float(q['sodUtc0']), int(q['ts'])
                if (not math.isfinite(last) or not math.isfinite(base) or min(last, base) <= 0
                        or ts//DAY != now//DAY or not 0 <= now-ts <= 60000):
                    raise ValueError('current-session quote required')
                gain = last/base-1
                if not math.isfinite(gain): raise ValueError('invalid return')
                out['rows'].append(dict(symbol=symbol, last=last, change=gain, ts=ts))
                out['quotes_ready'] += 1
            except (ValueError, KeyError, TypeError, OverflowError):
                if len(out['missing_quotes']) < 8: out['missing_quotes'].append(symbol)
        out['rows'].sort(key=lambda r: (-r['change'], r['symbol']))
        out['ready'] = bool(out['eligible']) and out['quotes_ready'] == out['eligible']
        if out['ready'] and out['rows'] and out['rows'][0]['change'] > 0:
            r = out['rows'][0]
            out['leader'] = dict(symbol=r['symbol'], gain=r['change'], rank=1,
                day=day, hour=now//HOUR*HOUR, observed_ms=now, quote_ms=r['ts'], basis='kst09_live')
        return out


def service(e):
    with _INIT:
        if not hasattr(e, '_phone_live_rank'):
            e._phone_live_rank = Ranking(e)
        return e._phone_live_rank


def snapshot(e, force=False):
    return service(e).read(force)


def selected(e, force=False):
    result = snapshot(e, force)
    if not result['ready']:
        raise ValueError('전체 현재가 순위 자료 대기: '+str(result['quotes_ready'])+'/'+str(result['eligible']))
    return result['leader']


def selected_rows(e, rank):
    """Only copy the selected symbol's immutable candle references."""
    if not rank: return []
    u = e.universe; symbol = rank['symbol']; now = e.api.now_ms()
    with u.lock:
        m = u.full_market
        instrument = dict(m.instruments[symbol])
        cache = getattr(m, 'band_cache', {})
        frames = {}
        for frame in ('15m', '1H'):
            item = cache.get((symbol, frame))
            bars = item[1] if isinstance(item, tuple) and len(item) == 2 else ()
            frames[frame] = bars if isinstance(bars, tuple) else copy.deepcopy(bars)
    return [dict(symbol=symbol, instrument=instrument, live_frames=frames,
                 observed_ms=None, cache_read_ms=now)]


def prewarm(e, now):
    # Subscription registry holds its own lock. Never acquire ranking/universe
    # locks here: the publisher atomically replaces an immutable snapshot.
    result = getattr(getattr(e, '_phone_live_rank', None), 'value', None)
    if (result and result['ready'] and result['leader']
            and 0 <= now-result['observed_ms'] <= 2000):
        return {result['leader']['symbol']}
    return set()


def check(e, signal):
    from phone_trend_slot import is_signal as long_signal, in_window as long_window
    from phone_morning_short import is_signal as short_signal, in_window as short_window
    from okx_core import BotError
    if not (long_signal(signal) or short_signal(signal)): return
    now = e.api.now_ms()
    window = long_window if long_signal(signal) else short_window
    if not window(now) or not signal['valid_from_ms'] <= now <= signal['expires_ms']:
        raise BotError('전용 주문 직전 시간 종료 또는 신호 만료')
    try: rank = selected(e, force=True)
    except ValueError as error: raise BotError(str(error)) from None
    if (not rank or rank['symbol'] != signal['symbol']
            or rank['day'] != signal['selection']['ranking_start_ms']):
        raise BotError('주문 직전 현재 상승1위 변경')


def install_submission_guard():
    import okx_risk732 as risk
    original = risk.submit_check
    if getattr(original, '_phone_live_rank', False): return
    @functools.wraps(original)
    def submit(e, plan, instrument, direction):
        result = original(e, plan, instrument, direction)
        check(e, e.prepared_signal)
        return result
    submit._phone_live_rank = True
    risk.submit_check = submit


class Publisher:
    """Replacement for the duplicate mobile REST feed; keeps tracking 24h."""
    def __init__(self, engine, events):
        self.engine, self.events = engine, events
        self.stop_event = threading.Event()
        self.thread = None
        self.published = None

    def cached(self):
        # Immutable display snapshot. Strategies still call snapshot()/check()
        # and retain their original freshness/leader revalidation.
        return self.published

    def payload(self):
        value = snapshot(self.engine)
        result = dict(rows=value['rows'], observed_ms=value['observed_ms'], basis='KST09시',
                    stale=not value['ready'], live_rank={k:v for k,v in value.items() if k != 'rows'})
        self.published = result
        return result

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.events.put(('futures_market', self.payload()))
                registry = getattr(self.engine, 'phone_quote_registry', None)
                if registry:
                    with registry.lock: registry.publish()
            except Exception as error:
                self.events.put(('futures_market_error', type(error).__name__))
            self.stop_event.wait(1)

    def start(self):
        self.thread = threading.Thread(target=self.run, name='phone-live-rank', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=2)
