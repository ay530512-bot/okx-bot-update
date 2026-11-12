"""Offline risk-path tests; never constructs an exchange API or sends a trade."""
import copy
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
sys.path.insert(0, os.environ.get('OKX_TEST_APP', str(Path(__file__).parent/'app')))
import okx_long_wick_exit732 as w
import okx_profit_guard714 as guard

T = 1800000000000  # UTC 15m aligned
NOW = T + 16*w.STEP + 1000


def candles(side='short'):
    b = [[T+i*w.STEP, 95., 96., 91., 95.5, 100.] for i in range(16)]
    b[-2][1:5] = [95., 96., 90., 94.]
    b[-1][1:5] = [94., 95., 92., 94.5]
    if side == 'long':
        b = [[r[0], 200-r[1], 200-r[3], 200-r[2], 200-r[4], r[5]] for r in b]
    return b


def inputs(side='short', partial=False):
    o = dict(symbol='TIA-USDT-SWAP', direction=side, quantity=10, ct_val=1,
             entry_taker_fee=.0005, entry_ms=T, client_id='OEtest', phase='active',
             stop_px=110 if side=='short' else 90, leverage=10, partial_used=partial,
             v4_signal=dict(rule_channel701=True), cost_rate=.002)
    p = dict(instId=o['symbol'], posSide=side, pos=10, avgPx=100,
             markPx=94.5 if side=='short' else 105.5, fee=-.5, fundingFee=0,
             mgnMode='isolated', lever=10)
    return o,p


class FakeEngine:
    def __init__(self, owned, p):
        self.calls=[];self.saves=0
        self.cfg={'execution': {'rule_channel701':True}, 'liquidity':{'max_slippage':.0005}}
        self.api=types.SimpleNamespace(now_ms=lambda:NOW)
        self.journal=types.SimpleNamespace(data={'owned':owned},save=self.save)
        self.stream=types.SimpleNamespace(read=self.quote)
        self.price=float(p['markPx']);self.qts=NOW;self.events=types.SimpleNamespace(put=lambda x:None)
        self.bars=candles(owned['direction'])
    def save(self):self.saves+=1
    def quote(self,*a):return dict(ts=self.qts,bidPx=self.price-.01,askPx=self.price+.01)
    def close(self,snapshot,reason):
        o=self.journal.data['owned'];self.assert_saved=self.saves>0
        o['phase']='closing';self.calls.append(('close',reason))
    def partial_close(self,*a,**k):self.calls.append(('partial',None))
    def chart_job(self,*a):return {'15m':self.bars}
    def trail(self,*a):self.calls.append(('trail',None))


class Pattern(unittest.TestCase):
    def test_short_and_long_mirror(self):
        for side in ('short','long'):
            s=w.signal(candles(side),side,T,NOW)
            self.assertIsNotNone(s);self.assertEqual(s['reference_ms'],T+14*w.STEP)
    def test_own_body_not_previous_body(self):
        b=candles();b[-2][1:5]=[95,96,85,90] # previous body 5 > current wick 2
        self.assertIsNotNone(w.signal(b,'short',T,NOW))
    def test_equal_body_wick_rejected(self):
        b=candles();b[-1][1:5]=[94,96,92,96]
        self.assertIsNone(w.signal(b,'short',T,NOW))
    def test_long_wick_doji(self):
        b=candles();b[-1][4]=b[-1][1]
        self.assertIsNotNone(w.signal(b,'short',T,NOW))
    def test_extreme_equal_or_wrong_side_rejected(self):
        for low in (90,89):
            b=candles();b[-1][3]=low
            self.assertIsNone(w.signal(b,'short',T,NOW))
    def test_skip_previous_no_wick(self):
        b=candles();b[-2][3]=94
        self.assertEqual(w.signal(b,'short',T,NOW)['reference_ms'],T+13*w.STEP)
    def test_no_reference(self):
        b=candles()
        for r in b[:-1]:r[3]=min(r[1],r[4])
        self.assertIsNone(w.signal(b,'short',T,NOW))
    def test_pre_entry_signal_rejected_reference_allowed(self):
        b=candles();at=b[-1][0]
        self.assertIsNotNone(w.signal(b,'short',at,NOW))
        self.assertIsNone(w.signal(b,'short',at+1,NOW))
    def test_future_does_not_change_signal(self):
        b=candles();expect=w.signal(b,'short',T,NOW)
        b.append([T+16*w.STEP,1,500,1,400,900])
        self.assertEqual(expect,w.signal(b,'short',T,NOW))
    def test_freshness_boundaries(self):
        b=candles();close=T+16*w.STEP
        self.assertIsNotNone(w.signal(b,'short',T,close))
        self.assertIsNotNone(w.signal(b,'short',T,close+60000))
        self.assertIsNone(w.signal(b,'short',T,close+60001))
    def test_gap_bad_ohlc_nan_and_bad_entry(self):
        for kind in ('gap','ohlc','nan'):
            b=candles()
            if kind=='gap':b.pop(4)
            elif kind=='ohlc':b[-1][3]=1000
            else:b[-1][4]=float('nan')
            self.assertIsNone(w.signal(b,'short',T,NOW))
        for t in (None,'bad',float('nan'),NOW+1):
            self.assertIsNone(w.signal(candles(),'short',t,NOW))


