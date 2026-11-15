#!/usr/bin/env python3
"""Verified 1.2.3 -> 1.2.4 periodic keepalive regression candidate. Stage then safe serial handover. No exchange orders here."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PINNED = {'phone_host.py': '21b9139454ff32c6afc7a4f0c9dece4540cc4cc9eb1d2a619c8e895f2b8afdce', 'phone_mobile.py': '8bdb7b6d78a7bb038dee1a2e2a8aff7234429c882e8bce6ea4bf9a051e840507', 'phone_account.py': '3c4c9f9cccaeaa60a41cc3ff3fdde68c04372aabcd8861098cefb8d918406f81', 'phone_sources.json': '1e8a54e5baff2e9f77aa48e1335dea650ae74cc1e5ebfaf562d796960d0838c7', 'phone_remote.py': 'f891e8cc8c8e822eb7f75ccd22d441b4b451162de0bf87a134b3c925e9073e97', 'phone_service.py': 'f8fd3f60df8b8c7416b0bbd1045bde11e50a00ead16172e005e2ba20ed4a51cc', 'phone_migrate.py': 'aafbe024259d3f4dffc81b9b4ec7c9e9307a3487efeb969b1feed257f66399fb', 'phone_migration_sources.json': '214293c5bf0d7fd79838b1037ab9499a2a5428c91758fe3df7c439d790e3691d', 'phone_remote_check.py': '7d20cb6dcbbd2d784dab6c9fd8131722175d2f684b2202c3499fc13e8fd194d1', 'phone_clock.py': 'c1465b5e7d796937e16897c28d29d6ea78d4523b1c3a235a3384a97c2af7074c', 'phone_connection_trace.py': '8db7c7d7222b846d010f38b6a733201425ac4b6cbcb19df297b10dfddca5846c', 'phone_public_ws.py': '09c2a06ca2a093dc267aa576505203590d670839fe69def9c8e3a5df59691dce', 'phone_performance.py': '6247cb8f03e118de3ca0420c197a7c3ef61297280f21847e7f4fca78b9c632db', 'phone_signal_cache.py': '071eb2defa234b3055d439ab775e8c9ec0384b8f36b8d0464d241ac442d94827', 'phone_update.py': '516f03e1ec23e811b456fd42d4f44c9abe8104a919566fa0a01d88169b4dda49', 'phone_update_ui.js': '35d08e37dc57561009565de06b01ac1acb2d827bc77841e66faf94b483f709c4', 'phone_button_upgrade.py': '9f657d8561e62391509d666f6aaaa8381f5828fec1768c563e340f6a4f98e23f', 'phone_button_old_sources.json': '30d8bfe29019e4618ed28f8e12ab86849e99b876359bec3fdd295b2db097a459', 'phone_handover.py': '11d26680baa581043998005af8b2016a40a4df1eff7730d9d34b10706c89523c', 'phone_pullback_size.py': '556c076220d5af838cd6082a224388f1ac23869fd7f0c479a220d2f381887f41', 'phone_candidate_fast.py': 'a13ca10ee3884abdff60e230bd3a250ff29d6204e683865e2b12047245b628d6', 'phone_runtime_health.py': '4177c24e5da1806dd0ebc9afcfb13629562474e763c8a97cfe40af608905a38e'}
HOST_OLD = 'host-v21'
HOST_NEW = 'host-v22'
TRANSPORT_MODULE = '"""Public-stream recovery only; no account, strategy, REST or order changes.\n\nInstall after original source hash verification, before constructing RuleEngine.\nKeep the original quote freshness checks, feed processing and reconnect pacing.\nSubscription payloads stay below 60 KiB (OKX limit 64 KiB); operations remain\nat least 10 seconds apart. Network I/O never owns MarketStream.lock.\n"""\nimport json\nimport functools\nimport socket\nimport ssl\nimport errno\nimport selectors\nimport time\n\nVERSION = \'phone-public-ws-4\'\nPING_INTERVAL_SECONDS = 20\nPONG_TIMEOUT_SECONDS = 20\nMAX_PAYLOAD_BYTES = 60 * 1024\nSTAGES = {\'waiting\', \'dns\', \'tcp\', \'tls\', \'handshake\', \'subscribe\',\n          \'unsubscribe\', \'ping\', \'receive\', \'feed\', \'closed\'}\n\n\nclass PublicPeerClosed(ConnectionError):\n    pass\n\n\nclass PublicHeartbeatTimeout(TimeoutError):\n    pass\n\n\ndef payload(op, pairs):\n    if op not in (\'subscribe\', \'unsubscribe\'):\n        raise ValueError(\'invalid subscription operation\')\n    items, encoded = [], []\n    prefix = \'{"op":\' + json.dumps(op) + \',"args":[\'\n    size = len(prefix.encode()) + 2\n    # Retain original priority: execution-only channels before universe tickers.\n    for symbol, channel in sorted(pairs, key=lambda p: (p[1] == \'tickers\', p[0], p[1])):\n        arg = json.dumps({\'channel\': channel, \'instId\': symbol}, separators=(\',\', \':\'))\n        increment = len(arg.encode()) + bool(items)\n        if size + increment > MAX_PAYLOAD_BYTES:\n            if not items:\n                raise ValueError(\'subscription argument exceeds payload limit\')\n            break\n        size += increment\n        items.append((symbol, channel))\n        encoded.append(arg)\n    return items, prefix + \',\'.join(encoded) + \']}\'\n\n\ndef diagnostics(stream):\n    # Caller holds the short-lived state lock; never stores symbols or payloads.\n    if not hasattr(stream, \'_public_transport\'):\n        stream._public_transport = dict(version=VERSION, stage=\'waiting\', frames=0,\n            text_pings=0, text_pongs=0, max_frame_gap_s=0.0,\n            subscription_frames=0, last_subscription_bytes=0,\n            last_disconnect=None, disconnect_count=0,\n            frame_at=None, pong_at=None, pending_ping_at=None)\n    return stream._public_transport\n\n\ndef stage(stream, value):\n    with stream.lock:\n        diagnostics(stream)[\'stage\'] = value\n\n\ndef tracked_watch(original):\n    @functools.wraps(original)\n    def update_watch(stream, symbols, monitor=False):\n        # Source update_watch semantics and its lock are preserved. Watch changes\n        # are rare compared with market frames, so compare once at the writer.\n        with stream.lock:\n            before=(set(stream.symbols),set(stream.monitor_symbols))\n            try:return original(stream,symbols,monitor=monitor)\n            finally:\n                if before!=(stream.symbols,stream.monitor_symbols):\n                    stream._phone_watch_revision=getattr(stream,\'_phone_watch_revision\',0)+1\n    return update_watch\n\n\ndef subscription_state(stream):\n    # Active sets are written only by this receiving worker. Send commits have\n    # their own revision; reconnect changes generation and replaces the set.\n    return (getattr(stream,\'_phone_watch_revision\',0),stream.generation,\n        stream.ws,stream.active_pairs,len(stream.active_pairs),\n        getattr(stream,\'_phone_subscription_revision\',0))\n\n\ndef same_subscription_state(a,b):\n    return (a is not None and a[0]==b[0] and a[1]==b[1] and a[2] is b[2]\n        and a[3] is b[3] and a[4]==b[4] and a[5]==b[5])\n\n\ndef flush_subscriptions(stream):\n    with stream.lock:\n        now = time.monotonic()\n        if not stream.connected or not stream.ws or now-stream.last_subscription < 10:\n            return\n        if now-stream.watch_changed < 2:\n            return\n        current=subscription_state(stream)\n        if same_subscription_state(getattr(stream,\'_phone_subscription_settled\',None),current):\n            return\n        desired = stream.pairs()\n        removed = stream.active_pairs-desired\n        added = desired-stream.active_pairs\n        # Warm new execution channels first; otherwise removing an old watch\n        # costs an extra ten seconds before the candidate can get its quotes.\n        # Removed channels are reconciled on the next rate-limited operation.\n        if added:\n            op, pairs = \'subscribe\', added\n        elif removed:\n            op, pairs = \'unsubscribe\', removed\n        else:\n            stream._phone_subscription_settled=current\n            return\n        ws, generation = stream.ws, stream.generation\n    items, message = payload(op, pairs)\n    if not items:\n        return\n    with stream.lock:\n        if stream.ws is not ws or stream.generation != generation or not stream.connected:\n            return\n        diagnostics(stream)[\'stage\'] = op\n    # One receiving worker is the sole subscription writer, just as in original.\n    ws.send(message)\n    with stream.lock:\n        if stream.ws is not ws or stream.generation != generation or not stream.connected:\n            return  # Never commit an old socket\'s send to a new generation.\n        if op == \'subscribe\':\n            stream.active_pairs.update(items)\n        else:\n            stream.active_pairs.difference_update(items)\n        stream._phone_subscription_revision=getattr(stream,\'_phone_subscription_revision\',0)+1\n        stream._phone_subscription_settled=None\n        stream.last_subscription = time.monotonic()\n        d = diagnostics(stream)\n        d[\'subscription_frames\'] += 1\n        d[\'last_subscription_bytes\'] = len(message.encode())\n\n\ndef receive(ws, websocket, stream):\n    # This is the same frame assembler used by WebSocket.recv(). Returning\n    # control frames exposes the peer\'s close code instead of losing it.\n    opcode, frame = ws.recv_data_frame(control_frame=True)\n    now = time.monotonic()\n    with stream.lock:\n        d = diagnostics(stream)\n        if d[\'frame_at\'] is not None:\n            d[\'max_frame_gap_s\'] = max(d[\'max_frame_gap_s\'], now-d[\'frame_at\'])\n        d[\'frame_at\'] = now\n        d[\'frames\'] += 1\n        d[\'stage\'] = \'feed\'\n    if opcode == websocket.ABNF.OPCODE_CLOSE:\n        raw = frame.data\n        if isinstance(raw, str):\n            raw = raw.encode()\n        code = int.from_bytes(raw[:2], \'big\') if len(raw) >= 2 else None\n        with stream.lock:\n            diagnostics(stream)[\'peer_close_code\'] = code\n        raise PublicPeerClosed(\'public peer close\')\n    if opcode not in (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_BINARY):\n        return None  # websocket-client handles protocol ping/pong replies itself.\n    message = frame.data\n    if isinstance(message, bytes):\n        message = message.decode(\'utf-8\')\n    if message == \'pong\':\n        with stream.lock:\n            d = diagnostics(stream)\n            d[\'text_pongs\'] += 1\n            d[\'pong_at\'] = now\n            d[\'pending_ping_at\'] = None\n        return None\n    if not message:\n        raise PublicPeerClosed(\'empty public message\')\n    return message\n\n\ndef ping_if_due(stream, ws):\n    # Restore the pre-1.1.7 periodic text keepalive (20 s), without bringing\n    # back the 1.1.7 false timeout when live market frames are still arriving.\n    # This is a narrow regression candidate, not proof of the EOF root cause.\n    now = time.monotonic()\n    with stream.lock:\n        if stream.ws is not ws or not stream.connected:\n            return\n        generation = stream.generation\n        d = diagnostics(stream)\n        pending = d[\'pending_ping_at\']\n        last_frame = d[\'frame_at\']\n        if pending is not None:\n            if last_frame is not None and last_frame > pending:\n                # Inbound traffic resumed; no reason to reset the stream.\n                d[\'pending_ping_at\'] = None\n            elif now - pending >= PONG_TIMEOUT_SECONDS:\n                # A genuinely silent socket has failed the idle heartbeat.\n                raise PublicHeartbeatTimeout(\'public heartbeat reply expired\')\n            else:\n                return  # Only one outstanding ping, never a repeated flood.\n        if now - stream.last_ping < PING_INTERVAL_SECONDS:\n            return\n        d[\'stage\'] = \'ping\'\n    ws.send(\'ping\')\n    with stream.lock:\n        if stream.ws is not ws or stream.generation != generation or not stream.connected:\n            return\n        stream.last_ping = time.monotonic()\n        d = diagnostics(stream)\n        d[\'text_pings\'] += 1\n        d[\'pending_ping_at\'] = stream.last_ping\n\n\ndef failure_kind(error):\n    # Explicit allowlist classification; never publish arbitrary socket messages.\n    if isinstance(error, PublicHeartbeatTimeout): return \'idle_timeout\'\n    if isinstance(error, PublicPeerClosed): return \'peer_close_frame\'\n    if isinstance(error, ConnectionResetError): return \'tcp_reset\'\n    if isinstance(error, BrokenPipeError): return \'write_broken_pipe\'\n    if type(error).__name__ == \'WebSocketConnectionClosedException\':\n        if str(error) == \'Connection to remote host was lost.\': return \'read_eof\'\n        if str(error) == \'socket is already closed.\': return \'socket_already_closed\'\n        return \'websocket_closed\'\n    return \'other_transport_error\'\n\n\ndef housekeeping(stream, ws, previous, interval=.25):\n    now = time.monotonic()\n    if now - previous >= interval:\n        flush_subscriptions(stream)\n        ping_if_due(stream, ws)\n        return now\n    return previous\n\n\ndef disconnect(stream, ws, generation, error=None):\n    """Invalidate snapshots before closing. Called even after failed handshake."""\n    with stream.lock:\n        d = diagnostics(stream)\n        if error is not None:\n            # Never record raw server text, frames, URLs or credentials.\n            name = type(error).__name__\n            now = time.monotonic()\n            d[\'disconnect_count\'] += 1\n            d[\'last_disconnect\'] = dict(generation=generation, error=name,\n                stage=d[\'stage\'], close_code=d.get(\'peer_close_code\'),\n                cause=failure_kind(error),\n                connection_uptime_s=round(now-d[\'connected_at\'],3) if d.get(\'connected_at\') is not None else None,\n                frame_age_s=round(now-d[\'frame_at\'], 3) if d[\'frame_at\'] is not None else None,\n                pong_age_s=round(now-d[\'pong_at\'], 3) if d[\'pong_at\'] is not None else None,\n                pending_ping_age_s=round(now-d[\'pending_ping_at\'], 3) if d[\'pending_ping_at\'] is not None else None,\n                observed_at=time.time())\n            if isinstance(error, ValueError) and str(error).startswith(\'공개 WS 구독 거절:\'):\n                stream.error = str(error)[:160]\n            else:\n                stream.error = name\n        # No concurrent run worker is started. A manual reconnect may already\n        # have advanced generation, but this still owns the old socket.\n        if stream.ws is ws:\n            stream.connected = False\n            stream.data = {}\n            stream.active_pairs = set()\n            stream.ws = None\n        d[\'stage\'] = \'closed\'\n    if ws:\n        try:\n            ws.close()\n        except Exception:\n            pass\n\n\ndef recv_checked(sock, size, websocket):\n    """Distinguish temporary TLS/read readiness from actual zero-byte EOF.\n\n    Some websocket-client releases turn a selector timeout into None and then\n    treat it as a closed socket. Only b\'\' is EOF here. This adapter is scoped to\n    the public connection; TLS verification and frame validation are unchanged.\n    """\n    if sock is None:\n        raise websocket.WebSocketConnectionClosedException(\'socket is already closed.\')\n    timeout = sock.gettimeout()\n    deadline = None if timeout is None else time.monotonic()+max(0,timeout)\n    while True:\n        event = selectors.EVENT_READ\n        try:\n            chunk = sock.recv(size)\n        except ssl.SSLWantWriteError:\n            event = selectors.EVENT_WRITE\n        except (ssl.SSLWantReadError, BlockingIOError):\n            pass\n        except (socket.timeout, TimeoutError) as error:\n            raise websocket.WebSocketTimeoutException(\'public socket read timed out\') from error\n        except OSError as error:\n            if error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):\n                raise\n        else:\n            if chunk == b\'\':\n                raise websocket.WebSocketConnectionClosedException(\'Connection to remote host was lost.\')\n            if chunk is None:\n                raise websocket.WebSocketTimeoutException(\'public socket temporarily unavailable\')\n            return chunk\n        remaining = None if deadline is None else deadline-time.monotonic()\n        if remaining is not None and remaining <= 0:\n            raise websocket.WebSocketTimeoutException(\'public socket readiness timed out\')\n        with selectors.DefaultSelector() as selector:\n            selector.register(sock, event)\n            if not selector.select(remaining):\n                raise websocket.WebSocketTimeoutException(\'public socket readiness timed out\')\n\n\ndef public_socket_class(websocket):\n    class PublicWebSocket(websocket.WebSocket):\n        def _recv(self, size):\n            try:\n                return recv_checked(self.sock, size, websocket)\n            except websocket.WebSocketConnectionClosedException:\n                sock, self.sock = self.sock, None\n                self.connected = False\n                if sock is not None:\n                    sock.close()\n                raise\n    return PublicWebSocket\n\n\ndef run(stream):\n    import websocket\n    while not stream.stop_event.is_set():\n        sock = ws = None\n        generation = None\n        failure = None\n        try:\n            with stream.lock:\n                symbols = stream.symbols | stream.monitor_symbols\n            if not symbols:\n                stream.stop_event.wait(.5)\n                continue\n            # Reset per-connection timing; retain last disconnect across recovery.\n            with stream.lock:\n                d = diagnostics(stream)\n                d.update(frame_at=None, pong_at=None, pending_ping_at=None, peer_close_code=None, connected_at=None)\n            stage(stream, \'dns\')\n            for info in socket.getaddrinfo(\'ws.okx.com\', 443, socket.AF_INET, socket.SOCK_STREAM):\n                stage(stream, \'tcp\')\n                sock = socket.socket(info[0], info[1], info[2])\n                sock.settimeout(10)\n                try:\n                    sock.connect(info[4])\n                    break\n                except OSError:\n                    sock.close()\n                    sock = None\n            if sock is None:\n                raise OSError(\'WS IPv4 connection failed\')\n            stage(stream, \'tls\')\n            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=\'ws.okx.com\')\n            stage(stream, \'handshake\')\n            ws = websocket.create_connection(\'wss://ws.okx.com/ws/v5/public\', timeout=10, socket=sock, class_=public_socket_class(websocket))\n            ws.settimeout(1)\n            with stream.lock:\n                stream.ws = ws\n                stream.generation += 1\n                generation = stream.generation\n                stream.connected = True\n                stream.data = {}\n                stream.error = None\n                stream.active_pairs = set()\n                stream.last_subscription = -float(\'inf\')\n                stream.last_ping = time.monotonic()\n                diagnostics(stream)[\'connected_at\'] = stream.last_ping\n            last_housekeeping = -float(\'inf\')\n            while not stream.stop_event.is_set():\n                with stream.lock:\n                    if stream.ws is not ws or stream.generation != generation or not stream.connected:\n                        break\n                # Avoid subscription/heartbeat locking on every market frame.\n                # Every frame is still received and fed, with no queue/drops.\n                last_housekeeping = housekeeping(stream, ws, last_housekeeping)\n                stage(stream, \'receive\')\n                try:\n                    message = receive(ws, websocket, stream)\n                except websocket.WebSocketTimeoutException:\n                    continue\n                with stream.lock:\n                    if stream.ws is not ws or stream.generation != generation or not stream.connected:\n                        break\n                if message is not None:\n                    stream.feed(message)\n                stream.retry_delay = 2\n        except Exception as error:\n            failure = error\n        finally:\n            disconnect(stream, ws, generation, failure)\n            if sock:\n                try:\n                    sock.close()\n                except Exception:\n                    pass\n        stream.stop_event.wait(stream.retry_seconds())\n\n\ndef install():\n    import okx_stream\n    cls = okx_stream.MarketStream\n    if getattr(cls, \'_phone_public_version\', None) == VERSION:\n        return\n    cls.update_watch = tracked_watch(cls.update_watch)\n    cls.flush_subscriptions = flush_subscriptions\n    cls.run = run\n    cls._phone_public_version = VERSION\n'
HEALTH_UI = "\n// Read-only verification summary; elapsed run and faults remain explicit.\nconst healthRender123 = render;\nrender = function(d){\n healthRender123(d);\n let el=document.getElementById('phoneHealthSummary');\n if(!el){el=document.createElement('p');el.id='phoneHealthSummary';el.className='muted';document.getElementById('programUpdate').appendChild(el);}\n const h=d.performance?.runtime_health, rows=[];\n if(!h||h.unavailable){el.textContent='연결·진입 진단 수집 중';return;}\n const fresh=Math.max(0,Date.now()/1000-h.observed_at);\n rows.push('연결·진입 진단 '+Math.round(fresh)+'초 전 · 이번 실행 '+Math.floor((h.elapsed_s||0)/60)+'분');\n rows.push('시세 '+(h.public_connected===true?'연결':h.public_connected===false?'끊김':'확인 대기')+' / 계좌 '+(h.account_connected&&h.account_fresh?'최신 자료 수신':'연결·자료 확인 중'));\n const allowed=h.entry_enabled&&!h.user_paused&&!h.entry_cancelled&&!h.recovering&&h.public_connected&&h.account_fresh;\n rows.push('신규 진입 상태: '+(fresh>10?'진단 자료 지연':allowed?'허용 · 조건·주문 검사 필요':'대기·차단'));\n rows.push('이번 실행 시세 끊김 '+(h.disconnect_count??'확인 중')+'회');\n if(h.last_disconnect_at)rows.push('마지막 끊김 '+new Date(h.last_disconnect_at*1000).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})+' KST');\n const causes={read_eof:'소켓 수신 종료(EOF)',socket_already_closed:'이미 닫힌 소켓',websocket_closed:'웹소켓 종료',tcp_reset:'TCP 연결 초기화',write_broken_pipe:'송신 연결 종료',idle_timeout:'수신 무응답',peer_close_frame:'상대 종료 프레임',other_transport_error:'기타 통신 오류'};\n if(h.last_disconnect_cause)rows.push('마지막 종료 유형: '+(causes[h.last_disconnect_cause]||'분류 확인 필요'));\n const e=h.entry||{};\n if(e.observed_at){\n  rows.push('신호 검사 '+Math.round(Math.max(0,Date.now()/1000-e.observed_at))+'초 전 · '+e.duration_s+'초 소요 · 준비 '+e.pending+'개 · '+e.result);\n  const reasons=Object.entries(e.reasons||{}).map(([k,v])=>k+' '+v+'건');\n  if(reasons.length)rows.push('이번 검사 대기 이유: '+reasons.join(' / '));\n  for(const w of e.waiting||[])rows.push(w.symbol+' · '+w.channels.join(', ')+' 대기 · 검사 당시 유효시간 '+w.remaining_s+'초 남음');\n }\n rows.push('연결 허용은 체결 확인이 아닙니다. 끊김 횟수는 재시작 시 초기화됩니다.');\n el.style.whiteSpace='pre-line';el.textContent=rows.join('\\n');\n};\n"
OLD_HEALTH_UI = "\n// Read-only verification summary; elapsed run and faults remain explicit.\nconst healthRender123 = render;\nrender = function(d){\n healthRender123(d);\n let el=document.getElementById('phoneHealthSummary');\n if(!el){el=document.createElement('p');el.id='phoneHealthSummary';el.className='muted';document.getElementById('programUpdate').appendChild(el);}\n const h=d.performance?.runtime_health, rows=[];\n if(!h||h.unavailable){el.textContent='연결·진입 진단 수집 중';return;}\n const fresh=Math.max(0,Date.now()/1000-h.observed_at);\n rows.push('연결·진입 진단 '+Math.round(fresh)+'초 전 · 이번 실행 '+Math.floor((h.elapsed_s||0)/60)+'분');\n rows.push('시세 '+(h.public_connected===true?'연결':h.public_connected===false?'끊김':'확인 대기')+' / 계좌 '+(h.account_connected&&h.account_fresh?'최신 자료 수신':'연결·자료 확인 중'));\n const allowed=h.entry_enabled&&!h.user_paused&&!h.entry_cancelled&&!h.recovering&&h.public_connected&&h.account_fresh;\n rows.push('신규 진입 상태: '+(fresh>10?'진단 자료 지연':allowed?'허용 · 조건·주문 검사 필요':'대기·차단'));\n rows.push('이번 실행 시세 끊김 '+(h.disconnect_count??'확인 중')+'회');\n if(h.last_disconnect_at)rows.push('마지막 끊김 '+new Date(h.last_disconnect_at*1000).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})+' KST');\n const e=h.entry||{};\n if(e.observed_at){\n  rows.push('신호 검사 '+Math.round(Math.max(0,Date.now()/1000-e.observed_at))+'초 전 · '+e.duration_s+'초 소요 · 준비 '+e.pending+'개 · '+e.result);\n  const reasons=Object.entries(e.reasons||{}).map(([k,v])=>k+' '+v+'건');\n  if(reasons.length)rows.push('이번 검사 대기 이유: '+reasons.join(' / '));\n  for(const w of e.waiting||[])rows.push(w.symbol+' · '+w.channels.join(', ')+' 대기 · 검사 당시 유효시간 '+w.remaining_s+'초 남음');\n }\n rows.push('연결 허용은 체결 확인이 아닙니다. 끊김 횟수는 재시작 시 초기화됩니다.');\n el.style.whiteSpace='pre-line';el.textContent=rows.join('\\n');\n};\n"

