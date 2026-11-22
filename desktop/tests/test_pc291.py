"""Replay 15m reactions through the real outbox. The HTTP adapter never opens a socket."""
from email import policy
from email.parser import BytesParser
import json
from pathlib import Path
from queue import Queue
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import zlib

import requests
from test_pc280 import OfflineEngine, P, SYMBOL, STEP, candles, raw
from okx_core import BotError, Rejected, UnknownOutcome
from okx_notify import DELAY_NOTE, Notifier, WICK_EVENT, WICK_RESULT
from okx_v5 import RuleEngine
from pc_wick_chart import HEIGHT, MARK, WIDTH, render, signal_time
from pc_wick_feed import CANDLE, TRADES, SymbolWatch

SETTINGS = dict(TELEGRAM_BOT_TOKEN='offline', TELEGRAM_CHAT_ID='offline')
CFG = {'notifications': {'enabled': True, 'repeat_wait_seconds': 60}}


class Recorder(requests.adapters.BaseAdapter):
    def __init__(self, status=200, description=''):
        self.status = status
        self.description = description
        self.messages = []

    def send(self, request, **kwargs):
        method = request.url.rsplit('/',1)[-1]
        if method == 'sendPhoto':
            header = ('Content-Type: '+request.headers['Content-Type']+'\r\n\r\n').encode()
            msg = BytesParser(policy=policy.default).parsebytes(header+request.body)
            fields = {part.get_param('name',header='content-disposition'):part for part in msg.iter_parts()}
            self.messages.append((method,fields['caption'].get_payload(decode=True).decode(),
                                  fields['photo'].get_payload(decode=True)))
            assert fields['photo'].get_content_type() == 'image/png'
            assert fields['chat_id'].get_content().strip() == 'offline'
        else:
            self.messages.append((method,json.loads(request.body)['text'],None))
        code = self.status if method == 'sendPhoto' else 200
        response = requests.Response()
        response.status_code = code
        response._content = json.dumps(dict(ok=code==200,result={},description=self.description)).encode()
        return response

    def close(self):
        pass


