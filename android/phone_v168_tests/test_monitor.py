"""Replay transport and monitor-only failures; no external sockets or orders."""
import copy
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

D=Path(__file__).resolve().parent;HOST=D.parent/'phone_v168';CORE=D.parents[2]/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
import websocket
import phone_public_ws as fix
import phone_public_lanes as lanes
from phone_connection_trace import Trace,snapshot,sanitized
from phone_diagnostic_export import safe
from okx_stream import MarketStream


class BytesSocket:
    def __init__(self,parts):self.parts=list(parts);self.calls=[];self.closed=False
    def gettimeout(self):return 1
    def recv(self,n):
        self.calls.append(n)
        if not self.parts:return b''
        value=self.parts.pop(0)
        if isinstance(value,Exception):raise value
        if len(value)>n:self.parts.insert(0,value[n:])
        return value[:n]
    def close(self):self.closed=True


def frame(data,opcode=1,fin=1):
    return websocket.ABNF(fin=fin,opcode=opcode,mask_value=0,data=data).format()


def socket(parts,ahead=16384):
    sock=BytesSocket(parts);ws=fix.public_socket_class(websocket,ahead)(skip_utf8_validation=True)
    ws.sock=sock;ws.connected=True;ws.pong=Mock();ws.send_close=Mock()
    return ws,sock


class BufferedTests(unittest.TestCase):
    def test_exact_frames_across_small_extended_and_large_lengths(self):
        messages=[b'x',b'y'*125,b'z'*126,b'a'*65535,b'b'*65536,'한글'.encode()*100]
        wire=b''.join(frame(m) for m in messages)
        for chunk in (1,3,500,16384):
            ws,sock=socket([wire[i:i+chunk] for i in range(0,len(wire),chunk)])
            out=[ws.recv_data_frame(control_frame=True)[1].data for _ in messages]
            self.assertEqual(out,messages);self.assertLessEqual(len(ws._phone_rx_bytes),16384)
            self.assertTrue(all(n<=16384 for n in sock.calls))
    def test_many_frames_use_one_tls_read_and_keep_order(self):
        values=[str(i).encode() for i in range(100)]
        ws,sock=socket([b''.join(frame(x) for x in values)])
        self.assertEqual([ws.recv_data_frame()[1].data for _ in values],values)
        self.assertEqual(len(sock.calls),1)
    def test_available_one_byte_returns_without_waiting_to_fill_buffer(self):
        ws,sock=socket([b'A',TimeoutError()])
        self.assertEqual(ws._recv(99),b'A');self.assertEqual(len(sock.calls),1)
        with self.assertRaises(websocket.WebSocketTimeoutException):ws._recv(1)
        self.assertTrue(ws.connected);self.assertFalse(sock.closed)
    def test_partial_frame_preserved_through_temporary_tls_timeout(self):
        ws,sock=socket([b'\x81\x04po',TimeoutError(),b'ng'])
        with self.assertRaises(websocket.WebSocketTimeoutException):ws.recv_data_frame()
        self.assertEqual(ws.recv_data_frame()[1].data,b'pong');self.assertTrue(ws.connected)
    def test_actual_eof_is_detected_after_all_received_bytes_are_consumed(self):
        ws,sock=socket([frame(b'one')+frame(b'two')])
        self.assertEqual(ws.recv_data_frame()[1].data,b'one')
        self.assertEqual(ws.recv_data_frame()[1].data,b'two')
        with self.assertRaises(websocket.WebSocketConnectionClosedException):ws.recv_data_frame()
        self.assertFalse(ws.connected);self.assertIsNone(ws.sock);self.assertTrue(sock.closed)
        self.assertEqual(ws._phone_rx_bytes,b'')
    def test_socket_replacement_and_external_close_never_reuse_buffered_bytes(self):
        ws,sock=socket([b'OLD']);self.assertEqual(ws._recv(1),b'O')
        ws.sock=BytesSocket([b'NEW']);self.assertEqual(ws._recv(3),b'NEW')
        ws.sock=None
        with self.assertRaises(websocket.WebSocketConnectionClosedException):ws._recv(1)
    def test_fragmentation_protocol_ping_and_close_are_not_skipped(self):
        wire=frame(b'hel',fin=0)+frame(b'lo',opcode=0)+frame(b'ping',opcode=9)+frame((1001).to_bytes(2,'big'),opcode=8)
        ws,_=socket([wire]);s=MarketStream()
        self.assertEqual(fix.receive(ws,websocket,s),'hello')
        self.assertIsNone(fix.receive(ws,websocket,s));ws.pong.assert_called_once_with(b'ping')
        with self.assertRaises(fix.PublicPeerClosed):fix.receive(ws,websocket,s)
        self.assertEqual(s._public_transport['peer_close_code'],1001)
    def test_invalid_utf8_and_reserved_frame_flags_still_fail(self):
        ws,_=socket([frame(b'\xff')])
        with self.assertRaises(UnicodeDecodeError):fix.receive(ws,websocket,MarketStream())
        ws,_=socket([b'\xc1\x01x'])
        with self.assertRaises(websocket.WebSocketProtocolException):ws.recv_data_frame()
    def test_invalid_buffer_size_is_rejected(self):
        for n in (-1,16385,1.5,True):
            with self.assertRaises(ValueError):fix.public_socket_class(websocket,n)
    def test_execution_default_keeps_original_exact_read_size(self):
        ws,sock=socket([b'A'],ahead=0);self.assertEqual(ws._recv(1),b'A');self.assertEqual(sock.calls,[1])
    def test_runtime_enables_buffer_for_monitor_only(self):
        for monitor,want in ((True,16384),(False,0)):
            s=MarketStream();s._phone_monitor_only=monitor;s.monitor_symbols={'X'};s.symbols={'X'}
            raw=Mock();ws=Mock()
            def receive(*a,**k):s.stop_event.set();return (1,NS(data=b'pong'))
            ws.recv_data_frame.side_effect=receive
            with patch.object(fix.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]), \
                 patch.object(fix.socket,'socket',return_value=raw),patch.object(fix.ssl,'create_default_context') as ctx, \
                 patch.object(websocket,'create_connection',return_value=ws),patch.object(fix,'public_socket_class',wraps=fix.public_socket_class) as factory:
                ctx.return_value.wrap_socket.return_value=raw;fix.run(s)
                factory.assert_called_once_with(websocket,want)


