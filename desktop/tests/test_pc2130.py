"""Symmetric confirmed swing breakouts and execution boundaries."""
import unittest
from test_pc280 import OfflineEngine, P
from test_wick_alert import STEP, SYMBOL, candles
from pc_wick_alert import MarketWicks
from pc_wick_entries import Reaction, make_signal
from okx_core import BotError
from pc_swing_break import setup

def bars(side):
    rows=candles()
    for i in range(50):
        t=rows[-1][0]+STEP
        lo=96.51 if i in (8,22) else 96.50 if i==38 else 96.54
        hi=96.59 if i==28 else 96.57
        rows.append((t,96.55,hi,lo,96.56,70))
    if side<0:
        rows=[(t,200-o,200-l,200-h,200-c,v) for t,o,h,l,c,v in rows]
    return rows

class Neckline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from phone_trend_slot import install
        install(P/'core')

    def test_three_confirmed_extrema_first_cross_and_protected_plan(self):
        for side in (1,-1):
            rows=bars(side); w=MarketWicks(.01);w.seed(rows)
            h=w.swings[side];t=rows[-1][0]+STEP;level=h['neckline']
            self.assertAlmostEqual(level,96.59 if side==1 else 103.41)
            self.assertFalse([v for v in w.trade(t,1,level,True) if 'neckline' in v])
            hit=next(v for v in w.trade(t+1,2,level+side*.01,True) if 'neckline' in v)
            self.assertFalse([v for v in w.trade(t+2,3,level+2*side*.01,True) if 'neckline' in v])
            e=OfflineEngine();e.api.now=t+1
            r=Reaction(SYMBOL,hit,'.01',tuple(rows),'')
            self.assertFalse(r.needs_confirmation)
            sig=make_signal(e,r)
            self.assertEqual(sig['decision_record']['volume_wick_proof']['neckline'],level)
            self.assertGreater(side*(hit['second']-sig['stop']),0)
            e.wick_entries.current=(r,sig)
            with self.assertRaises(BotError):e.wick_entries.validate(sig,level)
            e.wick_entries.validate(sig,hit['price'])

    def test_invalidation_and_restart_do_not_emit_previous_cross(self):
        for side in (1,-1):
            rows=bars(side);w=MarketWicks(.01);w.seed(rows);h=w.swings[side];t=rows[-1][0]+STEP
            w.trade(t,1,h['second']-side*.01,True)
            self.assertNotIn(side,w.swings)
            p=h['neckline']+side*.01
            w.seed(rows+[(t,p,p,p,p,100)])
            self.assertNotIn(side,w.swings)
            self.assertIsNone(setup(rows[:-6],side,100,.01))