class WickPhotos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from phone_trend_slot import install
        install(P/'core')

    def engine(self, root):
        e = OfflineEngine()
        e.feed.notifier = e.notifier = Notifier(root,SETTINGS,CFG)
        e.notify = RuleEngine.notify.__get__(e)
        e.settings, e.events = {}, Queue()
        return e

    def deliver(self, notifier, items, adapter=None):
        adapter = adapter or Recorder()
        with requests.Session() as http:
            http.mount('https://',adapter)
            for item in items:
                notifier.deliver(http,item)
        return adapter.messages

    def test_all_signal_and_order_outcomes_frozen_on_real_reaction(self):
        for side in (1,-1):
            for mode, final in (('off','자동 미진입'),('limit','포지션 한도'),('expired','만료'),
                                ('reject','거래소 거절'),('uncertain','결과 미확인'),('accepted','자동 주문 접수')):
                with self.subTest(side=side,mode=mode), TemporaryDirectory() as root:
                    e = self.engine(root)
                    e.enabled = mode != 'off'
                    if mode == 'limit':
                        e.raw_snapshot['manual_positions'] = [dict(instId=str(i),posSide='long',pos='1') for i in range(3)]
                    if mode == 'reject':
                        e.api.error = Rejected('거래소 거절')
                    if mode == 'uncertain':
                        e.api.error = UnknownOutcome('모의 시간 초과')
                    e.signal(side)
                    first = e.notifier.data['pending'][0]
                    chart = first['chart']
                    if mode == 'expired':
                        e.api.now += 16_000
                    if mode == 'uncertain':
                        with self.assertRaises(UnknownOutcome):
                            e.wick_entries.poll()
                    else:
                        e.wick_entries.poll()
                    pending = e.notifier.data['pending']
                    self.assertIn(final,pending[-1]['text'])
                    expected = ['sendPhoto'] * (1 if mode=='off' else 2)
                    messages = self.deliver(e.notifier,pending)
                    self.assertEqual([m[0] for m in messages],expected)
                    self.assertTrue(all(m[2] == messages[0][2] for m in messages))
                    self.assertTrue(all(signal_time(chart) in m[1] for m in messages))
                    self.assertEqual(chart['price'],96.57 if side==1 else 103.43)
                    self.assertEqual(chart['live'][-1],chart['price'])
                    self.assertAlmostEqual(chart['live'][3 if side==1 else 2],chart['second'])
                    self.assertEqual(chart['closed'][-1][0]+STEP,chart['ts']//STEP*STEP)
                    self.assertEqual(len(e.api.orders()),int(mode in ('accepted','reject','uncertain')))

    def test_future_candle_and_trade_cannot_enter_snapshot(self):
        with TemporaryDirectory() as root:
            e = self.engine(root)
            e.signal()
            item = e.notifier.data['pending'][0]
            before = render(item['chart'])
            bucket = item['chart']['live'][0]
            # A later, much larger intrabar high and a later print shouldn't alter the captured reaction.
            for channel,data in ((CANDLE,[[str(bucket),'96.74','110','95','108','120','0','0','0']]),
                                 (TRADES,[dict(ts=bucket+250,tradeId='80',px='108')])):
                e.feed.message(dict(arg=dict(channel=channel,instId=SYMBOL),data=data),bucket+260)
            self.assertEqual(render(item['chart']),before)
            self.assertEqual(item['chart']['live'][2],96.74)
            # Inspect real PNG geometry and ring color without optional image dependencies.
            self.assertEqual(before[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('!II',before[16:24]),(WIDTH,HEIGHT))
            offset = 8
            while before[offset+4:offset+8] != b'IDAT':
                offset += 12+int.from_bytes(before[offset:offset+4],'big')
            size = int.from_bytes(before[offset:offset+4],'big')
            raster = zlib.decompress(before[offset+8:offset+8+size])
            self.assertEqual(len(raster),(3*WIDTH+1)*HEIGHT)
            ring_pixels = sum(raster[y*(3*WIDTH+1)+1+3*800:y*(3*WIDTH+1)+1+3*855].count(bytes(MARK))
                              for y in range(125,450))
            self.assertGreater(ring_pixels,90)

    def test_watch_only_and_out_of_order_channels(self):
        with TemporaryDirectory() as root:
            e = self.engine(root)
            feed = e.feed
            feed.entries = None
            rows = candles()
            t = rows[-1][0]+STEP
            state = feed.markets[SYMBOL] = SymbolWatch('.01')
            self.assertTrue(state.seed([raw(r) for r in rows[:-1]],t-1))
            feed.message(dict(arg=dict(channel=TRADES,instId=SYMBOL),event='subscribe'),t-50)
            # The later official intrabar high arrives first. The preceding close then unlocks the trades.
            feed.message(dict(arg=dict(channel=CANDLE,instId=SYMBOL),
                              data=[raw((t,96.74,110,96.56,108,7),False)]),t+8)
            trade_rows = [dict(ts=t+i,tradeId=i+1,px=p) for i,p in enumerate((96.74,96.56,96.57,98))]
            feed.message(dict(arg=dict(channel=TRADES,instId=SYMBOL),data=trade_rows),t+8)
            feed.message(dict(arg=dict(channel=CANDLE,instId=SYMBOL),data=[raw(rows[-1])]),t+9)
            photo, = e.notifier.data['pending']
            self.assertEqual(photo['chart']['live'],(t,96.74,96.74,96.56,96.57))
            self.assertEqual(self.deliver(e.notifier,[photo])[0][0],'sendPhoto')
            self.assertFalse(e.api.orders())

    def test_overlapping_symbols_keep_their_own_chart(self):
        with TemporaryDirectory() as root:
            e = self.engine(root)
            e.signal(1,symbol='ONE-USDT-SWAP')
            e.signal(-1,symbol='TWO-USDT-SWAP')
            e.api.now += 20_000
            e.wick_entries.poll()
            messages = self.deliver(e.notifier,e.notifier.data['pending'])
            self.assertEqual(len(messages),4)
            for name in ('ONE','TWO'):
                pair = [m for m in messages if name in m[1]]
                self.assertEqual(len(pair),2)
                self.assertEqual(pair[0][2],pair[1][2])
            self.assertNotEqual(messages[0][2],messages[1][2])

    def test_confirmed_fill_after_reload_preserves_reference_and_actual_price(self):
        with TemporaryDirectory() as root:
            e = self.engine(root)
            e.signal()
            self.assertTrue(e.wick_entries.poll())
            e.journal.data = json.loads(json.dumps(e.durable))
            e.notifier = Notifier(root,SETTINGS,CFG)
            owned = e.records()[0]
            qty = owned['quantity']
            e.api.get = Mock(return_value=[dict(state='filled',accFillSz=qty,avgPx='96.58')])
            position = dict(instId=SYMBOL,posSide='long',pos=qty,posId='offline',mgnMode='isolated',
                            lever=str(owned['leverage']),avgPx='96.58',markPx='96.58')
            e.reconcile(dict(positions=[position],ms=e.api.now))
            pending = e.notifier.data['pending']
            self.assertEqual([p['event'] for p in pending],[WICK_EVENT,WICK_RESULT,'진입 체결'])
            self.assertIn('체결가 96.58',pending[-1]['text'])
            delivered = self.deliver(e.notifier,pending)
            self.assertTrue(all(p[0]=='sendPhoto' and p[2]==delivered[0][2] for p in delivered))
            self.assertIn('진입 검토가 96.57',delivered[-1][1])

    def test_confirmed_unfilled_cancel_and_partial_fill(self):
        for partial in (False,True):
            with self.subTest(partial=partial),TemporaryDirectory() as root:
                e = self.engine(root)
                e.signal()
                self.assertTrue(e.wick_entries.poll())
                owned = e.records()[0]
                qty = '.75' if partial else '0'
                rows = [dict(instId=SYMBOL,posSide='long',pos=qty,posId='offline',mgnMode='isolated',
                        lever=str(owned['leverage']),avgPx='96.58')] if partial else []
                e.api.get = Mock(return_value=[dict(state='canceled',accFillSz=qty,avgPx='96.58')])
                e.pause = e.close = e.finish_position = Mock()
                e.reconcile(dict(positions=rows,ms=e.api.now))
                result = e.notifier.data['pending'][-1]
                self.assertIn('일부 체결' if partial else '미체결 취소 확인',result['text'])
                self.assertEqual(self.deliver(e.notifier,[result])[0][0],'sendPhoto')

    def test_settlement_uses_closed_positions_original_chart_after_restart(self):
        with TemporaryDirectory() as root:
            e = self.engine(root)
            e.root = Path(root)
            e.signal(-1)
            e.wick_entries.poll()
            owned = e.records()[0]
            owned.update(posId='first-short',has_fill=True)
            expected = render(owned['wick_chart'])
            e.journal.data['settlements'] = []
            with patch('okx_engine.Engine.finish_position'):
                e.finish_position()
            e.journal.data = json.loads(json.dumps(e.durable))
            e.journal.data['owned'] = None
            e.journal.data['day']['base'] = '150'
            e.strategy_roi = Mock(return_value=0)
            e.api.get = Mock(return_value=[dict(posId='first-short',uTime=e.api.now,
                                               realizedPnl='1',closeAvgPx='103.1')])
            with patch('okx_online_learning.refresh',return_value={'accepted_trades':0}):
                e.settle(dict(equity='151'))
            notice, = [p for p in e.notifier.data['pending'] if p['event']=='청산 손익']
            self.assertEqual(self.deliver(e.notifier,[notice])[0][2],expected)
            self.assertEqual(e.journal.data['settlements'],[])

    def test_retry_backlog_dedup_and_existing_text(self):
        with TemporaryDirectory() as root:
            e = self.engine(root)
            e.enabled = False
            e.signal()
            e.signal()
            item = e.notifier.data['pending'][0]
            self.assertEqual(len(e.notifier.data['pending']),1)
            with self.assertRaises(BotError):
                self.deliver(e.notifier,[item],Recorder(502,'upstream failure'))
            # A restart after the former 60s text TTL must deliver the original photo.
            n = Notifier(root,SETTINGS,CFG)
            n.data['pending'][0]['expires'] = 1
            adapter = Recorder()
            with requests.Session() as http:
                http.mount('https://',adapter)
                n.on_success = n.stop_event.set
                with patch('requests.Session',return_value=http):
                    n.run()
            self.assertFalse(n.data['pending'])
            self.assertIn(DELAY_NOTE,adapter.messages[0][1])
            n.emit('실거래 시작','ok')
            n.wick_result('이전 버전 알림','old')
            self.assertEqual([r[0] for r in self.deliver(n,n.data['pending'])],['sendMessage','sendMessage'])

    def test_only_definitive_media_refusal_uses_text_and_long_captions_fit(self):
        with TemporaryDirectory() as root:
            e = self.engine(root)
            e.enabled = False
            e.signal()
            item = e.notifier.data['pending'][0]
            refusal = self.deliver(e.notifier,[item],Recorder(403,'CHAT_SEND_PHOTOS_FORBIDDEN'))
            self.assertEqual([m[0] for m in refusal],['sendPhoto','sendMessage'])
            self.assertIn('사진 전송을 거절',refusal[-1][1])
            text = '💬거래소 상세 응답 ' * 180
            e.notifier.wick_result(text,'long-result',chart=item['chart'])
            parts = [p for p in e.notifier.data['pending'] if p['event']==WICK_RESULT]
            self.assertEqual(''.join(p['text'] for p in parts),text)
            sent = self.deliver(e.notifier,parts)
            self.assertTrue(all(method=='sendPhoto' and len(caption.encode('utf-16-le'))<=2048
                                for method,caption,_ in sent))

if __name__=='__main__':
    unittest.main()