def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(text, before, after, file):
    if not before or text.count(before) != 1:
        raise ValueError(file + ': 수정 대상이 정확히 일치하지 않습니다. 변경 안 함')
    return text.replace(before, after, 1)


def safe_path(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ValueError('운용 루트 폴더가 없거나 링크입니다.')
    return path.resolve(strict=True)


def read_pins(root):
    old = root/HOST_OLD
    if old.is_symlink() or not old.is_dir():
        raise ValueError('현재 1.2.3 host-v21 폴더를 확인하지 못했습니다.')
    originals = {}
    for name, checksum in PINNED.items():
        file = old/name
        if file.is_symlink() or not file.is_file():
            raise ValueError(name + ': 필수 원본 파일이 없습니다.')
        data = file.read_bytes()
        actual = digest(data)
        if actual != checksum:
            raise ValueError(name + ': 승인된 1.2.3 원본과 다릅니다. 자동 변경하지 않았습니다.')
        originals[name] = data
    for file in old.rglob('*'):
        rel = file.relative_to(old)
        if file.is_symlink():
            raise ValueError('이전 실행기 안에 파일 링크가 있어 중단합니다.')
        if file.is_file() and '__pycache__' not in rel.parts and rel.as_posix() not in PINNED:
            raise ValueError('1.2.3 실행기에 예상하지 않은 파일이 있어 중단합니다: ' + str(rel))
    return originals


def candidate(originals):
    files = dict(originals)
    files['phone_public_ws.py'] = TRANSPORT_MODULE.encode('utf-8')
    ui=originals['phone_update_ui.js'].decode()
    files['phone_update_ui.js']=replace_once(ui,OLD_HEALTH_UI,HEALTH_UI,'phone_update_ui.js').encode()
    trace=originals['phone_connection_trace.py'].decode()
    files['phone_connection_trace.py']=replace_once(trace,"'phone-public-ws-3',","'phone-public-ws-4', 'phone-public-ws-3',",'phone_connection_trace.py').encode()
    service = originals['phone_service.py'].decode()
    service = replace_once(service,"VERSION = 'phone-service-21'","VERSION = 'phone-service-22'",'phone_service.py')
    service = replace_once(service,"MARKER = '# OKX phone service v21 managed boot hook'","MARKER = '# OKX phone service v22 managed boot hook'",'phone_service.py')
    service = replace_once(service,'LEGACY_MARKERS = (',"LEGACY_MARKERS = ('# OKX phone service v21 managed boot hook', ",'phone_service.py')
    files['phone_service.py'] = service.encode()
    mobile = originals['phone_mobile.py'].decode()
    if mobile.count('1.2.3') != 4: raise ValueError('mobile version mismatch')
    files['phone_mobile.py'] = mobile.replace('1.2.3','1.2.4').encode()
    update = originals['phone_update.py'].decode()
    update = replace_once(update,'CURRENT = 21','CURRENT = 22','phone_update.py')
    update = replace_once(update,"DISPLAY_VERSION = '1.2.3'","DISPLAY_VERSION = '1.2.4'",'phone_update.py')
    files['phone_update.py'] = update.encode()
    up = originals['phone_button_upgrade.py'].decode().replace('1.2.3','1.2.4')
    up = replace_once(up,"if matches != ['host-v20']:","if matches != ['host-v21']:",'phone_button_upgrade.py')
    files['phone_button_upgrade.py'] = up.encode()
    oldpins=json.loads(originals['phone_button_old_sources.json'])
    if HOST_OLD in oldpins: raise ValueError('duplicate predecessor')
    oldpins[HOST_OLD]=PINNED
    files['phone_button_old_sources.json']=(json.dumps(oldpins,ensure_ascii=False,indent=2)+'\n').encode()
    for name,data in files.items():
        if name.endswith('.py'): compile(data,name,'exec')
    return files


def stage(root, files):
    dest = root/HOST_NEW
    if dest.is_symlink():
        raise ValueError('host-v22 경로 링크 오류')
    if dest.exists():
        if not dest.is_dir():
            raise ValueError('host-v22은 폴더가 아닙니다.')
        seen = {}
        for file in dest.rglob('*'):
            rel = file.relative_to(dest)
            if file.is_symlink():
                raise ValueError('host-v22 내 파일 링크 오류')
            if file.is_file() and '__pycache__' not in rel.parts:
                seen[rel.as_posix()] = file.read_bytes()
        if seen != files:
            raise ValueError('다른 host-v22이 존재합니다. 덮어쓰지 않았습니다.')
        print('이미 검증된 1.2.4 파일이 준비되어 있습니다.')
        return dest
    tmp = Path(tempfile.mkdtemp(prefix='.host-v22-stage-', dir=root))
    try:
        for name, data in files.items():
            target = tmp/name
            with target.open('xb') as fp:
                fp.write(data)
                os.fchmod(fp.fileno(), 0o600)
        for name, data in files.items():
            if (tmp/name).read_bytes() != data:
                raise ValueError('설치 파일 저장 검증 실패')
        tmp.rename(dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    print('해시 확인된 1.2.4 파일 준비:', dest)
    return dest


def main():
    parser = argparse.ArgumentParser(description='OKX Fold3 1.2.4 연결 유지 방식 복원 후보')
    parser.add_argument('--root', default=str(Path.home()/'okx-phone'))
    parser.add_argument('--stage-only', action='store_true', help='검증 및 파일 준비만 수행; 실행기 인계 없음')
    args = parser.parse_args()
    root = safe_path(args.root)
    dest = stage(root, candidate(read_pins(root)))
    if args.stage_only:
        return
    print('기존 보유/미체결/보호주문을 확인하고 안전 인계를 요청합니다.')
    print('보호 상태가 불확실하면 기존 실행기를 유지하고 설치를 보류합니다.')
    proc = subprocess.run([sys.executable, '-B', str(dest/'phone_button_upgrade.py'), '--root', str(root)],
                          cwd=str(dest), check=False)
    if proc.returncode:
        raise SystemExit('업데이트 보류: 기존 앱이 보유분 보호 중일 수 있습니다. 강제 종료하지 마세요.')
    print('설치 완료: 모바일 버전 1.2.4, 기존 운용 상태를 확인하세요.')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, UnicodeError) as exc:
        print('설치 보류:', str(exc))
        raise SystemExit(1)
