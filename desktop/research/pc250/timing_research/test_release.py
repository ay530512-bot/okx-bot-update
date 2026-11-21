"""Offline integration regressions for PC 2.5; never submits exchange orders."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch

P=(Path.cwd()/'OKX_PC_PACKAGE').resolve()
sys.path[:0]=[str(P),str(P/'core'),str(P/'runtime')]
import pc_forward as f
import pc_monthly as m
import pc_scalp as sc
import pc_timing as tim
import pc_update as updater
import okx_risk732 as risk
from okx_core import BotError,dec

M=60000;DAY=1440*M;NOW=1795228200000;K='scalp_higher'
class FakeAPI:
    def __init__(self,now=NOW):self.now=now;self.calls=[];self.trade=[];self.mark=[]
    def now_ms(self):return self.now
    def public(self,path,**params):
        self.calls.append(path)
        if path.endswith('funding-rate-history'):return [{'fundingTime':str(self.now-3*DAY),'realizedRate':'0'}]
        if path.endswith('/ticker'):return [dict(ts=str(self.now),bidPx='99.99',askPx='100')]
        source=self.mark if 'mark-price' in path else self.trade
        return [r for r in reversed(source) if int(r[0])<int(params['after'])][:100]

def engine(api):return Obj(api=api,stream=Obj(read=lambda *a:None))
def sample(ts):return dict(side=1,symbol='BREV-USDT-SWAP',price=100,stop=98,tick=.01,entry_ms=ts,minutes=120)
def signal(now):return dict(monthly208=K,symbol='BREV-USDT-SWAP',action='LONG',valid_from_ms=now,expires_ms=now+M-1,entry_reference=100,atr=1,stop=98,tick250=.01,signal_id='same',holding_rule={'max_hold_seconds':tim.policies()[K]['minutes']*60})
def hist(ts,n=20,ret=.35):return [dict(entry_ms=ts-(n-i)*DAY,exit_ms=ts-(n-i)*DAY+M,net_r=ret,symbol='A') for i in range(n)]

def candles(o,h,l,c,vol=100):return [0,o,h,l,c,vol]

class Release(unittest.TestCase):
    def test_validate_update_and_assets(self):
        import phone_mobile
        html=phone_mobile.mobile_module(P/'core').asset('index.html').decode()
        self.assertEqual(html.count('data-forward-rule='),13);self.assertIn('PC 2.5.0',html)
        self.assertEqual(set(m.RULES),set(tim.policies()))
        result=updater.verify_package(P);self.assertEqual(result['revision'],20500)
        for fn,sha in json.loads((P/'runtime/phone_sources.json').read_text())['files'].items():self.assertEqual(hashlib.sha256((P/'core'/fn).read_bytes()).hexdigest(),sha)

    def test_wicks_stops_and_filters(self):
        bars=[candles(101,102,100,101) for _ in range(99)]
        bars[-1]=candles(100,103,99,102.5,200)
        a=tim.evidence('reversal',bars,1,.01,2);self.assertLess(a['stop'],99);self.assertTrue(tim.passes('volume',a))
        bars[-1]=candles(102,104,100,100.5,200)
        b=tim.evidence('reversal',bars,-1,.01,2);self.assertGreater(b['stop'],104);self.assertTrue(tim.passes('reclaim',b))
        bars[-1]=candles(100,121,99,119);self.assertIsNone(tim.evidence('reversal',bars,1,.01,2))
        self.assertEqual(tim.round_stop(99.996,.01,1),99.99);self.assertEqual(tim.round_stop(101.001,.01,-1),101.01)

    def test_shadow_history_and_restart(self):
        api=FakeAPI(); e=engine(api);now=api.now;sig=signal(now)
        with tempfile.TemporaryDirectory() as folder:
            w=f.Watcher(e,folder);self.assertFalse(w.ready(K,now));w.record(sig,now);w.record(sig,now)
            bucket=w.data['rules'][K];self.assertEqual(bucket['daily'],1);self.assertFalse(w.allows(sig,now))
            bucket['history']=hist(now);w.save();self.assertTrue(w.allows(sig,now));self.assertFalse(w.allows(dict(sig,signal_id='other'),now));self.assertFalse(f.qualifies(hist(now,19),now))
            self.assertFalse(f.qualifies(hist(now,20,-1),now));self.assertFalse(f.qualifies(hist(now-61*DAY),now));self.assertFalse(w.ready(K,now+2*DAY))
            w.close();two=f.Watcher(e,folder);self.assertTrue(two.allows(sig,now));two.close()
            two.path.write_text('bad json');bad=f.Watcher(e,folder);self.assertFalse(bad.ready(K,now));bad.close()
        self.assertFalse(any('/trade/' in path for path in api.calls))

    def test_completed_mark_funding_and_deadline(self):
        first=NOW//M*M;api=FakeAPI(first+122*M)
        for t in range(first,first+121*M,M):
            api.trade.append([str(t),'100','104','98.5','103','1','1','1','1'])
            api.mark.append([str(t),'100','101','99','100','1'])
        s=sample(first);out=f.settle(api,s);self.assertEqual(out['reason'],'time');self.assertLess(out['net_r'],0)
        # A mark-price stop can fire without the spot/last candle intersecting that stop.
        api.mark[2][3]='97';out=f.settle(api,s);self.assertEqual(out['reason'],'stop');self.assertEqual(out['exit_ms'],first+3*M)
        api.mark.pop(72);self.assertRaises(ValueError,f.settle,api,s)

    def test_budget_before_submission(self):
        cfg={'risk':{'max_position_loss_fraction':.005,'max_open_stop_loss_fraction':.02,'entry_cash_reserve_usdt':3}}
        e=Obj(cfg=cfg,records=lambda:[],allocation_seed=lambda snap:dec(147),margin_room=lambda snap:dec(147))
        snap=dict(equity='150',available='150',positions=[]);instrument=dict(tickSz='.01',lotSz='.01',ctVal='.1',minSz='.01',maxMktSz='100000')
        s={'leverage':10,'stop':99,'monthly208':K,'pc211':True,'pc250':True};plan={'buy':'100','sell':'100'}
        a=risk.cap_plan(e,plan,instrument,s,'long',snap,'.0005');b=risk.cap_plan(e,plan,instrument,dict(s,stop=96),'long',snap,'.0005');self.assertLess(dec(b['quantity']),dec(a['quantity']));self.assertLessEqual(dec(b['estimated_loss']),dec('.735'))
        s2=dict(s,stop=105);short=risk.cap_plan(e,plan,instrument,s2,'short',snap,'.0005');self.assertLessEqual(dec(short['estimated_loss']),dec('.735'))
        with patch('okx_risk732.portfolio',return_value=(dec('2.90'),dec(100))):limited=risk.cap_plan(e,plan,instrument,s,'long',snap,'.0005');self.assertLessEqual(dec(limited['estimated_loss']),dec('.04'))
        with patch('okx_risk732.portfolio',return_value=(dec(4),dec(100))):self.assertRaises(BotError,risk.cap_plan,e,plan,instrument,s,'long',snap,'.0005')
        old=risk.cap_plan(e,plan,instrument,dict(s,pc250=False),'long',snap,'.0005');self.assertEqual(old['initial_size_mode'],'fixed_tenth211');self.assertEqual(dec(old['initial_margin_target']),dec('14.7'))

    def test_held_exits_and_no_widening(self):
        now=NOW;ev=[];e=Obj(api=FakeAPI(now),close=lambda _,why:ev.append(('exit',why)),trail=lambda snap,pos,order,level:ev.append(('trail',level)))
        for side in (1,-1):
            k='late_reversal'; sig=dict(monthly208=k,pc211=True,pc250=True,action='LONG' if side==1 else 'SHORT',stop=100-2*side,holding_rule={'max_hold_seconds':60*60})
            order=dict(v4_signal=sig,entry_ms=now,stop_px=sig['stop'],direction='long' if side==1 else 'short');pos=dict(avgPx=100,markPx=100+4*side)
            self.assertTrue(m.manage(e,{},pos,order));self.assertEqual(ev.pop(),('trail',100+2*side))
            order['stop_px']=100+2*side;pos['markPx']=100+3*side;self.assertFalse(m.manage(e,{},pos,order));self.assertFalse(ev)
            e.api.now=now+60*M;self.assertTrue(m.manage(e,{},pos,order));self.assertIn('60분',ev.pop()[1]);e.api.now=now
        legacy=dict(monthly208='scalp_higher',pc211=True,action='LONG',stop=98);order=dict(v4_signal=legacy,stop_px=98,entry_ms=now-30*M,direction='long');self.assertTrue(m.manage(e,{},dict(avgPx=100,markPx=100),order));self.assertIn('30분',ev.pop()[1])

if __name__=='__main__':unittest.main()
