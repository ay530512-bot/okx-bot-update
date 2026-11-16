"""Behavioral transport regressions; no real exchange or orders."""
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

D = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(D/'phone_v162'), str(D.parent.parent/'core121')]
import okx_stream
import phone_public_ws as transport
import phone_public_lanes as lanes
import websocket

transport.install()
lanes.install()


def active(s):
    s.ws = Mock(); s.connected = True; s.generation = 1
    return s


def feed(s, channel='tickers', symbol='A-USDT-SWAP', stamp=1000000, price='2'):
    row = {'ts':str(stamp), 'last':price, 'markPx':price}
    s.feed(json.dumps({'arg':{'channel':channel, 'instId':symbol}, 'data':[row]}))


class Lanes(unittest.TestCase):
    def setUp(self):
        self.s = active(okx_stream.MarketStream())
        self.m = active(self.s._phone_monitor_stream)
        self.s.monitor(['A-USDT-SWAP', 'B-USDT-SWAP'])
        self.s.watch(['A-USDT-SWAP'])

    def test_290_tickers_and_candidate_use_separate_connections(self):
        self.s.monitor([f'X{i}-USDT-SWAP' for i in range(288)])
        transport.flush_subscriptions(self.s)
        transport.flush_subscriptions(self.m)
        self.assertEqual(len(self.s.active_pairs),4)
        self.assertEqual(len(self.m.active_pairs),290)
        self.assertTrue(all(ch=='tickers' for _,ch in self.m.active_pairs))
        self.assertEqual({ch for _,ch in self.s.active_pairs},set(self.s.CHANNELS))

    def test_monitor_eof_keeps_live_execution_quotes_and_generation(self):
        for ch in self.s.CHANNELS: feed(self.s,ch)
        feed(self.m,symbol='B-USDT-SWAP')
        generation=self.s.generation
        transport.disconnect(self.m,self.m.ws,1,ConnectionResetError())
        cfg={'liquidity':{'ws_max_age_seconds':15,'trade_max_age_seconds':60}}
        self.assertTrue(self.s.ready('A-USDT-SWAP',cfg,1000001))
        self.assertIsNone(self.s.read('B-USDT-SWAP','tickers',now_ms=1000001))
        self.assertEqual(self.s.generation,generation)
        self.assertTrue(self.s.connected)

    def test_execution_eof_cannot_use_fresh_monitor_quotes(self):
        feed(self.s);feed(self.m)
        transport.disconnect(self.s,self.s.ws,1,ConnectionResetError())
        self.assertIsNone(self.s.read('A-USDT-SWAP','tickers',now_ms=1000001))
        self.assertIsNotNone(self.m.read('A-USDT-SWAP','tickers',now_ms=1000001))

    def test_promoting_monitor_symbol_requires_new_execution_data(self):
        feed(self.m,symbol='B-USDT-SWAP')
        self.assertIsNotNone(self.s.read('B-USDT-SWAP','tickers',now_ms=1000001))
        self.s.watch(['A-USDT-SWAP','B-USDT-SWAP'])
        self.assertIsNone(self.s.read('B-USDT-SWAP','tickers',now_ms=1000001))
        feed(self.s,symbol='B-USDT-SWAP')
        self.assertIsNotNone(self.s.read('B-USDT-SWAP','tickers',now_ms=1000001))

    def test_stale_future_and_old_generation_remain_rejected_both_lanes(self):
        for symbol,lane in [('A-USDT-SWAP',self.s),('B-USDT-SWAP',self.m)]:
            feed(lane,symbol=symbol)
            self.assertIsNone(self.s.read(symbol,'tickers',now_ms=1038000))
            self.assertIsNone(self.s.read(symbol,'tickers',now_ms=999499))
            self.assertIsNotNone(self.s.read(symbol,'tickers',now_ms=1000001))
            lane.generation+=1
            self.assertIsNone(self.s.read(symbol,'tickers',now_ms=1000001))

    def test_monitor_bands_preserve_intrabar_extremes(self):
        for price in ('2','5','1','3'):feed(self.m,symbol='B-USDT-SWAP',price=price)
        bar=self.s.band_bar('B-USDT-SWAP','5m',[900000,2,2,2,2])
        self.assertEqual(bar,[900000,2,5,1,3])

    def test_all_mark_callbacks_remain_on_execution_lane(self):
        self.s.on_mark=Mock()
        for price in ('2','5','1','3'):feed(self.s,'mark-price',price=price)
        self.assertEqual(self.s.on_mark.call_count,4)
        self.assertFalse(hasattr(self.m,'on_mark'))

    def test_ui_monitor_changes_do_not_evict_execution(self):
        feed(self.s)
        self.s.monitor(['C-USDT-SWAP'])
        self.assertIsNotNone(self.s.read('A-USDT-SWAP','tickers',now_ms=1000001))
        self.assertIn('C-USDT-SWAP',self.m.monitor_symbols)
        self.assertEqual(self.s.symbols,{'A-USDT-SWAP'})

    def test_manual_reconnect_and_stop_cover_both_lanes(self):
        a,b=self.s.ws,self.m.ws
        self.s.reconnect()
        self.assertFalse(self.s.connected);self.assertFalse(self.m.connected)
        a.close.assert_called();b.close.assert_called()
        self.s.stop()
        self.assertTrue(self.s.stop_event.is_set());self.assertTrue(self.m.stop_event.is_set())

    def test_start_is_idempotent_and_reader_ownership_is_separate(self):
        s=okx_stream.MarketStream();started=[];done=threading.Event()
        def run(obj):started.append(obj);done.wait(1)
        s.run=lambda:run(s);s._phone_monitor_stream.run=lambda:run(s._phone_monitor_stream)
        s.start();s.start()
        done.set();s._phone_reader.join(1);s._phone_monitor_stream._phone_reader.join(1)
        self.assertCountEqual(started,[s,s._phone_monitor_stream])

    def test_subscription_ack_distinguished_from_sent_and_cleared_on_disconnect(self):
        transport.flush_subscriptions(self.s)
        self.assertFalse(getattr(self.s,'_phone_acknowledged',set()))
        msg=json.dumps({'event':'subscribe','arg':{'channel':'trades','instId':'A-USDT-SWAP'}})
        ws=Mock();ws.recv_data_frame.return_value=(1,Mock(data=msg.encode()))
        transport.receive(ws,websocket,self.s)
        self.assertIn(('A-USDT-SWAP','trades'),self.s._phone_acknowledged)
        self.assertIsNone(self.s.read('A-USDT-SWAP','trades',now_ms=1000001))
        transport.disconnect(self.s,self.s.ws,1,ConnectionResetError())
        self.assertFalse(self.s._phone_acknowledged)

    def test_both_disconnect_histories_and_rtt_export_without_secrets(self):
        from phone_connection_trace import snapshot
        from phone_diagnostic_export import safe
        from types import SimpleNamespace as NS
        transport.disconnect(self.m,self.m.ws,1,ConnectionResetError('SECRET'))
        transport.disconnect(self.s,self.s.ws,1,ConnectionResetError('SECRET'))
        e=NS(stream=self.s,account_stream=NS(received=0,connected=False,generation=0,
             error=None,equity=None,fresh=lambda:False),connection_key=None,recovering=True,
             good_snapshots=0,enabled=False,user_paused=True,entry_cancel=threading.Event())
        out=safe(snapshot(e))
        self.assertEqual(out['public']['monitor']['disconnect_count'],1)
        self.assertEqual(out['public']['transport']['disconnect_count'],1)
        self.assertNotIn('SECRET',json.dumps(out))