class Costs(unittest.TestCase):
    def test_net_long_short(self):
        for side in ('long','short'):
            o,p=inputs(side);price=float(p['markPx']);s=1 if side=='long' else -1
            px=price*(1-s*.0005)
            self.assertAlmostEqual(w.remaining_net(p,o,price)['net'],10*(px-100)*s-.5-10*px*.0005)
    def test_gross_positive_cost_negative(self):
        o,p=inputs('long');self.assertLess(w.remaining_net(p,o,100.01)['net'],0)
    def test_partial_proceeds_cannot_subsidize_remainder(self):
        o,p=inputs('long',True);p['realizedPnl']=999;p['pnl']=999
        self.assertLess(w.remaining_net(p,o,99)['net'],0)
    def test_partial_funding_allocation_debit_and_credit(self):
        for funding in (-4,4):
            o,p=inputs('long',True)
            before=dict(p,pos=20,fundingFee=funding,fee=-1)
            o['long_wick_partial_cost732']=w.partial_cost_snapshot(before,o)
            p.update(fundingFee=funding-1,fee=-2)
            result=w.remaining_net(p,o,105)
            self.assertEqual(result['funding'],funding/2-1)
            self.assertEqual(result['entry_fee'],.5)
    def test_legacy_partial_no_credit_all_debits(self):
        o,p=inputs('long',True)
        for f,expected in ((4,0),(-4,-4)):
            p['fundingFee']=f;self.assertEqual(w.remaining_net(p,o,105)['funding'],expected)
    def test_missing_funding_or_fee_rate_is_unknown(self):
        o,p=inputs();p.pop('fundingFee');self.assertIsNone(w.remaining_net(p,o,94))
        o,p=inputs();o.pop('entry_taker_fee');self.assertIsNone(w.remaining_net(p,o,94))
    def test_invalid_and_quantity_mismatch(self):
        for key,v in (('ct_val',0),('ct_val','NaN'),('quantity',9),('entry_taker_fee',.5)):
            o,p=inputs();o[key]=v;self.assertIsNone(w.remaining_net(p,o,94))
    def test_partial_snapshot_persisted_in_reconcile(self):
        from okx_partial import PartialExits
        o,p=inputs('long');o.update(quantity='20',committed_margin='200',algo_client_id='OSold')
        p.update(pos='20',fee='-1',fundingFee='4');e=FakeEngine(o,p)
        e.invalidate=lambda:None;e.notify=lambda *a,**k:None
        e.api.public=lambda *a,**k:[dict(lotSz='1',minSz='1',tickSz='.01')]
        writes=[]
        def post(path,body):
            self.assertGreater(e.saves,0)
            self.assertEqual(o['partial']['long_wick_cost732']['funding'],4)
            writes.append((path,body))
        e.api.post=post
        e.api.get=lambda *a,**k:[dict(state='filled',accFillSz='10',avgPx='105')]
        snap=dict(ms=NOW,positions=[p])
        PartialExits.partial_close(e,snap,'test',fraction=.5)
        self.assertEqual(o['phase'],'partial_closing')
        self.assertEqual(writes[0][1]['sz'],'10')
        p.update(pos='10',fee='-1.525',fundingFee='4')
        PartialExits.reconcile_partial(e,snap)
        self.assertEqual(o['phase'],'resizing')
        self.assertEqual(o['quantity'],'10')
        self.assertEqual(o['long_wick_partial_cost732']['quantity'],20)
        costs=w.remaining_net(p,o,105)
        self.assertEqual(costs['entry_fee'],.5);self.assertEqual(costs['funding'],2)


