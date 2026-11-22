"""Inclusive 15-minute lower-wick window through the public feed and order gates."""
import struct
import unittest
from unittest.mock import patch

from test_pc280 import OfflineEngine, P
from test_wick_alert import SYMBOL, candles, raw, reflect
from pc_wick_alert import STEP, HISTORY
from pc_wick_chart import caption_note, render, visible_bars, WIDTH, HEIGHT
from pc_wick_entries import make_signal
from pc_wick_feed import SymbolWatch, TRADES
from okx_core import BotError
from okx_engine import day_key


def feed_after_restart(side, number, earlier_touch=False):
    engine=OfflineEngine()
    rows=candles(side)
    anchor=rows[-1][0]
    # Enough pre-anchor history for the displaced cloud over the entire long chart.
    pre=[(rows[0][0]-n*STEP,100.,100.1,99.9,100.,70.) for n in range(65,0,-1)]
    for k in range(1,number):
        low=96.55 if earlier_touch and k==46 else 96.74
        r=(anchor+k*STEP,96.78,96.82,low,96.78,70.)
        rows.append(r if side==1 else reflect(r))
    start=anchor+number*STEP
    engine.api.now=start+100
    engine.raw_snapshot['ms']=engine.api.now
    engine.journal.data['day']['date']=day_key(engine.api.now)
    state=engine.feed.markets[SYMBOL]=SymbolWatch('.01')
    assert state.seed([raw(r) for r in (pre+rows)[-HISTORY:]],engine.api.now)
    engine.feed.message({'event':'subscribe','arg':dict(channel=TRADES,instId=SYMBOL)},start-1)
    for i,px in enumerate([96.74,96.56,96.57]):
        p=px if side==1 else 200-px
        engine.feed.message(dict(arg=dict(channel=TRADES,instId=SYMBOL),
                 data=[dict(instId=SYMBOL,ts=str(start+i),tradeId=str(i+1),px=str(p))]),engine.api.now)
    return engine,anchor


class LowerWickWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from phone_trend_slot import install
        install(P/'core')

    def test_hundredth_long_reaches_alert_chart_and_protected_order_after_restart(self):
        e,anchor=feed_after_restart(1,100)
        r=next(iter(e.wick_entries.pending.values()))
        self.assertEqual(r.hit['bars'],100)
        self.assertIn('100번째',e.notifier.wick_alert.call_args.args[-1])
        chart=r.chart
        self.assertIn('100번째 15분봉',caption_note(chart))
        self.assertEqual(visible_bars(chart),105)
        bars=[*chart['closed'],chart['live']][-visible_bars(chart):]
        self.assertIn(anchor,[b[0] for b in bars])
        self.assertIn(anchor,[c[0] for c in chart['cloud']])
        self.assertEqual(struct.unpack('!II',render(chart)[16:24]),(WIDTH,HEIGHT))
        self.assertTrue(e.wick_entries.poll(),e.status())
        self.assertEqual(len(e.api.orders()),1,e.status())
        self.assertIn('slTriggerPx',e.api.orders()[0]['attachAlgoOrds'][0])

    def test_order_gate_independently_rejects_an_expired_anchor(self):
        for side,boundary in ((1,100),(-1,30)):
            with self.subTest(side=side):
                e,_=feed_after_restart(side,boundary)
                r=next(iter(e.wick_entries.pending.values()))
                self.assertEqual(make_signal(e,r)['action'],'LONG' if side==1 else 'SHORT')
                with patch.dict(r.hit,anchor_ms=r.hit['anchor_ms']-STEP):
                    with self.assertRaisesRegex(BotError,'시간 만료'):make_signal(e,r)

    def test_old_or_previously_retested_wicks_do_not_fire_on_reconnect(self):
        for side,age,touch in ((1,101,False),(-1,31,False),(1,100,True)):
            with self.subTest(side=side,age=age,touch=touch):
                e,_=feed_after_restart(side,age,touch)
                self.assertFalse(e.wick_entries.pending)
                e.notifier.wick_alert.assert_not_called()
                self.assertFalse(e.api.orders())


if __name__=='__main__':
    unittest.main()
