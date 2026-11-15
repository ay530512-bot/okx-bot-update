"""Offline transport/state tests. No exchange connection or credentials used."""
import importlib.util
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch, Mock

import websocket
import phone_public_ws as fix

SOURCE = Path(__file__).parents[1]/'phone_button_v1/original_stream_reference.py'
spec = importlib.util.spec_from_file_location('frozen_stream', SOURCE)
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)


class Socket:
    def __init__(self):
        self.sent = []
    def send(self, text):
        self.sent.append(text)
    def close(self):
        pass


def stream():
    s = original.MarketStream()
    s.ws = Socket()
    s.connected = True
    s.generation = 1
    s.monitor_symbols = {f'TEST{i:03}-USDT-SWAP' for i in range(289)}
    s.symbols = {'TEST000-USDT-SWAP'}
    return s


class Subscriptions(unittest.TestCase):
    def test_292_recovery_old_three_requests_new_one_same_pairs(self):
        old, new = stream(), stream()
        with patch('time.monotonic', return_value=100):
            old.flush_subscriptions()
            fix.flush_subscriptions(new)
        self.assertEqual(len(old.active_pairs), 100)
        self.assertEqual(len(new.active_pairs), 292)
        with patch('time.monotonic', return_value=110):
            old.flush_subscriptions()
            fix.flush_subscriptions(new)
        with patch('time.monotonic', return_value=120):
            old.flush_subscriptions()
        self.assertEqual(old.active_pairs, new.active_pairs)
        self.assertEqual(len(old.ws.sent), 3)
        self.assertEqual(len(new.ws.sent), 1)
        self.assertLess(len(new.ws.sent[0].encode()), 60*1024)

    def test_large_universe_is_split_by_bytes_and_never_loses_pairs(self):
        pairs = {(f'TEST{i:05}-USDT-SWAP', 'tickers') for i in range(4000)}
        remaining = set(pairs)
        while remaining:
            items, body = fix.payload('subscribe', remaining)
            self.assertLessEqual(len(body.encode()), fix.MAX_PAYLOAD_BYTES)
            self.assertEqual(len(json.loads(body)['args']), len(items))
            self.assertTrue(items)
            remaining.difference_update(items)

    def test_blocked_send_does_not_lock_market_read_or_watch(self):
        s = stream()
        entered, release = threading.Event(), threading.Event()
        s.data[('X','tickers')] = ({'ts':'1000'},time.monotonic(),s.generation)
        def send(_):
            entered.set()
            release.wait(2)
        s.ws.send = send
        worker = threading.Thread(target=fix.flush_subscriptions,args=(s,))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(s.lock.acquire(timeout=.1))
            s.lock.release()
            self.assertIsNotNone(s.read('X','tickers'))
            s.watch(['NEW-USDT-SWAP'])
        finally:
            release.set()
            worker.join(2)
        with patch('time.monotonic',return_value=time.monotonic()+20):
            fix.flush_subscriptions(s)  # new subscriptions first; removals reconcile next
        with patch('time.monotonic',return_value=time.monotonic()+40):
            fix.flush_subscriptions(s)
        self.assertEqual(s.active_pairs,s.pairs())

    def test_send_on_obsolete_generation_never_commits(self):
        s = stream()
        def send(_):
            s.generation += 1
            s.active_pairs = set()
        s.ws.send = send
        fix.flush_subscriptions(s)
        self.assertFalse(s.active_pairs)
        self.assertEqual(s.last_subscription, -float('inf'))

    def test_send_failure_never_marks_pairs_active(self):
        s = stream()
        s.ws.send = Mock(side_effect=BrokenPipeError())
        with self.assertRaises(BrokenPipeError):
            fix.flush_subscriptions(s)
        self.assertFalse(s.active_pairs)

    def test_ten_second_operation_pacing_and_two_second_debounce(self):
        s = stream()
        s.watch_changed = 99
        with patch('time.monotonic',return_value=100):
            fix.flush_subscriptions(s)
        self.assertFalse(s.ws.sent)
        with patch('time.monotonic',return_value=101):
            fix.flush_subscriptions(s)
        s.monitor_symbols.add('NEW-USDT-SWAP')
        with patch('time.monotonic',return_value=110):
            fix.flush_subscriptions(s)
        self.assertEqual(len(s.ws.sent),1)
        with patch('time.monotonic',return_value=111):
            fix.flush_subscriptions(s)
        self.assertEqual(len(s.ws.sent),2)


