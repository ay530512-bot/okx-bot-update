"""Public-stream recovery only; no account, strategy, REST or order changes.

Install after original source hash verification, before constructing RuleEngine.
Keep the original quote freshness checks, feed processing and reconnect pacing.
Subscription payloads stay below 60 KiB (OKX limit 64 KiB); operations remain
at least 10 seconds apart. Network I/O never owns MarketStream.lock.
"""
import json
import socket
import ssl
import time

VERSION = 'phone-public-ws-1'
MAX_PAYLOAD_BYTES = 60 * 1024
STAGES = {'waiting', 'dns', 'tcp', 'tls', 'handshake', 'subscribe',
          'unsubscribe', 'ping', 'receive', 'feed', 'closed'}


class PublicPeerClosed(ConnectionError):
    pass


def payload(op, pairs):
    if op not in ('subscribe', 'unsubscribe'):
        raise ValueError('invalid subscription operation')
    items, encoded = [], []
    prefix = '{"op":' + json.dumps(op) + ',"args":['
    size = len(prefix.encode()) + 2
    # Retain original priority: execution-only channels before universe tickers.
    for symbol, channel in sorted(pairs, key=lambda p: (p[1] == 'tickers', p[0], p[1])):
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
            last_disconnect=None, disconnect_count=0,
            frame_at=None, pong_at=None, pending_ping_at=None)
    return stream._public_transport


def stage(stream, value):
    with stream.lock:
        diagnostics(stream)['stage'] = value


def flush_subscriptions(stream):
    with stream.lock:
        now = time.monotonic()
        if not stream.connected or not stream.ws or now-stream.last_subscription < 10:
            return
        if now-stream.watch_changed < 2:
            return
        desired = stream.pairs()
        removed = stream.active_pairs-desired
        added = desired-stream.active_pairs
        # Match original removal-first policy; do not silently retain old watches.
        if removed:
            op, pairs = 'unsubscribe', removed
        elif added:
            op, pairs = 'subscribe', added
        else:
            return
        ws, generation = stream.ws, stream.generation
    items, message = payload(op, pairs)
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
        else:
            stream.active_pairs.difference_update(items)
        stream.last_subscription = time.monotonic()
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
    if opcode == websocket.ABNF.OPCODE_CLOSE:
        raw = frame.data
        if isinstance(raw, str):
            raw = raw.encode()
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
            d['pending_ping_at'] = None
        return None
    if not message:
        raise PublicPeerClosed('empty public message')
    return message


def ping_if_due(stream, ws):
    now = time.monotonic()
    # Preserve original 20-second text heartbeat. Record missing pong rather
    # than inventing a new liveness threshold that could cause extra reconnects.
    if now-stream.last_ping >= 20:
        stage(stream, 'ping')
        ws.send('ping')
        with stream.lock:
            stream.last_ping = time.monotonic()
            d = diagnostics(stream)
            d['text_pings'] += 1
            if d['pending_ping_at'] is None:
                d['pending_ping_at'] = stream.last_ping


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
                frame_age_s=round(now-d['frame_at'], 3) if d['frame_at'] is not None else None,
                pong_age_s=round(now-d['pong_at'], 3) if d['pong_at'] is not None else None,
                pending_ping_age_s=round(now-d['pending_ping_at'], 3) if d['pending_ping_at'] is not None else None,
                observed_at=time.time())
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
            stream.ws = None
        d['stage'] = 'closed'
    if ws:
        try:
            ws.close()
        except Exception:
            pass


def run(stream):
    import websocket
    while not stream.stop_event.is_set():
        sock = ws = None
        generation = None
        failure = None
        try:
            with stream.lock:
                symbols = stream.symbols | stream.monitor_symbols
            if not symbols:
                stream.stop_event.wait(.5)
                continue
            # Reset per-connection timing; retain last disconnect across recovery.
            with stream.lock:
                d = diagnostics(stream)
                d.update(frame_at=None, pong_at=None, pending_ping_at=None, peer_close_code=None)
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
            ws = websocket.create_connection('wss://ws.okx.com/ws/v5/public', timeout=10, socket=sock)
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
                stream.last_ping = time.monotonic()
            while not stream.stop_event.is_set():
                with stream.lock:
                    if stream.ws is not ws or stream.generation != generation or not stream.connected:
                        break
                flush_subscriptions(stream)
                ping_if_due(stream, ws)
                stage(stream, 'receive')
                try:
                    message = receive(ws, websocket, stream)
                except websocket.WebSocketTimeoutException:
                    continue
                with stream.lock:
                    if stream.ws is not ws or stream.generation != generation or not stream.connected:
                        break
                if message is not None:
                    stage(stream, 'feed')
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
    cls.flush_subscriptions = flush_subscriptions
    cls.run = run
    cls._phone_public_version = VERSION
