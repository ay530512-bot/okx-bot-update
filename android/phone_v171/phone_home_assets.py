"""Display-only account valuation, isolated from trading I/O and admission.

One read-only worker per host, not per browser. Never transfers funds or sizes
orders from funding/total balances. An unavailable value is never zero-filled.
"""
import threading
import time
from phone_dashboard_live import number


def project_total_basis(state, assets, today):
    """Use the same total shown on the home card for both display calculations."""
    total = number(assets.get('total'))
    base = total if total is not None and total > 0 else None
    profit = number(state.get('day_profit'))
    ratio = dict(base=str(base) if base is not None else None,
                 observed_ms=assets.get('observed_ms'),
                 stale=bool(assets.get('stale')),
                 percent=None)
    goal = state.get('daily_goal') or {}
    if goal.get('date') == today and profit is not None and base is not None:
        ratio['percent'] = str(profit / base * 100)
    if not goal:
        return ratio

    net = number(goal.get('net_profit'))
    rate = number(goal.get('rate'))
    if goal.get('date') != today or goal.get('status') == 'unavailable' or net is None or base is None or rate is None or rate <= 0:
        state['daily_goal'] = dict(goal, status='unavailable')
        return ratio
    target = base * rate
    previous_target = number(goal.get('target_profit'))
    previous_equity = number(goal.get('target_equity'))
    state['daily_goal'] = dict(
        goal, seed=str(base), target_profit=str(target), net_roi=float(net / base),
        target_equity=str(previous_equity - previous_target + target)
        if previous_equity is not None and previous_target is not None else None,
        progress=float(net / target), remaining=str(max(0, target - net)),
        status='reached' if net >= target else 'tracking', assets_stale=ratio['stale'])
    return ratio


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
