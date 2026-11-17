"""Display-only account valuation, isolated from trading I/O and admission.

One read-only worker per host, not per browser. Never transfers funds or sizes
orders from funding/total balances. An unavailable value is never zero-filled.
"""
import threading
import time
from phone_dashboard_live import number


def capture_available_basis(engine, snapshot):
    from okx_core import day_key
    day = engine.journal.data.get('day')
    value = number(snapshot.get('available'))
    if not day or day.get('date') != day_key(snapshot['ms']) or value is None or value < 0:
        return
    if 'display_available_base' in day:
        return
    day['display_available_base'] = str(value)
    day['display_available_ms'] = snapshot['ms']
    try:
        engine.journal.save()
    except Exception:
        day.pop('display_available_base', None)
        day.pop('display_available_ms', None)
        # Optional display persistence must not stop original protection work.


def install_basis(engine):
    if getattr(engine, '_home_basis1610', False):
        return
    original = engine.refresh_day
    def refresh(snapshot):
        result = original(snapshot)
        try:
            capture_available_basis(engine, snapshot)
        except Exception:
            pass
        return result
    engine.refresh_day = refresh
    engine._home_basis1610 = True


def profit_basis(state, basis, now):
    from okx_core import day_key
    day = basis.get('day') or {}
    base = number(day.get('display_available_base'))
    profit = number(state.get('day_profit'))
    valid = day.get('date') == day_key(now) and base is not None and base > 0
    return dict(base=str(base) if valid else None,
                observed_ms=day.get('display_available_ms') if valid else None,
                percent=str(profit / base * 100) if valid and profit is not None else None)


def valuation_client(keys):
    from phone_account import readonly_client
    api = readonly_client(keys)
    # Funding display must not acquire or poison the trading shared-clock lock.
    def sync():
        rows = api.request('GET', '/api/v5/public/time', private=False)
        stamp = int(rows[0]['ts'])
        if stamp <= 0:
            raise ValueError('invalid clock')
        api.server_ms = stamp
        api.anchor = api.synced = time.monotonic()
    api.sync = sync
    return api


class HomeAssets:
    def __init__(self, keys, closed, factory=valuation_client, clock=time.monotonic):
        self.keys, self.closed, self.factory, self.clock = keys, closed, factory, clock
        self.lock = threading.Lock()
        self.values = None
        self.seen = None
        self.failed = False
        self.thread = None

    def poll(self, api):
        rows = api.request('GET', '/api/v5/asset/asset-valuation', params={'ccy': 'USDT'})
        if len(rows) != 1:
            raise ValueError('valuation missing')
        row = rows[0]
        funding, total = number((row.get('details') or {}).get('funding')), number(row.get('totalBal'))
        stamp = int(row.get('ts') or 0)
        if funding is None or total is None or funding < 0 or stamp <= 0:
            raise ValueError('invalid valuation')
        if abs(api.now_ms() - stamp) > 90000:
            raise ValueError('stale valuation')
        values = dict(funding=str(funding), total=str(total), observed_ms=stamp)
        with self.lock:
            self.values, self.seen, self.failed = values, self.clock(), False

    def snapshot(self):
        with self.lock:
            age = max(0, self.clock() - self.seen) if self.seen is not None else None
            return dict(self.values or dict(funding=None, total=None, observed_ms=None),
                        stale=self.failed or age is None or age > 90)

    def run(self):
        api = None
        failures = 0
        try:
            while not self.closed.is_set():
                try:
                    if api is None:
                        api = self.factory(self.keys)
                    self.poll(api)
                    failures = 0
                except Exception:
                    failures = min(failures + 1, 3)
                    with self.lock:
                        self.failed = True
                if self.closed.wait(min(60, 15 * 2 ** max(0, failures - 1))):
                    break
        finally:
            if api is not None:
                api.session.close()

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name='home-assets-read', daemon=True)
            self.thread.start()
