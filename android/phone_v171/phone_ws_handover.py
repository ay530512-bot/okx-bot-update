"""Warm a replacement public socket after OKX 64008; no account/order I/O.

The current reader keeps receiving while one bounded worker confirms the new
subscriptions. Only the current reader adopts it. Fresh replacement snapshots
get a new generation; old-generation data is never promoted. Warm failures keep
the current socket alive. A cancelled/changed owner cannot adopt a late result.
"""
import threading
import time

WARM_SECONDS = 18
READY_MAX_AGE = 2
RETRY_SECONDS = 10


class Pending:
    def __init__(self, stream):
        from okx_stream import MarketStream
        self.original_ws = stream.ws
        self.original_generation = stream.generation
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.ready = False
        self.taken = False
        self.error = None
        self.ready_at = None
        self.lock = threading.Lock()
        self.shadow = MarketStream()
        self.shadow._phone_monitor_only = getattr(stream, '_phone_monitor_only', False)
        self.shadow.symbols = set(stream.symbols)
        self.shadow.monitor_symbols = set(stream.monitor_symbols)
        self.shadow._phone_priority_symbols = getattr(stream, '_phone_priority_symbols', frozenset())
        self.wanted = frozenset(stream.pairs())
        self.raw = None
        self.closing = False

    def close(self):
        self.cancel.set()
        with self.lock:
            if self.taken or self.closing:
                return
            self.closing = True
            sockets = (self.shadow.ws, self.raw)
        # May be called with the owner's state lock. Close never owns that lock.
        threading.Thread(target=close_sockets, args=(sockets,), daemon=True,
                         name='okx-retired-public').start()


def close_sockets(sockets):
    for ws in sockets:
        if ws is not None:
            try: ws.close(timeout=.1)
            except TypeError:
                try: ws.close()
                except Exception: pass
            except Exception: pass


def ready(p, now=None):
    s = p.shadow
    now = time.monotonic() if now is None else now
    with s.lock:
        if not s.connected or s._public_transport.get('server_notice'):
            return False
        if not p.wanted <= getattr(s, '_phone_acknowledged', set()):
            return False
        # Trades may be quiet. Keep the ordinary admission trade-age check;
        # never fabricate a trade or borrow one from the retiring connection.
        required = {pair for pair in p.wanted if pair[1] != 'trades'}
        return bool(required) and all(pair in s.data and
            s.data[pair][2] == s.generation and 0 <= now-s.data[pair][1] <= READY_MAX_AGE
            for pair in required)


def warm(p):
    import websocket
    import phone_public_ws as wire
    deadline = time.monotonic()+WARM_SECONDS
    try:
        ws, raw = wire.connect(p.shadow, cancelled=p.cancel, register=lambda s: register(p, s))
        with p.lock:
            p.raw = raw
            if p.cancel.is_set():
                ws.close()
                return
            wire.activate(p.shadow, ws)
        last = -float('inf')
        while not p.cancel.is_set() and time.monotonic() < deadline:
            last = wire.housekeeping(p.shadow, ws, last)
            try: message = wire.receive(ws, websocket, p.shadow)
            except websocket.WebSocketTimeoutException: continue
            if message is not None: p.shadow.feed(message)
            if ready(p):
                with p.lock:
                    if not p.cancel.is_set():
                        p.ready = True
                        p.ready_at = time.monotonic()
                return
        p.error = 'warm_timeout'
    except Exception as error:
        p.error = type(error).__name__
    finally:
        if not p.ready: p.close()
        # After done the worker will never read or write this socket again.
        p.done.set()


def register(p, sock):
    with p.lock:
        p.raw = sock
        cancelled = p.cancel.is_set()
    if cancelled:
        sock.close()
        raise ConnectionAbortedError('public handover cancelled')


def abandon(stream):
    with stream.lock:
        p = getattr(stream, '_phone_upgrade_pending', None)
        stream._phone_upgrade_pending = None
    if p is not None: p.close()


def poll(stream):
    import phone_public_ws as wire
    old = None
    with stream.lock:
        p = getattr(stream, '_phone_upgrade_pending', None)
        now = time.monotonic()
        d = wire.diagnostics(stream)
        if stream.stop_event.is_set():
            if p is not None: p.close()
            stream._phone_upgrade_pending = None
            return False
        if p is None:
            if (not stream.connected or not d.get('server_notice') or
                    now < getattr(stream, '_phone_upgrade_retry_at', 0)):
                return False
            p = Pending(stream)
            stream._phone_upgrade_pending = p
            d['upgrade_attempts'] = d.get('upgrade_attempts', 0)+1
            threading.Thread(target=warm, args=(p,), daemon=True,
                             name='okx-public-upgrade').start()
            return False
        if stream.ws is not p.original_ws or stream.generation != p.original_generation:
            p.close()
            stream._phone_upgrade_pending = None
            return False
        if not p.done.is_set():
            return False
        if not p.ready or now-p.ready_at > READY_MAX_AGE or frozenset(stream.pairs()) != p.wanted or not ready(p, now):
            p.close()
            stream._phone_upgrade_pending = None
            stream._phone_upgrade_retry_at = now+RETRY_SECONDS
            d['upgrade_failures'] = d.get('upgrade_failures', 0)+1
            return False
        with p.lock:
            if p.cancel.is_set(): return False
            shadow = p.shadow
            old = stream.ws
            new_generation = stream.generation+1
            stream.ws = shadow.ws
            stream.generation = new_generation
            stream.connected = True
            stream.error = None
            stream.data = {key:(value[0], value[1], new_generation) for key,value in shadow.data.items()
                           if key in p.wanted and value[2] == shadow.generation}
            stream.band_prices = {key:(*value[:4], new_generation) for key,value in shadow.band_prices.items()
                                  if value[4] == shadow.generation}
            for name in ('active_pairs','last_subscription','last_ping','_phone_subscription_times',
                         '_phone_acknowledged','_phone_desired_since'):
                setattr(stream, name, getattr(shadow, name))
            stream._phone_sent_at = {key:(new_generation, value[1]) for key,value in shadow._phone_sent_at.items()}
            stream._phone_subscription_settled = None
            stream._phone_subscription_revision = getattr(stream, '_phone_subscription_revision', 0)+1
            sd = wire.diagnostics(shadow)
            for name in ('frame_at','pong_at','pending_ping_at','last_ping_at','pong_rtt_s','connected_at','peer_close_code','server_notice'):
                d[name] = sd.get(name)
            d['stage'] = 'receive'
            d['upgrade_count'] = d.get('upgrade_count', 0)+1
            d['last_upgrade_at'] = time.time()
            for name in ('frames','text_pings','text_pongs','subscription_frames'):
                d[name] = d.get(name, 0)+sd.get(name, 0)
            p.taken = True
            stream._phone_upgrade_pending = None
    # No state lock is held during network close. A replacement mark snapshot
    # is processed by the normal stream reader on its next message; no callback
    # is fired by the warm worker and no order can originate from it.
    if old is not None:
        threading.Thread(target=close_sockets,args=((old,),),daemon=True,
                         name='okx-retired-public').start()
    return True
