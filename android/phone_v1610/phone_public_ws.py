"""Public-stream recovery only; no account, strategy, REST or order changes.

Install after original source hash verification, before constructing RuleEngine.
Keep the original quote freshness checks, feed processing and reconnect pacing.
Subscription payloads stay below 60 KiB (OKX limit 64 KiB). Normal operations
remain 10 seconds apart; wanted execution channels can use a 1-second interval
within a hard rolling 360/hour budget. Network I/O never owns MarketStream.lock.
"""
import json
import functools
import socket
import ssl
import errno
import selectors
import time
from collections import deque

VERSION = 'phone-public-ws-8'
PING_INTERVAL_SECONDS = 20
PONG_TIMEOUT_SECONDS = 20
MAX_PAYLOAD_BYTES = 60 * 1024
MAX_SUBSCRIPTION_OPERATIONS = 360
MONITOR_READ_BYTES = 16384
STAGES = {'waiting', 'dns', 'tcp', 'tls', 'handshake', 'subscribe',
          'unsubscribe', 'ping', 'receive', 'feed', 'closed'}


class PublicPeerClosed(ConnectionError):
    pass


class PublicHeartbeatTimeout(TimeoutError):
    pass


def payload(op, pairs, priority=()):
    if op not in ('subscribe', 'unsubscribe'):
        raise ValueError('invalid subscription operation')
    items, encoded = [], []
    prefix = '{"op":' + json.dumps(op) + ',"args":['
    size = len(prefix.encode()) + 2
    # All four channels of a valid candidate precede unrelated chart traffic.
    priority = frozenset(priority)
    for symbol, channel in sorted(pairs, key=lambda p: (p[0] not in priority, p[1] == 'tickers', p[0], p[1])):
        arg = json.dumps({'channel': channel, 'instId': symbol}, separators=(',', ':'))
        increment = len(arg.encode()) + bool(items)
        if size + increment > MAX_PAYLOAD_BYTES:
            if not items:
                raise ValueError('subscription argument exceeds payload limit')
            break
        size += increment
        items.append((symbol, channel))
        encoded.append(arg)
    return items, prefix + ','.join(encoded) + ']}'


def diagnostics(stream):
    # Caller holds the short-lived state lock; never stores symbols or payloads.
    if not hasattr(stream, '_public_transport'):
        stream._public_transport = dict(version=VERSION, stage='waiting', frames=0,
            text_pings=0, text_pongs=0, max_frame_gap_s=0.0,
            subscription_frames=0, last_subscription_bytes=0,
            last_disconnect=None, disconnect_count=0, disconnect_history=[], server_notice=None,
            frame_at=None, pong_at=None, pending_ping_at=None,
            last_ping_at=None, pong_rtt_s=None)
    return stream._public_transport


def stage(stream, value):
    with stream.lock:
        diagnostics(stream)['stage'] = value


def tracked_watch(original):
    @functools.wraps(original)
    def update_watch(stream, symbols, monitor=False):
        # Source update_watch semantics and its lock are preserved. Watch changes
        # are rare compared with market frames, so compare once at the writer.
        with stream.lock:
            before=(set(stream.symbols),set(stream.monitor_symbols))
            try:return original(stream,symbols,monitor=monitor)
            finally:
                if before!=(stream.symbols,stream.monitor_symbols):
                    stream._phone_watch_revision=getattr(stream,'_phone_watch_revision',0)+1
                    now=time.monotonic(); desired=stream.pairs()
                    stamps=getattr(stream,'_phone_desired_since',{})
                    stream._phone_desired_since={p:stamps.get(p,now) for p in desired}
    return update_watch


def subscription_state(stream):
    # Active sets are written only by this receiving worker. Send commits have
    # their own revision; reconnect changes generation and replaces the set.
    return (getattr(stream,'_phone_watch_revision',0),stream.generation,
        stream.ws,stream.active_pairs,len(stream.active_pairs),
        getattr(stream,'_phone_subscription_revision',0))


