"""One execution subscription owner. UI changes cannot evict valid candidates."""
import threading


class Registry:
    def __init__(self, e):
        self.e = e; self.stream = e.stream; self.original = e.stream.update_watch
        self.lock = threading.RLock(); self.requested = set(); self.candidates = set()
        self.stream.update_watch = self.update

    def publish(self):
        # Short critical section only. Underlying stream never performs I/O here.
        import phone_trend_slot as trend
        import phone_morning_short as morning
        now = self.e.api.now_ms()
        priority = {o['symbol'] for o in self.e.records()}
        priority.update(trend.prewarm_symbols(self.e, now))
        priority.update(morning.prewarm_symbols(self.e, now))
        signals = list(getattr(self.e, 'channel_pending', {}).values())
        signals.append(self.e.journal.data.get(trend.STATE, {}).get('pending'))
        signals.append(self.e.journal.data.get(morning.STATE, {}).get('pending'))
        for s in signals:
            if s and s['valid_from_ms'] <= now <= s['expires_ms']: priority.add(s['symbol'])
        s = getattr(self.e, 'executing_signal', None)
        if s: priority.add(s['symbol'])
        keep = set(self.requested) | set(self.candidates) | priority
        with self.stream.lock:
            self.stream._phone_priority_symbols = frozenset(priority)
        self.original(sorted(keep), monitor=False)

    def set_candidates(self, symbols):
        with self.lock:
            self.candidates = set(symbols)
            self.publish()

    def update(self, symbols, monitor=False):
        if monitor: return self.original(symbols, monitor=True)
        with self.lock:
            self.requested = set(symbols)
            self.publish()


def attach(e):
    e.phone_quote_registry = Registry(e)

