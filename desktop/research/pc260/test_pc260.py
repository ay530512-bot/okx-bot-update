"""Offline release regressions. All exchange endpoints below are in-memory fakes."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch

P=(Path.cwd()/'OKX_PC_PACKAGE').resolve()
sys.path[:0]=[str(P),str(P/'runtime'),str(P/'core')]
import pc_sizing as size
import pc_timing as timing
import okx_risk732 as policy
from okx_core import BotError, UnknownOutcome,dec
from okx_engine import Engine,day_key
from okx_portfolio import PortfolioEngine
from okx_v5 import RuleEngine
from okx_search_capacity import occupied,limit
from phone_trend_slot import require_slot

NOW=1795228200000

def noop(*args,**kwargs):pass

def signal(symbol='BONK-USDT-SWAP', side=1, score=3, dist=.0007):
    stop=100*(1-side*dist)
    ev=dict(rv=1.7,slope=1 if score>=2 else -1,stretch=.5,rsi_direction=2 if score==3 else -1,location=.8,stop=stop)
    level=size.leverage_for(ev,100,20.)
    return dict(symbol=symbol,action='LONG' if side==1 else 'SHORT',pc211=True,pc250=True,pc260=True,
                rule_channel701=True,pattern15=True,strategy='band_flow',monthly208='test'+symbol,
                signal_id=symbol,leverage=level,stop=stop,indicator_limit=20.,entry_reference=100.,
                decision_record={'volume_wick_proof':{'timing':ev}})


class Exchange:
    def __init__(self):self.writes=[];self.failure=False
    def now_ms(self):return NOW
    def public(self,path,**arg):
        if path.endswith('/instruments'):
            sym=arg['instId']
            return [dict(instId=sym,instCategory='1',ctValCcy=sym.split('-')[0],state='live',settleCcy='USDT',
                         ctType='linear',lever='20',tickSz='.001',lotSz='.001',ctVal='1',minSz='.001',maxMktSz='10000')]
        if path.endswith('/ticker'):return [dict(bidPx='99.999',askPx='100',ts=str(NOW))]
        if path.endswith('/books'):return [dict(bids=[['99.999','5000']],asks=[['100','5000']],ts=str(NOW))]
        raise AssertionError(path)
    def get(self,path,**arg):
        if path.endswith('/max-size'):return [dict(maxBuy='10000',maxSell='10000')]
        if path.endswith('/leverage-info'):
            inst=self.writes[-1][1]
            return [dict(inst,lever='10' if self.failure else inst['lever'])]
        raise AssertionError(path)
    def post(self,path,body):
        assert path in ('/api/v5/account/set-leverage','/api/v5/trade/order')
        self.writes.append((path,dict(body)))
        return [{'ordId':'OFFLINE'}]
    def taker_fee(self,instrument):return dec('.0005')


class Harness:
    allocation_seed=PortfolioEngine.allocation_seed
    margin_room=RuleEngine.margin_room
    def __init__(self):
        self.cfg=dict(risk=dict(max_position_loss_fraction=.005,max_open_stop_loss_fraction=.02,admission732={'enabled':True}),
                      liquidity={'max_book_age_ms':3000},execution={'rule_channel701':True,'ai_confirmation':False},
                      signals={'band_flow':{'enabled':True}},selection={})
        size.configure(self.cfg)
        self.api=Exchange();self.persisted=[];self.raw_snapshot=None
        self.journal=Obj(data=dict(owned=None,day=dict(date=day_key(NOW),ended=False),api_total_spent=0),save=noop)
        self.enabled=True;self.recovering=False;self.entry_cancel=Event();self.stop_event=Event();self.remaining=[]
        self.stream=Obj(ready=lambda *a:True)
        self.free=dec(150)
    def snapshot(self):
        self.raw_snapshot=dict(ms=NOW,equity=dec(150),available=self.free,positions=[],orders=[],config={'perm':'trade'})
        return self.raw_snapshot
    def records(self):return self.persisted
    def can_open_position(self):return occupied(self)<limit(self)
    def entry_context(self,*a):return {'_v4':self.prepared_signal}
    def within_session(self):return True
    def algos(self,**kw):return [],[]
    def is_allowed_instrument(self,i):return True
    def blocked_manual_symbols(self):return set()
    def selection_row(self,s):return {}
    log=invalidate=risk_snapshot=noop
    def entry_metadata(self,plan,frames):
        return dict(ct_val=plan['_ct'],original_risk_budget=plan['_initial_risk_budget'],estimated_loss=plan['estimated_loss'],
                    cost_rate=plan['cost_rate'],entry_fee_reserve=plan['entry_fee_reserve'],initial_margin_target=plan['initial_margin_target'])
    def prepare_entry_plan(self,*args):return policy.prepare_plan(self,*args)
    def pre_submit_check(self,*args):return policy.submit_check(self,*args)
    def initial_margin_cap(self,snap):return self.margin_room(snap)
    def candidate_decision(self):
        return next((s for s in self.remaining if s['signal_id'] not in self.pc_batch_seen),None)
    def send_simulated(self,s):
        self.prepared_signal=s
        self.journal.data['owned']=None
        require_slot(self,s,self.snapshot())
        Engine.entry(self,s,None)
        order=self.journal.data['owned']
        if order:self.persisted.append(order)


class Release(unittest.TestCase):
    def test_validate_tiers_and_downgrade(self):
        self.assertEqual([signal(score=n)['leverage'] for n in (1,2,3)],[3,4,5])
        self.assertEqual(signal(dist=.002)['leverage'],3)
        self.assertEqual(signal(dist=.004)['leverage'],0)
        self.assertFalse(size.valid(dict(signal(),leverage=10)))
        self.assertTrue(size.valid(dict(click716=True,leverage=5)))
        self.assertFalse(size.valid(dict(click716=True,leverage=4)))
    def test_first_extreme_both_directions(self):
        b=[[i,100.,100.1,99.9,100.,100.] for i in range(99)]
        b[-5]=[94,99.95,100.04,99.76,99.97,100.]
        b[-1]=[98,99.94,100.09,99.80,100.04,240.]
        e=timing.evidence('scalp_double',b,1,.001,.25)
        self.assertEqual((e['first_wick'],e['second_wick']),(99.76,99.8))
        self.assertEqual(e['stop'],99.722)
        flip=[[r[0],200-r[1],200-r[3],200-r[2],200-r[4],r[5]] for r in b]
        e=timing.evidence('two_wick',flip,-1,.001,.25)
        self.assertAlmostEqual(e['first_wick'],100.24);self.assertEqual(e['stop'],100.278)
        flip[-1][2]=100.25
        self.assertIsNone(timing.evidence('two_wick',flip,-1,.001,.25))
    def test_three_submissions_one_sweep_fee_and_fourth(self):
        e=Harness()
        sigs=[signal(name+'-USDT-SWAP',1 if n!=1 else -1,score=n+1) for n,name in enumerate(['BONK','BREV','INIT'])]
        e.remaining=sigs+[signal('XRP-USDT-SWAP')]
        with patch('okx_pattern15.check_entry',side_effect=lambda eng,s,px:require_slot(eng,s)):
            size.submit_batch(e,sigs[0],e.send_simulated)
        self.assertEqual(occupied(e),3)
        self.assertEqual([p['initial_margin_target'] for p in e.records()],['49']*3)
        self.assertEqual([b['lever'] for path,b in e.api.writes if path.endswith('/set-leverage')],['3','4','5'])
        actual=[b for path,b in e.api.writes if path.endswith('/order')]
        self.assertEqual(len(actual),3)
        self.assertEqual([b['posSide'] for b in actual],['long','short','long'])
        for s,b in zip(sigs,actual):
            triggered=float(b['attachAlgoOrds'][0]['slTriggerPx'])
            outward=(s['stop']-triggered)*(1 if b['posSide']=='long' else -1)
            self.assertGreaterEqual(outward,-1e-12);self.assertLessEqual(outward,.001000001)
            self.assertEqual(b['attachAlgoOrds'][0]['slTriggerPxType'],'mark')
        used=sum(dec(o['committed_margin'])+dec(o['entry_fee_reserve']) for o in e.records())
        self.assertGreaterEqual(dec(150)-used,3);self.assertLess(dec(150)-used,dec('3.2'))
        with self.assertRaises(BotError):require_slot(e,e.remaining[3])
    def test_manual_pending_and_protection(self):
        e=Harness();e.persisted=[dict(symbol='A',direction='long')]
        e.raw_snapshot=dict(positions=[dict(instId='A',posSide='long',pos=1)],
            manual_positions=[dict(instId='B',posSide='short',pos=2)],orders=[
                dict(instId='A',posSide='long',side='buy'),
                dict(instId='A',posSide='long',side='sell'), dict(instId='Z',reduceOnly='true')])
        self.assertEqual(occupied(e),2)
        e.manual_algo_rows=[dict(instId='C',posSide='long',side='buy',ordType='trigger',closeFraction='0')]
        self.assertEqual(occupied(e),3)
        with self.assertRaises(BotError):require_slot(e,signal())
        e.persisted.append(dict(symbol='D',direction='short'));self.assertFalse(e.can_open_position())
        self.assertEqual(len(e.records()),2)
    def test_manual_order_and_bad_exchange_leverage(self):
        e=Harness();s=dict(signal(),click716=True,leverage=5);e.api.failure=True
        with patch('okx_pattern15.check_entry',return_value={}):
            with self.assertRaises(BotError):e.send_simulated(s)
        self.assertFalse(any(path.endswith('/order') for path,_ in e.api.writes))
        e.api.failure=False
        with patch('okx_pattern15.check_entry',return_value={}):e.send_simulated(s)
        self.assertEqual(e.records()[0]['initial_margin_target'],'49')
    def test_uncertain_write_stops_batch(self):
        e=Harness();s=signal()
        def fail(_):raise UnknownOutcome('ambiguous fake write')
        with self.assertRaises(UnknownOutcome):size.submit_batch(e,s,fail)
        self.assertFalse(e.pc_batch_seen)
    def test_deployed_hooks(self):
        import pc_update,phone_mobile,pc_run
        self.assertEqual(pc_update.verify_package(P)['revision'],20600)
        pc_run.activate_package()
        from phone_pullback_size import install
        from phone_performance import install_before_engine
        import phone_trend_slot,phone_risk_lifecycle,phone_manual_reduction,pc_wick_failure
        with TemporaryDirectory() as work:
            install(P/'core');install_before_engine(Path(work));phone_trend_slot.install(P/'core')
            phone_manual_reduction.install(P/'core');phone_risk_lifecycle.install(P/'core');pc_wick_failure.install()
            from okx_autonomous import valid_leverage
            self.assertTrue(valid_leverage(signal(),Harness().cfg))
            self.assertFalse(valid_leverage(dict(signal(),leverage=10),Harness().cfg))
        html=phone_mobile.mobile_module(P/'core').asset('index.html').decode()
        self.assertIn('PC 2.6.0',html);self.assertIn('전체 최대 3포지션',html);self.assertEqual(html.count('data-forward-rule='),13)

if __name__=='__main__':unittest.main()