def same_subscription_state(a,b):
    return (a is not None and a[0]==b[0] and a[1]==b[1] and a[2] is b[2]
        and a[3] is b[3] and a[4]==b[4] and a[5]==b[5])


def subscription_wait(stream, urgent, now):
    """Caller holds stream.lock. Public connection only; no trading API budget."""
    history=getattr(stream,'_phone_subscription_times',None)
    if history is None:
        history=stream._phone_subscription_times=deque()
    while history and now-history[0]>=3600:
        history.popleft()
    delay=max(0.,stream.last_subscription+(1 if urgent else 10)-now)
    if len(history)>=MAX_SUBSCRIPTION_OPERATIONS:
        delay=max(delay,history[0]+3600-now)
    return delay


def flush_subscriptions(stream):
    with stream.lock:
        now = time.monotonic()
        if not stream.connected or not stream.ws:
            return
        current=subscription_state(stream)
        if same_subscription_state(getattr(stream,'_phone_subscription_settled',None),current):
            return
        desired = stream.pairs()
        removed = stream.active_pairs-desired
        added = desired-stream.active_pairs
        priority=getattr(stream,'_phone_priority_symbols',frozenset())
        urgent=any(symbol in priority for symbol,channel in added)
        # Warm new execution channels first; otherwise removing an old watch
        # costs an extra ten seconds before the candidate can get its quotes.
        # Removed channels are reconciled on the next rate-limited operation.
        if added:
            op, pairs = 'subscribe', added
        elif removed:
            if now-stream.watch_changed < 2:
                return
            op, pairs = 'unsubscribe', removed
        else:
            stream._phone_subscription_settled=current
            return
        if subscription_wait(stream,urgent,now)>0:
            return
        ws, generation = stream.ws, stream.generation
    items, message = payload(op, pairs, priority)
    if not items:
        return
    with stream.lock:
        if stream.ws is not ws or stream.generation != generation or not stream.connected:
            return
        diagnostics(stream)['stage'] = op
    # One receiving worker is the sole subscription writer, just as in original.
    ws.send(message)
    with stream.lock:
        if stream.ws is not ws or stream.generation != generation or not stream.connected:
            return  # Never commit an old socket's send to a new generation.
        if op == 'subscribe':
            stream.active_pairs.update(items)
            stamps=getattr(stream,'_phone_sent_at',{})
            for pair in items:stamps[pair]=(generation,time.monotonic())
            stream._phone_sent_at=stamps
        else:
            stream.active_pairs.difference_update(items)
            for pair in items:getattr(stream,'_phone_sent_at',{}).pop(pair,None)
        stream._phone_subscription_revision=getattr(stream,'_phone_subscription_revision',0)+1
        stream._phone_subscription_settled=None
        stream.last_subscription = time.monotonic()
        stream._phone_subscription_times.append(stream.last_subscription)
        d = diagnostics(stream)
        d['subscription_frames'] += 1
        d['last_subscription_bytes'] = len(message.encode())


