"""Lazy, bounded, display-only ticker lane for the selected chart.

Uses the existing verified public transport and subscription rate budget. Its
prices never enter the strategy/execution/private-account streams. One socket
and one selected symbol; an idle chart releases its watch and connection.
"""
import threading
import time


def ticker_stream():
    from okx_stream import MarketStream
    from phone_public_ws import install
    from phone_public_lanes import install as lanes
    install();lanes()
    parent = MarketStream()
    return parent._phone_monitor_stream


class ChartQuotes:
    def __init__(self, factory=ticker_stream, clock=time.monotonic):
        self.factory, self.clock = factory, clock
        self.lock = threading.RLock()
        self.stream = None
        self.symbol = None
        self.touched = 0
        self.closed = threading.Event()
        self.worker = None

    def watch(self, symbol):
        with self.lock:
            if self.closed.is_set(): return
            self.touched = self.clock()
            if self.stream is None:
                self.stream = self.factory()
                self.stream.start()
            if symbol != self.symbol:
                self.symbol = symbol
                self.replace_watch({symbol})
            if self.worker is None:
                self.worker = threading.Thread(target=self.run, name='phone-chart-idle', daemon=True)
                self.worker.start()

    def replace_watch(self, symbols):
        # Only this display lane replaces its monitor set. The full-market
        # monitor's union semantics and all execution subscriptions are intact.
        stream = self.stream
        with stream.lock:
            stream.monitor_symbols = set(symbols)
            stream.data = {}
            stream.band_prices = {}
            stream.watch_changed = self.clock()
            stream._phone_priority_symbols = frozenset(symbols)
            stream._phone_watch_revision = getattr(stream, '_phone_watch_revision', 0)+1
            stream._phone_desired_since = {p:self.clock() for p in stream.pairs()}

    def quote(self, symbol, now):
        with self.lock:
            if self.closed.is_set() or symbol != self.symbol or self.stream is None: return None
            self.touched = self.clock()
            stream = self.stream
        return stream.read(symbol, 'tickers', 3, now)

    def band_bar(self, symbol, frame, base):
        with self.lock:
            if symbol != self.symbol or self.stream is None: return list(base)
            stream = self.stream
        return stream.band_bar(symbol, frame, base)

    def expire(self):
        with self.lock:
            if self.symbol and self.clock()-self.touched > 15:
                self.symbol = None
                self.replace_watch(set())
                self.stream.reconnect()

    def run(self):
        while not self.closed.wait(1): self.expire()

    def diagnostic(self, now):
        from phone_public_ws import diagnostics
        with self.lock:
            stream, symbol = self.stream, self.symbol
        if stream is None: return dict(connected=False,symbol=None,frames=0)
        with stream.lock:
            d = diagnostics(stream)
            q = stream.read(symbol,'tickers',3,now) if symbol else None
            return dict(symbol=symbol,connected=stream.connected,generation=stream.generation,
                subscription_pairs=len(stream.active_pairs),frames=d['frames'],
                disconnect_count=d['disconnect_count'],pong_rtt_s=d.get('pong_rtt_s'),
                exchange_age_s=(now-int(q['ts']))/1000 if q else None)

    def close(self):
        self.closed.set()
        with self.lock:
            if self.stream: self.stream.stop()
        if self.worker: self.worker.join(timeout=2)
