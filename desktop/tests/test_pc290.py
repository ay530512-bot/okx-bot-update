"""KST close, persistence, source of signals, and upgrade. Offline exchange doubles only."""
import copy
import json
from queue import Queue
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from test_pc280 import OfflineEngine, candles, SYMBOL, STEP, P
from okx_core import BotError, OKX
from okx_click716 import accept
from pc_held_positions import manage
from pc_intraday import due, session_close_ms, CLOSE_REASON

class Intraday(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from phone_trend_slot import install
        install(P/'core')

    def test_day_and_originating_deadline(self):
        # 2026-11-22 00:00 KST equals Nov 21 15:00 UTC.
        from datetime import datetime, timezone, timedelta
        midnight=int(datetime(2026,11,22,tzinfo=timezone(timedelta(hours=9))).timestamp()*1000)
        close=midnight+86340000
        for t in (midnight,midnight+8*3600000,close-1,close,midnight+86399999):
            self.assertEqual(session_close_ms(t),close)
        self.assertEqual(session_close_ms(midnight+86400000),close+86400000)
        for d in ({},{'v4_signal':{'pc260':True}}):
            self.assertFalse(due(d,midnight+90000000))

    def test_long_short_trailing_and_restored_deadline(self):
        for side in (1,-1):
            e=OfflineEngine();e.signal(side)
            self.assertTrue(e.wick_entries.poll(),e.status())
            o=copy.deepcopy(e.durable['owned']);sig=o['v4_signal']
            close=sig['kst_close_ms']
            self.assertEqual(close,session_close_ms(sig['at_ms']))
            self.assertIn('중심선까지',e.notifier.wick_alert.call_args.args[-1])
            self.assertTrue(sig['decision_record']['volume_wick_proof']['timing_distances'])
            # An opening early in the date survives 6 hours, then follows its original absolute deadline across restart.
            o['entry_ms']=close-12*3600000
            price=sig['entry_reference'];r=side*(price-sig['stop']);q=dict(markPx=price,avgPx=price)
            e.close=Mock();e.trail=Mock();e.api.now=close-5*3600000
            self.assertFalse(manage(e,{},q,o));e.close.assert_not_called()
            self.assertTrue(manage(e,{},dict(q,markPx=price+2*side*r),o));e.trail.assert_called_once()
            e.api.now=close-1
            self.assertTrue(manage(e,{},dict(q,markPx=sig['stop']),o))
            self.assertIn('보호 손절',e.close.call_args.args[1])
            e.close.reset_mock();e.api.now=close
            self.assertTrue(manage(e,{},q,o));e.close.assert_called_once_with({},CLOSE_REASON)
            e.close.reset_mock();e.api.now=close+2*3600000
            self.assertTrue(manage(e,{},{},json.loads(json.dumps(o))))
            e.close.assert_called_once_with({},CLOSE_REASON)
            # A previously open 2.8.x record keeps the original duration.
            sig.pop('kst_close_ms');sig['holding_rule']['max_hold_seconds']=21600
            e.api.now=o['entry_ms']+21600000
            self.assertTrue(manage(e,{},q,o));self.assertIn('360분',e.close.call_args.args[1])

    def test_direct_click_and_crossing_order_validation(self):
        e=OfflineEngine();e.events=Queue();e.chat=NS(watch=lambda:[])
        e.api.manual_bars=[(r[0],96.57,96.60,96.54,96.57,100) for r in candles()]
        def request(code):
            return dict(op='entry',issued_at=time.monotonic(),request_id='manual-example-'+code,symbol=SYMBOL,direction='LONG')
        deadline=session_close_ms(e.api.now)
        accept(e,request('a'))
        self.assertEqual(e.records()[0]['v4_signal']['kst_close_ms'],deadline)
        fresh=OfflineEngine();fresh.api.now=deadline
        fresh.events=Queue();fresh.chat=NS(watch=lambda:[])
        with self.assertRaisesRegex(BotError,'23:59'):
            accept(fresh,request('b'))
        self.assertFalse(fresh.api.orders())
        x=OfflineEngine();x.signal()
        x.api.before_book=lambda:setattr(x.api,'now',session_close_ms(x.api.now)+61000)
        x.wick_entries.poll()
        self.assertFalse(x.api.orders());self.assertFalse(x.records())

    def test_reconciliation_cancels_entry_remainder_immediately_at_cutoff(self):
        e=OfflineEngine();e.signal();self.assertTrue(e.wick_entries.poll())
        record=e.records()[0];deadline=record['v4_signal']['kst_close_ms']
        record['entry_ms']=deadline-50;e.api.now=deadline
        e.api.get=Mock(return_value=[dict(state='live',accFillSz='0')])
        e.api.post=Mock()
        snap=dict(positions=[],ms=deadline)
        for _ in range(2):e.reconcile(snap)
        e.api.post.assert_called_once_with('/api/v5/trade/cancel-order',dict(instId=SYMBOL,clOrdId=record['client_id']))
        self.assertTrue(e.durable['owned']['market_cancel_requested'])

    def test_late_signal_alert_and_new_session(self):
        e=OfflineEngine();e.signal()
        r=next(iter(e.wick_entries.pending.values()))
        close=session_close_ms(r.hit['ts'])
        for stamp,blocked in ((close,True),(close+60000,False)):
            engine=OfflineEngine();engine.api.now=stamp
            hit=dict(r.hit,ts=stamp,anchor_ms=(stamp//STEP-1)*STEP)
            engine.wick_entries.offer(SYMBOL,hit,r.tick,r.bars)
            pending=next(iter(engine.wick_entries.pending.values()))
            self.assertEqual(bool(pending.initial_block),blocked)
            engine.notifier.wick_alert.assert_called_once()
            if blocked:
                self.assertIn('23:59',engine.notifier.wick_alert.call_args.args[-1])
                self.assertFalse(engine.wick_entries.poll());self.assertFalse(engine.api.orders())

    def test_no_order_if_time_crosses_during_intent_save(self):
        e=OfflineEngine();e.signal()
        save=e.journal.save;close=session_close_ms(e.api.now)
        def slow_save():
            save()
            if e.journal.data.get('owned'):e.api.now=close
        e.journal.save=slow_save
        self.assertFalse(e.wick_entries.poll());self.assertFalse(e.api.orders())
        self.assertIsNone(e.durable['owned'])

    def test_due_close_uses_exact_position_once_even_after_timeout(self):
        from okx_core import UnknownOutcome
        e=OfflineEngine();e.signal();self.assertTrue(e.wick_entries.poll())
        o=e.records()[0];side=o['direction'];s=o['v4_signal']
        o.update(phase='active',posId='fixture-position')
        p=dict(instId=SYMBOL,posSide=side,pos=o['quantity'],posId=o['posId'],
               mgnMode='isolated',lever=str(o['leverage']),avgPx=s['entry_reference'],markPx=s['entry_reference'])
        e.api.now=s['kst_close_ms'];e.enabled=False
        e.api.error=UnknownOutcome('mock timeout')
        before=copy.deepcopy(o)
        with self.assertRaisesRegex(BotError,'수동 포지션'):
            manage(e,dict(positions=[dict(p,instId='OTHER-USDT-SWAP')]),p,o)
        self.assertEqual(o['phase'],'active')
        with self.assertRaises(UnknownOutcome):
            manage(e,dict(positions=[p]),p,o)
        self.assertEqual(e.durable['owned']['phase'],'closing')
        client_id=o['close_id']
        manage(e,dict(positions=[p]),p,o)
        closes=[r for r in e.api.orders() if r.get('clOrdId')==client_id]
        self.assertEqual(len(closes),1)
        self.assertEqual((closes[0]['sz'],closes[0]['side'],closes[0]['posSide']),(before['quantity'],'sell',side))
        self.assertEqual(o['algo_client_id'],before['algo_client_id'])

    def test_exchange_deadline_only_on_new_entry_request(self):
        import requests
        api=object.__new__(OKX)
        api.synced=time.monotonic();api.now_ms=lambda:1795300000000
        api.key=api.passphrase=api.secret='offline';api.requests=requests
        response=NS(status_code=200,json=lambda:dict(code='0',data=[{'ordId':'offline'}]))
        api.session=NS(request=Mock(return_value=response))
        with patch('okx_read_control.invalidate'):
            api.post_entry_until({'clOrdId':'entry'},1795300010000)
            api.post('/api/v5/trade/order',{'clOrdId':'close'})
        first,second=api.session.request.call_args_list
        self.assertEqual(first.kwargs['headers']['expTime'],'1795300010000')
        self.assertNotIn('expTime',second.kwargs['headers'])
        self.assertNotIn('expTime',first.kwargs['data'])

if __name__=='__main__':unittest.main()