def receive(ws, websocket, stream):
    # This is the same frame assembler used by WebSocket.recv(). Returning
    # control frames exposes the peer's close code instead of losing it.
    opcode, frame = ws.recv_data_frame(control_frame=True)
    now = time.monotonic()
    with stream.lock:
        d = diagnostics(stream)
        if d['frame_at'] is not None:
            d['max_frame_gap_s'] = max(d['max_frame_gap_s'], now-d['frame_at'])
        d['frame_at'] = now
        d['frames'] += 1
        d['stage'] = 'feed'
    if opcode == websocket.ABNF.OPCODE_CLOSE:
        raw = frame.data
        if isinstance(raw, str):
            raw = raw.encode()
        # skip_utf8_validation below replaces only the slow Python validator.
        # Keep strict validation for close reasons as well as complete messages.
        raw[2:].decode('utf-8', errors='strict')
        code = int.from_bytes(raw[:2], 'big') if len(raw) >= 2 else None
        with stream.lock:
            diagnostics(stream)['peer_close_code'] = code
        raise PublicPeerClosed('public peer close')
    if opcode not in (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_BINARY):
        return None  # websocket-client handles protocol ping/pong replies itself.
    message = frame.data
    if isinstance(message, bytes):
        message = message.decode('utf-8')
    if message == 'pong':
        with stream.lock:
            d = diagnostics(stream)
            d['text_pongs'] += 1
            d['pong_at'] = now
            if d.get('last_ping_at') is not None:
                d['pong_rtt_s'] = round(now-d['last_ping_at'], 4)
            d['pending_ping_at'] = None
        return None
    if not message:
        raise PublicPeerClosed('empty public message')
    # Observe server control notices only; never log arbitrary text/connection IDs.
    # No additional parsing for normal market data frames.
    if '"event"' in message[:96]:
        try:
            event = json.loads(message)
            if event.get('event') == 'notice' and str(event.get('code')) == '64008':
                with stream.lock:
                    diagnostics(stream)['server_notice'] = dict(code='64008', observed_at=time.time())
            elif event.get('event') in ('subscribe', 'unsubscribe'):
                arg = event.get('arg') or {}
                pair = (arg.get('instId'), arg.get('channel'))
                with stream.lock:
                    ack = getattr(stream, '_phone_acknowledged', None)
                    if ack is None:
                        ack = stream._phone_acknowledged = set()
                    if event['event'] == 'subscribe' and pair in stream.active_pairs:
                        ack.add(pair)
                    elif event['event'] == 'unsubscribe':
                        ack.discard(pair)
        except (ValueError, TypeError):
            pass
    return message


def ping_if_due(stream, ws):
    # Restore the pre-1.1.7 periodic text keepalive (20 s), without bringing
    # back the 1.1.7 false timeout when live market frames are still arriving.
    # This is a narrow regression candidate, not proof of the EOF root cause.
    now = time.monotonic()
    with stream.lock:
        if stream.ws is not ws or not stream.connected:
            return
        generation = stream.generation
        d = diagnostics(stream)
        pending = d['pending_ping_at']
        last_frame = d['frame_at']
        if pending is not None:
            if last_frame is not None and last_frame > pending:
                # Inbound traffic resumed; no reason to reset the stream.
                d['pending_ping_at'] = None
            elif now - pending >= PONG_TIMEOUT_SECONDS:
                # A genuinely silent socket has failed the idle heartbeat.
                raise PublicHeartbeatTimeout('public heartbeat reply expired')
            else:
                return  # Only one outstanding ping, never a repeated flood.
        if now - stream.last_ping < PING_INTERVAL_SECONDS:
            return
        d['stage'] = 'ping'
    ws.send('ping')
    with stream.lock:
        if stream.ws is not ws or stream.generation != generation or not stream.connected:
            return
        stream.last_ping = time.monotonic()
        d = diagnostics(stream)
        d['text_pings'] += 1
        d['pending_ping_at'] = stream.last_ping
        d['last_ping_at'] = stream.last_ping


def failure_kind(error):
    # Explicit allowlist classification; never publish arbitrary socket messages.
    if isinstance(error, PublicHeartbeatTimeout): return 'idle_timeout'
    if isinstance(error, PublicPeerClosed): return 'peer_close_frame'
    if isinstance(error, ConnectionResetError): return 'tcp_reset'
    if isinstance(error, BrokenPipeError): return 'write_broken_pipe'
    if type(error).__name__ == 'WebSocketConnectionClosedException':
        if str(error) == 'Connection to remote host was lost.': return 'read_eof'
        if str(error) == 'socket is already closed.': return 'socket_already_closed'
        return 'websocket_closed'
    return 'other_transport_error'


def housekeeping(stream, ws, previous, interval=.25):
    now = time.monotonic()
    if now - previous >= interval:
        flush_subscriptions(stream)
        ping_if_due(stream, ws)
        return now
    return previous


