"""Additional routes use the normal order and position-management paths, offline."""
import unittest
from unittest.mock import Mock
from test_pc280 import OfflineEngine, P, SYMBOL
from test_pc2110 import live_context_signal
from test_wick_alert import candles
from pc_extra_entries import FIVE, SHORT, TREND, MorningShort, morning, trend_side
from pc_held_positions import manage
from phone_trend_slot import install


class AdditionalEntries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install(P/'core')

    def test_consensus_opposite_existing_blocked(self):
        e=OfflineEngine()
        e.wick_entries.set_mode('symbol_flow')
        original=live_context_signal(e)
        self.assertTrue(original.initial_block)
        self.assertEqual(trend_side(original.bars),-1)
        self.assertTrue(e.wick_entries.poll(),e.status())
        held=e.records()[0]
        s=held['v4_signal']
        self.assertEqual((s['pc217'],s['action'],e.api.orders()[0]['side']),(TREND,'SHORT','sell'))
        self.assertLess(float(held['committed_margin']),49)
        self.assertLessEqual(float(held['estimated_loss']),.735)
        self.assertEqual(held['wick_chart']['side'],-1)
        e.close=Mock()
        self.assertTrue(manage(e,{},dict(avgPx=100,markPx=99),dict(held,stop_px=101,v4_signal=dict(s,stop=101))))
        e.close.assert_called_once()

    def test_existing_order_wins(self):
        e=OfflineEngine()
        live_context_signal(e)
        self.assertTrue(e.wick_entries.poll(),e.status())
        e.wick_entries.poll()
        self.assertEqual(len(e.api.orders()),1)
        self.assertFalse(e.records()[0]['v4_signal'].get('pc217'))

    def test_morning_tape_to_order_and_exits(self):
        e=OfflineEngine()
        from pc_wick_alert import Anchor
        end=e.api.now//86400000*86400000
        e.api.now=end+10
        self.assertTrue(morning(end))
        self.assertFalse(morning(end+3*3600000))
        rows=[(end+(i-50)*FIVE,o,h+.35,l-.35,c,2*v if i>=47 else v)
              for i,(_,o,h,l,c,v) in enumerate(candles(-1))]
        watch=MorningShort(.01)
        watch.seed(rows)
        watch.detector.anchor=Anchor(end-FIVE,-103.5,1,-103.15,-103.,True)
        for i,px in enumerate((103.1,103.43,103.41)):
            hit=watch.take(rows,end+i,i+1,px,end-1)
        self.assertIsNotNone(hit)
        e.api.bid,e.api.ask=103.4,103.41
        e.wick_entries.offer(SYMBOL,hit,'.01',tuple(rows))
        self.assertTrue(e.wick_entries.poll(),e.status())
        held=e.records()[0]
        self.assertEqual(held['v4_signal']['pc217'],SHORT)
        entry=103.4
        risk=held['v4_signal']['stop']-entry
        e.trail=Mock()
        self.assertFalse(manage(e,{},dict(avgPx=entry,markPx=entry-2*risk),held))
        self.assertTrue(manage(e,{},dict(avgPx=entry,markPx=entry-3*risk),held))
        self.assertAlmostEqual(e.trail.call_args.args[-1],entry-1.5*risk)
        e.close=Mock()
        e.api.now=held['entry_ms']+150*60000
        self.assertTrue(manage(e,{},dict(avgPx=entry,markPx=entry),held))
        e.close.assert_called_once()