class Transport(unittest.TestCase):
    def framed(self, frames):
        ws = websocket.WebSocket()
        ws.recv_frame = Mock(side_effect=frames)
        ws.send_close = Mock()
        ws.pong = Mock()
        return ws

    def test_fragmented_data_protocol_ping_and_text_pong(self):
        ab = websocket.ABNF
        frames = [ab.create_frame('pi',ab.OPCODE_TEXT,0),
                  ab.create_frame(b'ng',ab.OPCODE_CONT,1),
                  ab.create_frame('check',ab.OPCODE_PING),
                  ab.create_frame('pong',ab.OPCODE_TEXT)]
        ws = self.framed(frames)
        s = stream()
        self.assertEqual(fix.receive(ws,websocket,s),'ping')
        self.assertIsNone(fix.receive(ws,websocket,s))
        ws.pong.assert_called_once()
        self.assertIsNone(fix.receive(ws,websocket,s))
        self.assertEqual(s._public_transport['text_pongs'],1)

    def test_peer_close_code_retained_without_raw_reason(self):
        ab = websocket.ABNF
        ws = self.framed([ab.create_frame((1001).to_bytes(2,'big')+b'PRIVATE_REASON',ab.OPCODE_CLOSE)])
        s = stream()
        with self.assertRaises(fix.PublicPeerClosed):
            fix.receive(ws,websocket,s)
        fix.disconnect(s,s.ws,s.generation,fix.PublicPeerClosed())
        self.assertEqual(s._public_transport['last_disconnect']['close_code'],1001)
        self.assertNotIn('PRIVATE_REASON',json.dumps(s._public_transport))

    def test_blocked_close_is_fail_closed_but_does_not_lock_readers(self):
        s = stream()
        old = s.ws
        entered, release = threading.Event(),threading.Event()
        def close():
            entered.set();release.wait(2)
        old.close = close
        worker = threading.Thread(target=fix.disconnect,args=(s,old,1,BrokenPipeError()))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(s.lock.acquire(timeout=.1));s.lock.release()
            self.assertFalse(s.connected)
            self.assertIsNone(s.read('TEST000-USDT-SWAP','tickers'))
            self.assertEqual(s.error,'BrokenPipeError')
        finally:
            release.set();worker.join(2)

    def test_ping_schedule_unchanged_and_missing_pong_measured(self):
        s = stream();s.last_ping=100
        with patch('time.monotonic',return_value=119):fix.ping_if_due(s,s.ws)
        self.assertEqual(s.ws.sent,[])
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,s.ws)
        with patch('time.monotonic',return_value=140):
            with self.assertRaises(fix.PublicHeartbeatTimeout):fix.ping_if_due(s,s.ws)
        self.assertEqual(s.ws.sent,['ping'])
        self.assertEqual(s._public_transport['pending_ping_at'],120)
        self.assertTrue(s.connected)

    def test_original_freshness_and_generation_guards_still_apply(self):
        s = stream()
        now=time.monotonic()
        s.data[('X','tickers')]=({'ts':'1000','last':'1'},now,1)
        self.assertIsNotNone(s.read('X','tickers',now_ms=1001))
        self.assertIsNone(s.read('X','tickers',now_ms=20000))
        s.generation=2
        self.assertIsNone(s.read('X','tickers'))
        s.generation=1;s.connected=False
        self.assertIsNone(s.read('X','tickers'))

    def test_run_reconnects_rebuilds_subscriptions_then_exits_cleanly(self):
        s=stream();s.connected=False;s.ws=None;s.generation=0
        raw=Mock()
        ws1,ws2=Mock(),Mock()
        frames=[websocket.WebSocketConnectionClosedException(),
            (websocket.ABNF.OPCODE_TEXT,websocket.ABNF.create_frame('pong',1))]
        ws1.recv_data_frame.side_effect=frames[:1]
        def second_frame(**kw):
            s.stop_event.set()
            return frames[1]
        ws2.recv_data_frame.side_effect=second_frame
        original_wait=s.stop_event.wait
        s.stop_event.wait=lambda seconds: original_wait(0)
        with patch.object(fix.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]), \
             patch.object(fix.socket,'socket',return_value=raw), \
             patch.object(fix.ssl,'create_default_context') as ctx, \
             patch.object(websocket,'create_connection',side_effect=[ws1,ws2]):
            ctx.return_value.wrap_socket.return_value=raw
            fix.run(s)
            ctx.return_value.wrap_socket.assert_called_with(raw,server_hostname='ws.okx.com')
        self.assertEqual(s.generation,2)
        for ws in (ws1,ws2):
            body=json.loads(ws.send.call_args_list[0].args[0])
            self.assertEqual(len(body['args']),292)
        self.assertFalse(s.connected)
        self.assertEqual(s._public_transport['disconnect_count'],1)
        self.assertEqual(s._public_transport['last_disconnect']['error'],'WebSocketConnectionClosedException')

    def test_install_changes_only_two_public_methods_and_is_idempotent(self):
        import sys
        spec2=importlib.util.spec_from_file_location('test_install_stream',SOURCE)
        module=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(module)
        old=dict(module.MarketStream.__dict__)
        account=dict(module.AccountStream.__dict__)
        with patch.dict(sys.modules,{'okx_stream':module}):
            fix.install();fix.install()
        changed={k for k,v in old.items() if module.MarketStream.__dict__[k] is not v}
        self.assertEqual(changed,{'flush_subscriptions','run','update_watch'})
        self.assertEqual(account,dict(module.AccountStream.__dict__))


    def test_new_execution_channels_precede_old_removal(self):
        s=stream();s.active_pairs=s.pairs();s.symbols={'NEW-USDT-SWAP'}
        with patch('time.monotonic',return_value=100):fix.flush_subscriptions(s)
        body=json.loads(s.ws.sent[0]);self.assertEqual(body['op'],'subscribe')
        self.assertTrue(any(x['instId']=='NEW-USDT-SWAP' and x['channel']=='books5' for x in body['args']))
        with patch('time.monotonic',return_value=110):fix.flush_subscriptions(s)
        self.assertEqual(json.loads(s.ws.sent[1])['op'],'unsubscribe')
        self.assertEqual(s.active_pairs,s.pairs())

    def test_busy_receive_does_not_repeat_housekeeping_per_frame(self):
        s=stream();last=-float('inf')
        with patch.object(fix,'flush_subscriptions') as subscriptions,patch.object(fix,'ping_if_due') as heartbeat:
            for i in range(10000):
                with patch('time.monotonic',return_value=100+i/10000):
                    last=fix.housekeeping(s,s.ws,last)
            self.assertEqual(subscriptions.call_count,4);self.assertEqual(heartbeat.call_count,4)

    def test_active_frames_cancel_pending_idle_timeout(self):
        s=stream();s.last_ping=100;d=fix.diagnostics(s)
        d.update(pending_ping_at=100,frame_at=119)
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,s.ws)
        self.assertIsNone(d['pending_ping_at']);self.assertFalse(s.ws.sent)

    def test_no_raw_disconnect_message_leaks(self):
        s=stream()
        fix.disconnect(s,s.ws,1,websocket.WebSocketConnectionClosedException('secret remote message'))
        self.assertEqual(s._public_transport['last_disconnect']['cause'],'websocket_closed')
        self.assertNotIn('secret',json.dumps(s._public_transport))
        self.assertEqual(fix.failure_kind(websocket.WebSocketConnectionClosedException('Connection to remote host was lost.')),'read_eof')