class TraceTests(unittest.TestCase):
    def setUp(self):
        fix.install();lanes.install();self.s=MarketStream();self.m=self.s._phone_monitor_stream
        for s in (self.s,self.m):s.connected=True;s.generation=1;s.error=None;s.ws=Mock()
        self.e=NS(stream=self.s,account_stream=NS(received=99,connected=True,generation=1,error=None,equity='100'),
            connection_key=(1,1),recovering=False,good_snapshots=2,enabled=True,user_paused=False,entry_cancel=threading.Event(),
            api=NS(server_ms=100000,anchor=100,synced=100,now_ms=Mock(side_effect=AssertionError('observer cannot fetch server time'))),
            events=queue.Queue(),stop_event=threading.Event())
        self.tmp=tempfile.TemporaryDirectory();self.now=100;self.t=Trace(self.e,self.tmp.name,mono=lambda:self.now)
    def tearDown(self):self.tmp.cleanup()
    def changes(self):return [e for e in self.t.events if e['kind']=='periodic_change']
    def test_monitor_only_eof_and_recovery_are_recorded_without_resetting_execution(self):
        self.t.sample();self.assertEqual(len(self.changes()),1)
        fix.disconnect(self.m,self.m.ws,1,websocket.WebSocketConnectionClosedException('Connection to remote host was lost.'))
        self.now+=1;self.t.sample();self.assertEqual(len(self.changes()),2)
        self.assertFalse(self.changes()[-1]['public']['monitor']['connected'])
        self.m.connected=True;self.m.generation+=1;self.m.error=None
        self.now+=1;self.t.sample();self.assertEqual(len(self.changes()),3)
        self.assertEqual(self.s.generation,1);self.assertTrue(self.s.connected);self.assertEqual(self.e.connection_key,(1,1))
        self.assertEqual(self.changes()[-1]['public']['monitor']['disconnect_count'],1)
    def test_locked_monitor_does_not_create_fake_disconnect_event(self):
        self.t.sample();lock=self.m.lock;self.m.lock=NS(acquire=lambda **k:False)
        self.now+=1;self.t.sample();self.assertEqual(len(self.changes()),1)
        self.m.lock=lock;self.now+=1;self.t.sample();self.assertEqual(len(self.changes()),1)
    def test_quote_lag_uses_existing_clock_and_latest_arrival_not_stalest_symbol(self):
        self.m.data={('OLD','tickers'):({'ts':'1000'},90,1),('NEW','tickers'):({'ts':'98500'},99.99,1)}
        d=fix.diagnostics(self.m);d.update(frame_at=99.99,pong_at=99,pending_ping_at=99.5)
        row=snapshot(self.e,lambda:100)['public']['monitor']
        self.assertEqual(row['latest_quote_lag_s'],1.5);self.assertEqual(row['last_market_receive_age_s'],.01)
        self.assertEqual(row['frame_age_s'],.01);self.assertEqual(row['pending_ping_age_s'],.5)
        self.e.api.now_ms.assert_not_called()
        self.e.api.server_ms=0
        self.assertIsNone(snapshot(self.e,lambda:100)['public']['monitor']['latest_quote_lag_s'])
    def test_periodic_monitor_samples_keep_cpu_and_lag_context_between_events(self):
        with patch('phone_connection_trace.time.process_time',side_effect=[self.t.last_cpu+.1,self.t.last_cpu+.3,self.t.last_cpu+.4]):
            self.now=101;self.t.sample();self.now=102;self.t.sample();self.now=106;self.t.sample()
        rows=[r for r in self.t.events if r['kind']=='monitor_sample']
        self.assertEqual(len(rows),2);self.assertAlmostEqual(rows[0]['resources']['cpu_one_core_pct'],10)
        self.assertEqual(rows[0]['observer_gap_s'],1)
        clean=safe(self.t.document());report=sanitized(self.t.document())
        for data in (clean,report):
            self.assertTrue(any(x['kind']=='monitor_sample' for x in data['events']))
            self.assertNotIn('100000',json.dumps(data))  # clock internals are not exported
    def test_bounded_trace_remains_exportable_during_disconnect_storm(self):
        history=[dict(observed_at=100,cause='read_eof',generation=i,error='WebSocketConnectionClosedException',
            stage='receive',connection_uptime_s=100,frame_age_s=.1,pong_age_s=5,pending_ping_age_s=None,
            close_code=None,server_notice=None) for i in range(8)]
        for lane in (self.s,self.m):fix.diagnostics(lane)['disconnect_history']=history
        row=dict(kind='periodic_change',time_kst='2026-11-17T04:00:00+09:00',**snapshot(self.e,lambda:100))
        for _ in range(120):self.t.events.append(copy.deepcopy(row))
        self.t.latest=snapshot(self.e,lambda:100);self.t.persist()
        p=Path(self.tmp.name)/'phone_connection_trace.json'
        self.assertLessEqual(p.stat().st_size,240*1024);self.assertGreater(self.t.trimmed_events,0)
        self.assertTrue(json.loads(p.read_text())['events'])


if __name__=='__main__':unittest.main(verbosity=2)