def disconnect(stream, ws, generation, error=None):
    """Invalidate snapshots before closing. Called even after failed handshake."""
    with stream.lock:
        d = diagnostics(stream)
        if error is not None:
            # Never record raw server text, frames, URLs or credentials.
            name = type(error).__name__
            now = time.monotonic()
            d['disconnect_count'] += 1
            d['last_disconnect'] = dict(generation=generation, error=name,
                stage=d['stage'], close_code=d.get('peer_close_code'),
                cause=failure_kind(error),
                server_notice=dict(d['server_notice']) if d.get('server_notice') else None,
                connection_uptime_s=round(now-d['connected_at'],3) if d.get('connected_at') is not None else None,
                frame_age_s=round(now-d['frame_at'], 3) if d['frame_at'] is not None else None,
                pong_age_s=round(now-d['pong_at'], 3) if d['pong_at'] is not None else None,
                pending_ping_age_s=round(now-d['pending_ping_at'], 3) if d['pending_ping_at'] is not None else None,
                observed_at=time.time())
            d['disconnect_history'] = (d.get('disconnect_history', [])+[dict(d['last_disconnect'])])[-8:]
            if isinstance(error, ValueError) and str(error).startswith('공개 WS 구독 거절:'):
                stream.error = str(error)[:160]
            else:
                stream.error = name
        # No concurrent run worker is started. A manual reconnect may already
        # have advanced generation, but this still owns the old socket.
        if stream.ws is ws:
            stream.connected = False
            stream.data = {}
            stream.active_pairs = set()
            stream._phone_acknowledged = set()
            stream.ws = None
        d['stage'] = 'closed'
    if ws:
        try:
            ws.close()
        except Exception:
            pass


def recv_checked(sock, size, websocket):
    """Distinguish temporary TLS/read readiness from actual zero-byte EOF.

    Some websocket-client releases turn a selector timeout into None and then
    treat it as a closed socket. Only b'' is EOF here. This adapter is scoped to
    the public connection; TLS verification and frame validation are unchanged.
    """
    if sock is None:
        raise websocket.WebSocketConnectionClosedException('socket is already closed.')
    timeout = sock.gettimeout()
    deadline = None if timeout is None else time.monotonic()+max(0,timeout)
    while True:
        event = selectors.EVENT_READ
        try:
            chunk = sock.recv(size)
        except ssl.SSLWantWriteError:
            event = selectors.EVENT_WRITE
        except (ssl.SSLWantReadError, BlockingIOError):
            pass
        except (socket.timeout, TimeoutError) as error:
            raise websocket.WebSocketTimeoutException('public socket read timed out') from error
        except OSError as error:
            if error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                raise
        else:
            if chunk == b'':
                raise websocket.WebSocketConnectionClosedException('Connection to remote host was lost.')
            if chunk is None:
                raise websocket.WebSocketTimeoutException('public socket temporarily unavailable')
            return chunk
        remaining = None if deadline is None else deadline-time.monotonic()
        if remaining is not None and remaining <= 0:
            raise websocket.WebSocketTimeoutException('public socket readiness timed out')
        with selectors.DefaultSelector() as selector:
            selector.register(sock, event)
            if not selector.select(remaining):
                raise websocket.WebSocketTimeoutException('public socket readiness timed out')


def public_socket_class(websocket, read_ahead=0):
    if type(read_ahead) is not int or not 0 <= read_ahead <= MONITOR_READ_BYTES:
        raise ValueError('public read buffer size')
    class PublicWebSocket(websocket.WebSocket):
        def _recv(self, size):
            # Read available TLS bytes once, then serve the unchanged frame
            # parser's small header/length/payload reads. Never wait for a full
            # buffer, drop ticks, or copy cached bytes into a new connection.
            if size <= 0: return b''
            if getattr(self, '_phone_rx_socket', None) is not self.sock:
                self._phone_rx_socket = self.sock
                self._phone_rx_bytes = b''
                self._phone_rx_offset = 0
            try:
                if not read_ahead:
                    return recv_checked(self.sock, size, websocket)
                if self.sock is None:
                    raise websocket.WebSocketConnectionClosedException('socket is already closed.')
                data = getattr(self, '_phone_rx_bytes', b'')
                offset = getattr(self, '_phone_rx_offset', 0)
                if offset >= len(data):
                    data = recv_checked(self.sock, read_ahead, websocket)
                    self._phone_rx_bytes = data
                    offset = 0
                end = min(len(data), offset+size)
                self._phone_rx_offset = end
                return data[offset:end]
            except websocket.WebSocketConnectionClosedException:
                self._phone_rx_bytes = b''
                self._phone_rx_offset = 0
                sock, self.sock = self.sock, None
                self.connected = False
                if sock is not None:
                    sock.close()
                raise
    return PublicWebSocket


