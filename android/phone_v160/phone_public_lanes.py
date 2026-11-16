"""Separate whole-market tickers from execution quotes on independent sockets.

Each socket has one reader/subscription writer and its own generation, data,
heartbeat, rate budget and recovery. No quote can cross a generation or be
promoted from the monitoring socket into order admission. No polling, queue,
sampling, account changes or trading API calls are introduced.
"""
import threading

VERSION = 'phone-public-lanes-1'


def owner(stream, symbol, channel):
    """Caller may hold the parent lock. Child never takes the parent lock."""
    if (not getattr(stream, '_phone_monitor_only', False)
            and channel == 'tickers' and symbol not in stream.symbols):
        return getattr(stream, '_phone_monitor_stream', stream)
    return stream


def install():
    import okx_stream
    cls = okx_stream.MarketStream
    if getattr(cls, '_phone_lanes_version', None) == VERSION:
        return
    init, update, read = cls.__init__, cls.update_watch, cls.read
    band, reconnect, stop = cls.band_bar, cls.reconnect, cls.stop

    def initialize(self):
        init(self)
        self._phone_monitor_only = False
        child = object.__new__(cls)
        init(child)
        child._phone_monitor_only = True
        self._phone_monitor_stream = child

    def pairs(self):
        if getattr(self, '_phone_monitor_only', False):
            return {(s, 'tickers') for s in self.monitor_symbols}
        return {(s, ch) for s in self.symbols for ch in self.CHANNELS}

    def watches(self, symbols, monitor=False):
        if getattr(self, '_phone_monitor_only', False):
            return update(self, symbols, monitor=True)
        if not monitor:
            return update(self, symbols, monitor=False)
        # Consumers request a union of ticker coverage, as before. Never let a
        # monitor update clear execution snapshots or delay their subscriptions.
        with self.lock:
            self.monitor_symbols.update(symbols)
            self._phone_monitor_stream.update_watch(self.monitor_symbols, monitor=True)

    def quote(self, symbol, channel, max_age=15, now_ms=None):
        with self.lock:
            lane = owner(self, symbol, channel)
            return read(lane, symbol, channel, max_age, now_ms)

    def candle(self, symbol, frame, base):
        with self.lock:
            return band(owner(self, symbol, 'tickers'), symbol, frame, base)

    def start(self):
        with self.lock:
            if getattr(self, '_phone_reader_started', False):
                return
            self._phone_reader_started = True
        if not self._phone_monitor_only:
            self._phone_monitor_stream.start()
        name = 'okx-monitor-ws' if self._phone_monitor_only else 'okx-execution-ws'
        self._phone_reader = threading.Thread(target=self.run, daemon=True, name=name)
        self._phone_reader.start()

    def restart(self):
        reconnect(self)
        if not self._phone_monitor_only:
            reconnect(self._phone_monitor_stream)

    def shutdown(self):
        stop(self)
        if not self._phone_monitor_only:
            stop(self._phone_monitor_stream)

    cls.__init__, cls.pairs, cls.update_watch = initialize, pairs, watches
    cls.read, cls.band_bar, cls.start = quote, candle, start
    cls.reconnect, cls.stop = restart, shutdown
    cls._phone_lanes_version = VERSION