class ReadinessVsEOF(unittest.TestCase):
    def test_old_library_path_reproduces_false_disconnect(self):
        from websocket._socket import recv
        sock=Mock();sock.gettimeout.return_value=1
        sock.recv.side_effect=fix.ssl.SSLWantReadError()
        selector=Mock();selector.select.return_value=[]
        with patch('websocket._socket.selectors.DefaultSelector',return_value=selector):
            with self.assertRaises(websocket.WebSocketConnectionClosedException):recv(sock,1)

    def test_readiness_timeout_keeps_socket_open(self):
        sock=Mock();sock.gettimeout.return_value=1
        sock.recv.side_effect=fix.ssl.SSLWantReadError()
        selector=Mock();selector.select.return_value=[]
        ctx=Mock();ctx.__enter__=Mock(return_value=selector);ctx.__exit__=Mock(return_value=False)
        ws=fix.public_socket_class(websocket)();ws.sock=sock;ws.connected=True
        with patch.object(fix.selectors,'DefaultSelector',return_value=ctx):
            with self.assertRaises(websocket.WebSocketTimeoutException):ws._recv(1)
        self.assertIs(ws.sock,sock);self.assertTrue(ws.connected);sock.close.assert_not_called()

    def test_real_eof_invalidates_socket(self):
        sock=Mock();sock.gettimeout.return_value=1;sock.recv.return_value=b''
        ws=fix.public_socket_class(websocket)();ws.sock=sock;ws.connected=True
        with self.assertRaises(websocket.WebSocketConnectionClosedException):ws._recv(1)
        self.assertIsNone(ws.sock);self.assertFalse(ws.connected);sock.close.assert_called_once()

    def test_partial_frame_survives_transient_timeout(self):
        sock=Mock();sock.gettimeout.return_value=1
        # Two-byte WS header then split payload, with transient TLS wait.
        sock.recv.side_effect=[b'\x81\x04',b'po',fix.ssl.SSLWantReadError(),b'ng']
        selector=Mock();selector.select.return_value=[]
        ctx=Mock();ctx.__enter__=Mock(return_value=selector);ctx.__exit__=Mock(return_value=False)
        ws=fix.public_socket_class(websocket)();ws.sock=sock;ws.connected=True
        with patch.object(fix.selectors,'DefaultSelector',return_value=ctx):
            with self.assertRaises(websocket.WebSocketTimeoutException):ws.recv_data_frame(control_frame=True)
        opcode,frame=ws.recv_data_frame(control_frame=True)
        self.assertEqual(opcode,websocket.ABNF.OPCODE_TEXT);self.assertEqual(frame.data,b'pong')
        self.assertTrue(ws.connected)

    def test_ssl_ready_then_data_and_zero_timeout(self):
        sock=Mock();sock.gettimeout.return_value=1
        sock.recv.side_effect=[fix.ssl.SSLWantReadError(),b'X']
        selector=Mock();selector.select.return_value=[(None,None)]
        ctx=Mock();ctx.__enter__=Mock(return_value=selector);ctx.__exit__=Mock(return_value=False)
        with patch.object(fix.selectors,'DefaultSelector',return_value=ctx):
            self.assertEqual(fix.recv_checked(sock,1,websocket),b'X')
        sock.gettimeout.return_value=0;sock.recv.side_effect=BlockingIOError()
        with self.assertRaises(websocket.WebSocketTimeoutException):fix.recv_checked(sock,1,websocket)


if __name__=='__main__':
    unittest.main()