def run(stream):
    import websocket
    while not stream.stop_event.is_set():
        sock = ws = None
        generation = None
        failure = None
        try:
            with stream.lock:
                symbols = stream.pairs()
            if not symbols:
                stream.stop_event.wait(.5)
                continue
            # Reset per-connection timing; retain last disconnect across recovery.
            with stream.lock:
                d = diagnostics(stream)
                d.update(frame_at=None, pong_at=None, pending_ping_at=None, peer_close_code=None, connected_at=None, server_notice=None)
                d.update(last_ping_at=None, pong_rtt_s=None)
            stage(stream, 'dns')
            for info in socket.getaddrinfo('ws.okx.com', 443, socket.AF_INET, socket.SOCK_STREAM):
                stage(stream, 'tcp')
                sock = socket.socket(info[0], info[1], info[2])
                sock.settimeout(10)
                try:
                    sock.connect(info[4])
                    break
                except OSError:
                    sock.close()
                    sock = None
            if sock is None:
                raise OSError('WS IPv4 connection failed')
            stage(stream, 'tls')
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname='ws.okx.com')
            stage(stream, 'handshake')
            # recv_data_frame validates UTF-8 byte-by-byte in Python by default.
            # receive() performs strict CPython decoding on the fully assembled
            # message instead. Fragment, control and TLS checks remain enabled.
            ws = websocket.create_connection('wss://ws.okx.com/ws/v5/public', timeout=10,
                socket=sock, class_=public_socket_class(websocket,
                    MONITOR_READ_BYTES if getattr(stream,'_phone_monitor_only',False) else 0),
                skip_utf8_validation=True)
            ws.settimeout(1)
            with stream.lock:
                stream.ws = ws
                stream.generation += 1
                generation = stream.generation
                stream.connected = True
                stream.data = {}
                stream.error = None
                stream.active_pairs = set()
                stream.last_subscription = -float('inf')
                stream._phone_subscription_times=deque()
                stream._phone_sent_at={}
                stream._phone_acknowledged=set()
                stream._phone_desired_since={p:time.monotonic() for p in stream.pairs()}
                stream.last_ping = time.monotonic()
                diagnostics(stream)['connected_at'] = stream.last_ping
            last_housekeeping = -float('inf')
            while not stream.stop_event.is_set():
                with stream.lock:
                    if stream.ws is not ws or stream.generation != generation or not stream.connected:
                        break
                # Avoid subscription/heartbeat locking on every market frame.
                # Every frame is still received and fed, with no queue/drops.
                last_housekeeping = housekeeping(stream, ws, last_housekeeping)
                stage(stream, 'receive')
                try:
                    message = receive(ws, websocket, stream)
                except websocket.WebSocketTimeoutException:
                    continue
                with stream.lock:
                    if stream.ws is not ws or stream.generation != generation or not stream.connected:
                        break
                if message is not None:
                    stream.feed(message)
                stream.retry_delay = 2
        except Exception as error:
            failure = error
        finally:
            disconnect(stream, ws, generation, failure)
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        stream.stop_event.wait(stream.retry_seconds())


def install():
    import okx_stream
    cls = okx_stream.MarketStream
    if getattr(cls, '_phone_public_version', None) == VERSION:
        return
    cls.update_watch = tracked_watch(cls.update_watch)
    cls.flush_subscriptions = flush_subscriptions
    cls.run = run
    cls._phone_public_version = VERSION
