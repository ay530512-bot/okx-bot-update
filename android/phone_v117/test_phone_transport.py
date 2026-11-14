"""Offline transport/state tests. No exchange connection or credentials used."""
import importlib.util
import json
from pathlib import Path
import threading
import time
from types import MethodType
import unittest
from unittest.mock import patch, Mock

import websocket
import phone_public_ws as fix

import os
SOURCE = Path(os.environ['OKX_TEST_CORE'])/'okx_stream.py'
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
    s.update_watch=MethodType(fix.tracked_watch(original.MarketStream.update_watch),s)
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
            fix.flush_subscriptions(s)  # removals first, like original
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

    def test_settled_watch_skips_pair_builds_across_many_received_frames(self):
        s=stream()
        with patch.object(s,'pairs',wraps=s.pairs) as pairs:
            with patch('time.monotonic',return_value=100):fix.flush_subscriptions(s)
            with patch('time.monotonic',return_value=110):fix.flush_subscriptions(s)
            builds=pairs.call_count
            with patch('time.monotonic',return_value=120):
                for i in range(2000):
                    fix.flush_subscriptions(s)
                    s.feed(json.dumps({'arg':{'channel':'tickers','instId':'TEST000-USDT-SWAP'},'data':[{'ts':str(1000+i),'last':'1'}]}))
            self.assertEqual(pairs.call_count,builds)
            self.assertEqual(s.data[('TEST000-USDT-SWAP','tickers')][0]['ts'],'2999')
            revision=getattr(s,'_phone_watch_revision',0)
            s.watch(s.symbols)
            self.assertEqual(getattr(s,'_phone_watch_revision',0),revision)
            builds=pairs.call_count
            with patch('time.monotonic',return_value=120):fix.flush_subscriptions(s)
            self.assertEqual(pairs.call_count,builds)
            with patch('time.monotonic',return_value=120):s.watch({'NEW-USDT-SWAP'})
            self.assertGreater(s._phone_watch_revision,revision)
            with patch('time.monotonic',return_value=122):fix.flush_subscriptions(s)
            self.assertEqual(json.loads(s.ws.sent[-1])['op'],'unsubscribe')
            with patch('time.monotonic',return_value=132):fix.flush_subscriptions(s)
            self.assertEqual(s.active_pairs,s.pairs())

    def test_monitor_change_reconnect_and_chunk_progress_invalidate_settled_state(self):
        s=stream()
        with patch('time.monotonic',return_value=100):fix.flush_subscriptions(s)
        with patch('time.monotonic',return_value=110):fix.flush_subscriptions(s)
        s.monitor({'NEW-USDT-SWAP'})
        with patch('time.monotonic',return_value=120):fix.flush_subscriptions(s)
        self.assertIn(('NEW-USDT-SWAP','tickers'),s.active_pairs)
        with patch('time.monotonic',return_value=130):fix.flush_subscriptions(s)
        s.generation+=1;s.active_pairs=set();s.last_subscription=-float('inf')
        with patch('time.monotonic',return_value=140):fix.flush_subscriptions(s)
        self.assertEqual(s.active_pairs,s.pairs())
        s.monitor({f'LARGE{i}-USDT-SWAP' for i in range(4000)})
        for i in range(20):
            with patch('time.monotonic',return_value=150+i*10):fix.flush_subscriptions(s)
        self.assertEqual(s.active_pairs,s.pairs())


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

    def test_missing_pong_times_out_at_deadline_and_invalidates_quotes(self):
        s = stream();s.last_ping=100
        s.data[('X','tickers')]=({'ts':'1000','last':'1'},100,1)
        with patch('time.monotonic',return_value=119):fix.ping_if_due(s,s.ws)
        self.assertEqual(s.ws.sent,[])
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,s.ws)
        with patch('time.monotonic',return_value=139.999):fix.ping_if_due(s,s.ws)
        with patch('time.monotonic',return_value=140):
            with self.assertRaises(fix.PublicHeartbeatTimeout):fix.ping_if_due(s,s.ws)
            fix.disconnect(s,s.ws,1,fix.PublicHeartbeatTimeout())
        self.assertFalse(s.connected);self.assertEqual(s.data,{})
        self.assertIsNone(s.read('X','tickers'))
        self.assertEqual(s._public_transport['last_disconnect']['error'],'PublicHeartbeatTimeout')
        self.assertEqual(s.retry_seconds(),2)
        self.assertEqual(s.retry_seconds(),4)

    def test_timely_pong_keeps_transport_live(self):
        s=stream();s.last_ping=100
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,s.ws)
        ws=self.framed([websocket.ABNF.create_frame('pong',websocket.ABNF.OPCODE_TEXT)])
        with patch('time.monotonic',return_value=139):fix.receive(ws,websocket,s)
        with patch('time.monotonic',return_value=140):fix.ping_if_due(s,s.ws)
        self.assertEqual(s.ws.sent,['ping','ping'])
        self.assertTrue(s.connected)
        self.assertEqual(s._public_transport['pending_ping_at'],140)

    def test_obsolete_ping_send_does_not_change_new_generation(self):
        s=stream();s.last_ping=0
        def send(_):
            s.generation+=1;s.last_ping=999
        s.ws.send=send
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,s.ws)
        self.assertEqual(s.last_ping,999)
        self.assertEqual(s._public_transport['text_pings'],0)
        self.assertIsNone(s._public_transport['pending_ping_at'])

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

    def test_silent_socket_reconnects_with_backoff_and_no_old_quote_reuse(self):
        s=stream();s.connected=False;s.ws=None;s.generation=0
        now=[100.0];waits=[];raw=Mock();ws1=Mock();ws2=Mock()
        def silence(**kw):
            s.data[('OLD','tickers')]=({'ts':'1000'},now[0],s.generation)
            now[0]+=20
            raise websocket.WebSocketTimeoutException()
        ws1.recv_data_frame.side_effect=silence
        def restored(**kw):
            self.assertNotIn(('OLD','tickers'),s.data)
            s.stop_event.set()
            return (websocket.ABNF.OPCODE_TEXT,websocket.ABNF.create_frame('pong',1))
        ws2.recv_data_frame.side_effect=restored
        s.stop_event.wait=lambda seconds: waits.append(seconds) or s.stop_event.is_set()
        with patch.object(fix.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(fix.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]), \
             patch.object(fix.socket,'socket',return_value=raw), \
             patch.object(fix.ssl,'create_default_context') as ctx, \
             patch.object(websocket,'create_connection',side_effect=[ws1,ws2]):
            ctx.return_value.wrap_socket.return_value=raw
            fix.run(s)
        self.assertEqual(s.generation,2);self.assertEqual(waits[0],2)
        self.assertEqual(s._public_transport['last_disconnect']['error'],'PublicHeartbeatTimeout')
        self.assertEqual(s._public_transport['disconnect_count'],1)
        self.assertFalse(s.connected);self.assertEqual(s.data,{})
        for ws in (ws1,ws2):
            self.assertEqual(len(json.loads(ws.send.call_args_list[0].args[0])['args']),292)

    def test_stopped_run_does_not_open_connection(self):
        s=stream();s.stop_event.set()
        with patch.object(fix.socket,'getaddrinfo') as lookup:fix.run(s)
        lookup.assert_not_called()

    def test_install_changes_only_three_public_methods_and_is_idempotent(self):
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


if __name__=='__main__':
    unittest.main()