class Integration(unittest.TestCase):
    def execute(self,side='short',partial=False,mutate=None):
        o,p=inputs(side,partial);e=FakeEngine(o,p);snap={'ms':NOW,'positions':[p]}
        if mutate:mutate(e,o,p,snap)
        result=guard.management(e,snap,p,o)
        return result,e,o,p,snap
    def test_wick_before_partial_once(self):
        result,e,o,p,snap=self.execute()
        self.assertTrue(result);self.assertEqual(len(e.calls),1);self.assertIn('긴 아랫꼬리',e.calls[0][1])
        self.assertTrue(e.assert_saved);self.assertIn('long_wick_exit732',o)
        self.assertFalse(guard.management(e,snap,p,o));self.assertEqual(len(e.calls),1)
    def test_long_partial_remainder_exit(self):
        _,e,o,_,_=self.execute('long',True)
        self.assertIn('긴 윗꼬리',e.calls[0][1])
    def test_profit_below_twenty_percent_roe_can_exit(self):
        def change(e,o,p,s):
            p['markPx']=99;e.price=99;e.bars[-1][1:5]=[98.9,99.2,97.,99.]
        _,e,o,_,_=self.execute(mutate=change)
        self.assertFalse(o['profit_state714'].get('partial_due721'))
        self.assertIn('긴 아랫꼬리',e.calls[0][1])
    def test_existing_stop_first(self):
        _,e,o,_,_=self.execute(mutate=lambda e,o,p,s:p.update(markPx=111))
        self.assertEqual(e.calls[0][1],'거래소 보호 SL 도달');self.assertNotIn('long_wick_exit732',o)
    def test_pending_protection_first(self):
        def change(e,o,p,s):o.update(target_stop_px=93)
        _,e,o,_,_=self.execute(mutate=change)
        self.assertIn('관측 수익 보호선',e.calls[0][1]);self.assertNotIn('long_wick_exit732',o)
    def test_missing_quote_falls_through_to_existing_partial(self):
        _,e,_,_,_=self.execute(mutate=lambda e,o,p,s:setattr(e.stream,'read',lambda *a:None))
        self.assertEqual(e.calls,[('partial',None)])
    def test_stale_snapshot_quote_wrong_owner_skip_new_exit(self):
        changes=[lambda e,o,p,s:s.update(ms=NOW-15001),
                 lambda e,o,p,s:setattr(e,'qts',NOW-5001),
                 lambda e,o,p,s:p.update(instId='OTHER-USDT-SWAP'),
                 lambda e,o,p,s:p.update(fundingFee=''),
                 lambda e,o,p,s:setattr(e,'price',101)]
        for change in changes:
            _,e,o,_,_=self.execute(mutate=change)
            self.assertNotIn('long_wick_exit732',o);self.assertEqual(e.calls,[('partial',None)])
    def test_no_signal_existing_partial_unchanged(self):
        def change(e,o,p,s):e.bars[-1][3]=90
        _,e,o,_,_=self.execute(mutate=change)
        self.assertEqual(e.calls,[('partial',None)])
    def test_busy_phases_never_submit(self):
        for phase in ('closing','submitted','partial_closing','resizing'):
            result,e,_,_,_=self.execute(mutate=lambda e,o,p,s:o.update(phase=phase))
            self.assertFalse(result);self.assertFalse(e.calls)
    def test_real_close_state_machine_sends_one_close_only(self):
        from okx_engine import Engine
        from okx_core import UnknownOutcome
        for fail in (False,True):
            o,p=inputs('short');o['quantity']='10';e=FakeEngine(o,p)
            e.log=lambda *a:None;e.invalidate=lambda:None;sent=[]
            def post(path,body):
                self.assertEqual(o['phase'],'closing')
                self.assertIn('close_id',o);sent.append((path,body))
                if fail:raise UnknownOutcome('simulated lost response')
            e.api.post=post
            e.close=lambda snap,why:Engine.close(e,snap,why)
            snap=dict(ms=NOW,positions=[p])
            if fail:
                with self.assertRaises(UnknownOutcome):guard.management(e,snap,p,o)
            else:self.assertTrue(guard.management(e,snap,p,o))
            self.assertFalse(guard.management(e,snap,p,o))
            self.assertEqual(len(sent),1)
            self.assertEqual(sent[0][1]['side'],'buy');self.assertEqual(sent[0][1]['posSide'],'short')
            self.assertEqual(sent[0][1]['sz'],'10')


if __name__=='__main__':unittest.main(verbosity=2)