class Decoding(unittest.TestCase):
    def receive(self, frames):
        ws=transport.public_socket_class(websocket)(skip_utf8_validation=True)
        ws.recv_frame=Mock(side_effect=frames);ws.send_close=Mock();ws.pong=Mock()
        return ws,okx_stream.MarketStream()

    def test_fragmented_unicode_still_decoded_strictly(self):
        ab=websocket.ABNF;raw='{"name":"한글"}'.encode();cut=10
        ws,s=self.receive([ab.create_frame(raw[:cut],ab.OPCODE_TEXT,0),ab.create_frame(raw[cut:],ab.OPCODE_CONT,1)])
        self.assertEqual(transport.receive(ws,websocket,s),' {"name":"한글"}'.strip())

    def test_invalid_text_binary_and_close_utf8_are_rejected(self):
        ab=websocket.ABNF
        for opcode,raw in [(ab.OPCODE_TEXT,b'\xff'),(ab.OPCODE_BINARY,b'\xff'),
                           (ab.OPCODE_CLOSE,(1000).to_bytes(2,'big')+b'\xff')]:
            with self.subTest(opcode=opcode):
                ws,s=self.receive([ab.create_frame(raw,opcode)])
                with self.assertRaises(UnicodeDecodeError):transport.receive(ws,websocket,s)


if __name__=='__main__':unittest.main(verbosity=2)
