"""No network; synthetic admission/management plus frozen historical parity."""
import sys, json, pickle, importlib.util, hashlib, tempfile, unittest, copy, threading, subprocess
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'fixture121/host-v29'),str(ROOT/'core121')]
import phone_trend_slot as T
from okx_core import BotError,dec

class Journal:
    def __init__(self,data=None):self.data=data or {};self.saves=0
    def save(self):self.saves+=1

def record(s='TEST-USDT-SWAP',trend=True):
    return dict(symbol=s,direction='long',phase='active',client_id='x'+s,
                stop_px='90',entry_ms=1000000,leverage=5 if trend else 10,
                v4_signal={'trend130':True} if trend else {},holding_rule={},
                ct_val='1',quantity='1',committed_margin='20')

class Logic(unittest.TestCase):
    def test_reservation(self):
        rr=[record(str(i),False) for i in range(3)]
        e=NS(records=lambda:rr,raw_snapshot={'positions':[],'orders':[]})
        self.assertEqual(T.slot_counts(e),(3,0,3))
        with self.assertRaises(BotError):T.require_slot(e,{'symbol':'N'})
        T.require_slot(e,{'symbol':'N','trend130':True})
        rr.append(record('T'));rr[-1]['phase']='submitted'
        with self.assertRaises(BotError):T.require_slot(e,{'symbol':'N','trend130':True})
        rr[:]=[record('T')]
        T.require_slot(e,{'symbol':'N'})
        with self.assertRaises(BotError):T.require_slot(e,{'symbol':'T'})
        with self.assertRaises(BotError):T.require_slot(e,{'symbol':'N','trend130':True})
        rr[:]=[record(str(i),False) for i in range(4)]
        with self.assertRaises(BotError):T.require_slot(e,{'symbol':'N','trend130':True})
        self.assertEqual(len(rr),4)  # No forced liquidation of legacy fourth.
        rr.clear();e.raw_snapshot={'positions':[], 'orders':[{'instId':'M','side':'buy','posSide':'long'}]}
        self.assertEqual(T.slot_counts(e,{'positions':[]}),(1,0,1))
        with self.assertRaises(BotError):T.require_slot(e,{'symbol':'M','trend130':True})

    def test_window(self):
        self.assertFalse(T.in_window(6*T.HOUR-1));self.assertTrue(T.in_window(6*T.HOUR))
        self.assertTrue(T.in_window(T.DAY-1));self.assertFalse(T.in_window(T.DAY))

    def test_rank_not_future_winner(self):
        def row(s,close):
            return dict(symbol=s,live_frames={'1H':[[i*T.HOUR,100,max(100,close),min(100,close),close,1] for i in range(7)]})
        a=row('A',110);b=row('B',105)
        b['live_frames']['1H'][-1][4]=200;b['live_frames']['1H'][-1][2]=200
        self.assertEqual(T.rank_rows([a,b],6*T.HOUR)['symbol'],'A')
        self.assertEqual(T.rank_rows([a,b],7*T.HOUR)['symbol'],'B')
        b['live_frames']['1H'].pop(5)
        with self.assertRaises(ValueError):T.rank_rows([a,b],6*T.HOUR)

    def test_trail_restart_no_half(self):
        now=100000000
        hour=now//T.HOUR*T.HOUR
        h=[[hour-(20-i)*T.HOUR,100,102,98,100,1] for i in range(20)]
        o=record();calls=[]
        e=NS(api=NS(now_ms=lambda:now),journal=Journal(),profit_lock714=threading.Lock(),
             profit_marks714={},chart_job=lambda s:{'1H':h},
             close=lambda *a:calls.append(('close',a[-1])),
             partial_close=lambda *a,**k:self.fail('trend half exit'),
             trail=lambda sn,p,o,target:(calls.append(('trail',target)),o.update(stop_px=str(target))))
        p={'avgPx':'100','markPx':'110'}
        T.observe_trend(e,{},p,o);T.manage(e,{},p,o)
        self.assertEqual(calls[-1],('trail',102.))
        self.assertNotIn('partial_due721',o['profit_state714'])
        o=json.loads(json.dumps(o));p['markPx']='108'
        T.observe_trend(e,{},p,o);T.manage(e,{},p,o)
        self.assertEqual(o['stop_px'],'102.0')
        self.assertEqual(o['profit_state714']['peak_mark'],110.)
        # Six hours doesn't close a trend position. Seventy-two hours does.
        self.assertFalse(any(x[0]=='close' for x in calls))
        now=o['entry_ms']+259200000
        T.manage(e,{},p,o);self.assertEqual(calls[-1][0],'close')

    def test_install_and_leverage_guards(self):
        import okx_channel701 as C,okx_autonomous as A,okx_risk732 as R
        import okx_profit_guard714 as G,okx_dashboard_data as D
        old=(C.candidate,C.check_entry,C.management,A.valid_leverage,R.cap_plan,R.prepare_plan,G.observe,D.dashboard_snapshot)
        T.install(ROOT/'core121')
        self.assertTrue(A.valid_leverage({'trend130':True,'leverage':5,'action':'LONG','symbol':'ALT-USDT-SWAP'},{}))
        self.assertFalse(A.valid_leverage({'trend130':True,'leverage':10,'action':'LONG','symbol':'ALT-USDT-SWAP'},{}))
        self.assertFalse(A.valid_leverage({'trend130':True,'leverage':5,'action':'SHORT','symbol':'ALT-USDT-SWAP'},{}))
        self.assertTrue(A.valid_leverage({'leverage':10,'symbol':'ALT-USDT-SWAP'},{'execution':{'pattern15_only':True}}))
        self.assertTrue(A.valid_leverage({'leverage':20,'symbol':'BTC-USDT-SWAP'},{'execution':{'pattern15_only':True}}))
        o=record();e=NS(api=NS(now_ms=lambda:10000000),journal=Journal())
        G.observe(e,{},dict(avgPx='100',markPx='120'),o)
        self.assertNotIn('partial_due721',o['profit_state714'])
        # Restore so further baseline tests cannot accidentally use the overlay.
        C.candidate,C.check_entry,C.management,A.valid_leverage,R.cap_plan,R.prepare_plan,G.observe,D.dashboard_snapshot=old
        del C._phone_trend130

    def test_subscription_no_churn(self):
        now=999;seen=[]
        e=NS(api=NS(now_ms=lambda:now),journal=Journal({T.STATE:{'pending':{'symbol':'T','valid_from_ms':0,'expires_ms':1000}}}),
             stream=NS(watch=lambda ss:seen.append(set(ss))),log=lambda x:None)
        T.attach(e);e.stream.watch(['A']);e.stream.watch(['A','T'])
        self.assertEqual(seen,[{'A','T'},{'A','T'}])
        now=1001;e.stream.watch(['A']);self.assertEqual(seen[-1],{'A'})

    def test_original_market_order_path_quarter_and_attached_stop(self):
        import okx_channel701 as C,okx_autonomous as A,okx_risk732 as R
        import okx_profit_guard714 as G,okx_dashboard_data as D
        from okx_engine import Engine
        from okx_v5 import RuleEngine
        from okx_free_ai import context
        from okx_core import day_key
        old=(C.candidate,C.check_entry,C.management,A.valid_leverage,R.cap_plan,R.prepare_plan,G.observe,D.dashboard_snapshot)
        T.install(ROOT/'core121')
        now=1706767201000;symbol='ALT-USDT-SWAP'
        proof=dict(confirmation_ms=now//T.STEP*T.STEP-T.STEP,armed_ms=now//T.STEP*T.STEP-T.STEP,
                   reference=100.,atr=2.,structural_stop=96.,hour_atr=4.,dip_level=100.)
        s=T.make_signal(symbol,proof,dict(gain=.1,day=now//T.DAY*T.DAY,hour=now//T.HOUR*T.HOUR),now)
        instrument=dict(instId=symbol,state='live',settleCcy='USDT',ctType='linear',ctValCcy='ALT',
                        instCategory='1',ctVal='1',tickSz='.01',lotSz='.01',minSz='.01',lever='20',maxMktSz='10000')
        ticker=dict(askPx='100',bidPx='99.99',ts=str(now))
        book=dict(ts=str(now),asks=[['100','1000']],bids=[['99.99','1000']])
        snapshot=dict(config={'perm':'read_only,trade'},equity=dec(300),available=dec(300),
                      positions=[],orders=[],ms=now)
        posts=[];journal=Journal(dict(owned=None,day={'date':day_key(now),'ended':False},api_total_spent=0,seen_signals={}))
        def public(path,**kwargs):
            return [instrument] if path.endswith('instruments') else [ticker] if path.endswith('/ticker') else [book]
        def get(path,**kwargs):
            if path.endswith('max-size'):return [dict(maxBuy='1000',maxSell='1000')]
            if path.endswith('leverage-info'):return [dict(instId=symbol,posSide='long',mgnMode='isolated',lever='5')]
            raise AssertionError(path)
        def post(path,body):
            if path.endswith('/order'):
                self.assertEqual(journal.data['owned']['phase'],'submitted')
                self.assertTrue(T.is_owned(journal.data['owned']))
            posts.append((path,body));return [{}]
        e=NS(root=Path('/tmp/trend-test/runtime-q2x'),api=NS(now_ms=lambda:now,public=public,get=get,post=post,taker_fee=lambda i:dec('.0005')),
             journal=journal,enabled=True,entry_cancel=threading.Event(),raw_snapshot=snapshot,
             cfg={'risk':{'initial_margin_fraction':.25,'initial_size_mode':'up_to_third','entry_cash_reserve_usdt':3,'profit_review_roe':.2,'admission732':{'enabled':True}},
                  'selection':{},'execution':{'pattern15_only':True,'rule_channel701':True},'signals':{'band_flow':{'enabled':True}},'liquidity':{'max_book_age_ms':1000}},
             stream=NS(ready=lambda *a:True),records=lambda:[],snapshot=lambda:snapshot,
             algos=lambda **k:([],[]),within_session=lambda:True,is_allowed_instrument=lambda i:True,
             allocation_seed=lambda sn:dec(297),margin_room=lambda sn:dec(300),
             initial_margin_cap=lambda sn:dec('74.25'),risk_snapshot=lambda sn:None,
             blocked_manual_symbols=lambda:set(),log=lambda *a:None,invalidate=lambda:None,
             executing_signal=s,entry_leverage=5,prepared_symbol=symbol,selection_row=lambda symbol:s['selection'])
        e.entry_context=lambda sy,ac:context(e,sy,ac)
        e.prepare_entry_plan=lambda *args:RuleEngine.prepare_entry_plan(e,*args)
        e.pre_submit_check=lambda *args:RuleEngine.pre_submit_check(e,*args)
        e.entry_metadata=lambda *args:RuleEngine.entry_metadata(e,*args)
        try:
            with patch.object(T,'validate_entry',return_value=proof):Engine.entry(e,s,None)
            self.assertEqual([x[0] for x in posts],['/api/v5/account/set-leverage','/api/v5/trade/order'])
            o=journal.data['owned'];order=posts[-1][1]
            self.assertEqual(o['initial_margin_target'],'74.25');self.assertEqual(o['leverage'],5)
            self.assertEqual(dec(o['stop_px']),dec(96));self.assertEqual(order['sz'],'3.71')
            self.assertEqual(order['ordType'],'market');self.assertEqual(order['posSide'],'long')
            self.assertEqual(dec(order['attachAlgoOrds'][0]['slTriggerPx']),dec(96))
            self.assertEqual(order['attachAlgoOrds'][0]['slTriggerPxType'],'mark')
            self.assertTrue(T.is_owned(json.loads(json.dumps(o))))
        finally:
            C.candidate,C.check_entry,C.management,A.valid_leverage,R.cap_plan,R.prepare_plan,G.observe,D.dashboard_snapshot=old
            del C._phone_trend130

    def test_four_predecessors_button_and_boot(self):
        import phone_button_upgrade as upgrade
        raw=(ROOT/'release_1110_repo/android/phone_1_3_1_setup.py').read_bytes()
        for host in (24,25,26,27,28):
            spec=importlib.util.spec_from_file_location('up'+str(host),ROOT/f'fixture121/host-v{host}/phone_update.py')
            m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            man=dict(format='okx-phone-release-1',version=29,display_version='1.3.1',from_versions=[24,25,26,27,28],
                     installer='android/phone_1_3_1_setup.py',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),commit='a'*40,notes='test')
            u=m.PhoneUpdater('/tmp',NS(complete_control=lambda _:None))
            with patch.object(m,'download',side_effect=[json.dumps(man).encode(),raw]):u.check(dict(request_id='fixture',owner='fixture'))
            self.assertEqual(u.state['target_version'],'1.3.1');self.assertEqual(u.candidate['raw'],raw)
            with tempfile.TemporaryDirectory() as tmp:
                home=Path(tmp);b=home/'.termux/boot/40-okx-home';b.parent.mkdir(parents=True)
                b.write_text(str(ROOT/f'fixture121/host-v{host}/phone_service.py'))
                with patch.object(Path,'home',return_value=home):
                    self.assertEqual(upgrade.verify_old(ROOT/'fixture121'),ROOT/f'fixture121/host-v{host}')

    def test_original_rules_and_compute_modes_unchanged(self):
        a=ROOT/'fixture121/host-v27';b=ROOT/'fixture121/host-v29'
        for name in ('phone_signal_cache.py','phone_parallel.py','phone_pullback_size.py','phone_public_ws.py','phone_handover.py'):
            self.assertEqual((a/name).read_bytes(),(b/name).read_bytes())
        import okx_two_wick732 as w
        p=dict(action='LONG',route721='trend_pullback')
        self.assertEqual(w.combine(p,None),(dict(p,entry_source732='baseline_only'),'baseline_only'))
        self.assertEqual(w.combine(p,dict(action='SHORT')),(None,'conflict'))

    def test_production_patch_order(self):
        script='''import sys,tempfile
from pathlib import Path
sys.path[:0]=sys.argv[1:3]
from phone_performance import install_before_engine
from phone_trend_slot import install
with tempfile.TemporaryDirectory() as t:
 timer=install_before_engine(Path(t))
 install(Path(sys.argv[2]))
 import okx_channel701 as c
 assert c._phone_trend130
 assert timer.optimization_enabled
print('production performance/cache/parallel then trend hooks: OK')
'''
        z=subprocess.run([sys.executable,'-c',script,str(ROOT/'fixture121/host-v29'),str(ROOT/'core121')],capture_output=True,text=True)
        self.assertEqual(z.returncode,0,z.stdout+z.stderr)

    def test_real_candles_admission_expiry_stop_touch_restart(self):
        import numpy as np
        data=pickle.load((ROOT/'top3_trend_5x/bars15.pickle').open('rb'))
        signals=json.loads((ROOT/'top1_15_entry3/signals.json').read_text())['dip_only']
        symbol,nexts=next(iter(signals.items()));ts,hit=next(iter(nexts.items()))
        t=int(ts);v=hit['trend'];z=data[symbol]
        j=int(np.searchsorted(z['ts'],t));k=int(np.searchsorted(z['ht'],t-T.HOUR,side='right'))
        b=z['b'][max(0,j-299):j];h=z['h'][max(0,k-100):k]
        okx=symbol.removesuffix('USDT')+'-USDT-SWAP'
        i=dict(instId=okx,state='live',settleCcy='USDT',ctType='linear',ctValCcy=okx.split('-')[0],instCategory='1')
        now=t+1000
        row=dict(symbol=okx,instrument=i,live_frames={'15m':b,'1H':h})
        result=dict(rows=[row],whole_market=True,universe=1,ms=now)
        state=dict(last=t-T.STEP,arm=dict(symbol=okx,t=v['armed_ms'],level=v['dip_level']),pending=None)
        active=[]
        def public(path,**kw):
            bars=(b+active) if kw['bar']=='15m' else h
            return [[str(int(r[0]))]+[str(x) for x in r[1:]]+['0','0','1'] for r in bars]
        e=NS(root=Path('/tmp/trend-test/runtime-q2x'),api=NS(now_ms=lambda:now,public=public),cfg={'selection':{}},
             records=lambda:[],raw_snapshot={},universe=NS(read=lambda:(result,None)),journal=Journal({T.STATE:state}))
        s=T.scan(e);self.assertIsNotNone(s)
        self.assertAlmostEqual(s['stop'],v['structural_stop'])
        saves=e.journal.saves
        self.assertEqual(T.scan(e)['signal_id'],s['signal_id']);self.assertEqual(e.journal.saves,saves)
        e.journal=Journal(json.loads(json.dumps(e.journal.data)))
        self.assertEqual(T.scan(e)['signal_id'],s['signal_id'])
        T.validate_entry(e,s,v['reference'])
        active.append([t,v['reference'],v['reference'],s['stop'],v['reference'],1])
        with self.assertRaisesRegex(BotError,'초기SL'):T.validate_entry(e,s,v['reference'])
        active.clear();now=t+90001
        with self.assertRaisesRegex(BotError,'만료'):T.validate_entry(e,s,v['reference'])
        self.assertIsNone(T.scan(e))
        # Intrabar touch alone is not a completed-close dip.
        altered=copy.deepcopy(b);altered[-1][4]=v['dip_level']+v['atr']
        arm,p=T.advance(dict(t=v['armed_ms'],level=v['dip_level']),altered,h,h,t,True,True)
        self.assertIsNone(p)

    def test_installer_four_predecessors_tamper_and_stage(self):
        p=ROOT/'release_1110_repo/android/phone_1_3_1_setup.py'
        spec=importlib.util.spec_from_file_location('installer130',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        for v in (24,25,26,27,28):
            old={p.name:p.read_bytes() for p in (ROOT/f'fixture121/host-v{v}').iterdir() if p.is_file()}
            files=m.candidate(old)
            self.assertIn('phone_trend_slot.py',files)
            bad=dict(old);bad['phone_host.py']+=b'\n# tamper'
            with self.assertRaises(ValueError):m.candidate(bad)
            with tempfile.TemporaryDirectory() as tmp:
                dest=m.stage(Path(tmp),files)
                self.assertEqual(dest.name,'host-v29')
                self.assertEqual(m.stage(Path(tmp),files),dest)
                (dest/'phone_host.py').write_text('modified')
                with self.assertRaises(ValueError):m.stage(Path(tmp),files)

def historical_parity():
    import numpy as np
    data=pickle.load((ROOT/'top3_trend_5x/bars15.pickle').open('rb'))
    ranks={int(k):v for k,v in json.loads((ROOT/'top1_15kst/rankings.json').read_text()).items()}
    expected=json.loads((ROOT/'top1_15_entry3/signals.json').read_text())['dip_only']
    got={};count=0
    for symbol,z in data.items():
        arm=None;out={}
        for t in range(1706745600000,1711929600000,T.STEP):
            eligible=bool(ranks.get(t//T.HOUR*T.HOUR) and ranks[t//T.HOUR*T.HOUR][0]['symbol']==symbol)
            if not eligible or t not in z['atr']:arm=None;continue
            j=int(np.searchsorted(z['ts'],t));k=int(np.searchsorted(z['ht'],t-T.HOUR,side='right'))
            pk=int(np.searchsorted(z['ht'],t-T.STEP-T.HOUR,side='right'))
            b=z['b'][max(0,j-300):j];h=z['h'][max(0,k-100):k];ph=z['h'][max(0,pk-100):pk]
            prev=bool(ranks.get((t-T.STEP)//T.HOUR*T.HOUR) and ranks[(t-T.STEP)//T.HOUR*T.HOUR][0]['symbol']==symbol)
            arm,p=T.advance(arm,b,h,ph,t,eligible,prev)
            if p:
                out[str(t)]=p;count+=1
                ref=expected[symbol][str(t)]['trend']
                for key in ('reference','atr','structural_stop','confirmation_ms','armed_ms','dip_level'):
                    assert abs(p[key]-ref[key])<1e-10,(symbol,t,key,p[key],ref[key])
        if out:got[symbol]=out
    assert {s:set(v) for s,v in got.items()}=={s:set(v) for s,v in expected.items()}
    return count

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Logic)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():sys.exit(1)
    count=historical_parity()
    report=dict(unit_tests=result.testsRun,historical_signal_parity=count,
                reused_data='Binance 2024-02~03; prior research dip_only',
                live_orders=False,full_3plus1_portfolio_profitability_tested=False)
    (Path(__file__).parent/'test_audit.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
