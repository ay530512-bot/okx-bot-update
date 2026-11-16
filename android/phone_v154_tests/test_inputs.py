"""Synthetic inputs isolate collection ordering; no live fills or profit claims."""
import copy,importlib.util,json,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
D=Path(__file__).resolve().parents[1];HOST=D/'phone_v154';CORE=D.parent.parent/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
import phone_trend_slot as new
spec=importlib.util.spec_from_file_location('rank_old141',D.parent.parent/'regression_hosts/phone_v141/phone_trend_slot.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
T=1794829500000 # 2026-11-16 20:45 KST
A,B='TESTA-USDT-SWAP','TESTB-USDT-SWAP'
def bars(step,slope,n=70):
 end=T//step*step
 return [[end-(n-i)*step,1+i*slope,1+i*slope+.01,1+i*slope-.01,1+i*slope+.002,100] for i in range(n)]
def engine():
 rows=[]
 for s,slope in [(A,.005),(B,.001)]:
  b=bars(900000,.002);b[-1][4]=b[-1][1]-.005
  rows.append(dict(symbol=s,instrument=dict(instId=s,state='live',settleCcy='USDT',ctType='linear',ctValCcy=s.split('-')[0],instCategory='1',lever='100'),
      live_frames={'15m':b,'1H':bars(3600000,slope),'4H':[]},observed_ms=T+1000))
 result=dict(rows=rows,whole_market=True,universe=2,ms=T+1000,filter_counts={'data_error':0})
 cache={(r['symbol'],f):(time.monotonic(),tuple(tuple(b) for b in bs)) for r in rows for f,bs in r['live_frames'].items()}
 u=NS(lock=threading.RLock(),result=result,full_market=NS(instruments={r['symbol']:r['instrument'] for r in rows},band_cache=cache),search_paused=threading.Event())
 u.read=lambda:(u.result,None)
 e=NS(universe=u,cfg={'selection':{}},api=NS(now_ms=lambda:T+2000),journal=NS(data={},save=lambda:None),root='/tmp/no_live/runtime')
 e.journal.data[new.STATE]={'last':T-900000,'arm':{'t':T-900000,'symbol':A,'level':rows[0]['live_frames']['15m'][-1][4]+.01},'pending':None}
 return e
class Tests(unittest.TestCase):
 def test_real_collector_unrelated4h_wait_does_not_block_ready_trend_inputs(self):
  import okx_band_flow as flow
  e=engine();u=e.universe;m=u.full_market;m.owner=u
  u.cfg=dict(e.cfg,execution={'rule_channel701':True});u.settings={'TRADING_EXCHANGE':'okx'}
  u.stop_event=threading.Event();u.throttle=lambda **kw:None
  m.market=lambda:dict(instruments=m.instruments,quotes={})
  m.band_cache[(B,'4H')]=(time.monotonic(),tuple(tuple(b) for b in bars(14400000,.001)))
  m.band_cache.pop((A,'4H'));u.result=None
  entered=threading.Event();release=threading.Event();calls=[];results=[]
  class API:
   def __init__(self,settings):self.session=NS(close=lambda:None)
   def now_ms(self):return T+2000
   def public(self,path,**kw):
    calls.append((path,kw));self.assert_public=path=='/api/v5/market/candles'
    if kw['instId']==A and kw['bar']=='4H':entered.set();release.wait(3)
    return []
  with patch('okx_core.OKX',API),patch('time.time',return_value=(T+2000)/1000):
   worker=threading.Thread(target=lambda:results.append(flow.scan(m)));worker.start()
   try:
    self.assertTrue(entered.wait(1));deadline=time.monotonic()+1
    while u.result is None and time.monotonic()<deadline:time.sleep(.005)
    self.assertIsNotNone(u.result);self.assertEqual(len(u.result['rows']),1)
    with self.assertRaisesRegex(ValueError,'전체 종목 자료 완성 대기'):old.snapshot_ranks(e,T)
    self.assertEqual(new.snapshot_ranks(e,T)[1]['symbol'],A)
    self.assertIsNotNone(new.scan(e));self.assertTrue(worker.is_alive())
    self.assertEqual(len(calls),1);self.assertEqual(calls[0][1]['bar'],'4H')
   finally:release.set();worker.join(3)
  self.assertEqual(len(results[0]['rows']),2)
 def test_partial_scan_reproduces_old_wait_and_new_same_signal_as_complete(self):
  ref=engine();expected=old.scan(ref);self.assertIsNotNone(expected)
  e=engine();e.universe.result=dict(e.universe.result,rows=e.universe.result['rows'][1:])
  self.assertIsNone(old.scan(e));self.assertEqual(e.phone_trend_status,'전체 종목 자료 완성 대기')
  got=new.scan(e);self.assertEqual(got,expected)
  self.assertEqual(e.phone_trend_inputs['hourly_ready'],2)
  self.assertEqual(e.phone_trend_inputs['scan_rows'],1)
  (Path(__file__).parent/'input_reproduction.json').write_text(json.dumps({'type':'synthetic confirmed candle input ordering, not actual missed-trade replay','all_eligible_hourly_available':True,'leader_latest15m_available':True,'published_scan_rows':1,'universe':2,'old141':'whole scan incomplete: no signal','new142':'same signal as old complete-data reference','unchanged_signal_fields':True,'live_orders':0},indent=2)+'\n')
 def test_complete_ranks_identical_for_every_quarter_in_same_hour(self):
  for shift in (0,900000,1800000):
   e=engine();e.api.now_ms=lambda:T-shift+2000;e.universe.result['ms']=T-shift+1000
   a=old.snapshot_ranks(e,T-shift)[1:];b=new.snapshot_ranks(e,T-shift)[1:]
   self.assertEqual(a,b)
 def test_every_eligible_symbol_hourly_required(self):
  e=engine();e.universe.full_market.band_cache.pop((B,'1H'))
  with self.assertRaisesRegex(ValueError,'완료1시간봉 대기'):new.snapshot_ranks(e,T)
  self.assertEqual(e.phone_trend_inputs['missing_hourly'],[B]);self.assertEqual(e.phone_trend_inputs['hourly_ready'],1)
 def test_other15m_and_all4h_do_not_block_ranking(self):
  e=engine();base=old.snapshot_ranks(e,T)[1:]
  for k in list(e.universe.full_market.band_cache):
   if k[1]=='4H' or k==(B,'15m'):e.universe.full_market.band_cache.pop(k)
  self.assertEqual(new.snapshot_ranks(e,T)[1:],base);self.assertIsNotNone(new.scan(e))
 def test_leader15m_still_required(self):
  e=engine();e.universe.full_market.band_cache.pop((A,'15m'))
  self.assertIsNone(new.scan(e));self.assertEqual(e.phone_trend_status,'최신 확정봉 대기')
 def test_stale_hour_rejected_at_new_hour(self):
  e=engine();e.api.now_ms=lambda:T+900000+2000;e.universe.result['ms']=T+900000+1000
  self.assertIsNone(new.scan(e));self.assertIn('완료1시간봉 대기',e.phone_trend_status)
 def test_invalid_hourly_values_are_not_admitted(self):
  e=engine();at,bs=e.universe.full_market.band_cache[(B,'1H')];bad=[list(b) for b in bs];bad[-2][4]=999
  e.universe.full_market.band_cache[(B,'1H')]=(at,bad)
  with self.assertRaises(ValueError):new.snapshot_ranks(e,T)
 def test_missing09_reference_is_not_partial_rank(self):
  e=engine();at,bs=e.universe.full_market.band_cache[(B,'1H')]
  e.universe.full_market.band_cache[(B,'1H')]=(at,bs[-2:])
  with self.assertRaises(ValueError):new.snapshot_ranks(e,T)
 def test_snapshot_age_and_future_still_block(self):
  for stamp in (T-120001,T+2001):
   e=engine();e.universe.result['ms']=stamp
   with self.assertRaisesRegex(ValueError,'갱신 대기'):new.snapshot_ranks(e,T)
 def test_universe_change_and_pause_block(self):
  e=engine();e.universe.full_market.instruments.pop(B)
  with self.assertRaisesRegex(ValueError,'목록 갱신'):new.snapshot_ranks(e,T)
  e=engine();e.universe.search_paused.set()
  with self.assertRaisesRegex(ValueError,'수집 중지'):new.snapshot_ranks(e,T)
 def test_expiry_remains90_seconds(self):
  e=engine();e.api.now_ms=lambda:T+90001;e.universe.result['ms']=T+90001
  self.assertIsNone(new.scan(e));self.assertIn('90초 만료',e.phone_trend_status)
 def test_bad_hourly_does_not_count_omitted_symbol_as_nonpositive(self):
  e=engine();e.universe.full_market.band_cache.pop((A,'1H'))
  with self.assertRaises(ValueError):new.snapshot_ranks(e,T)
 def test_core_predicates_and_financial_management_identical(self):
  import ast
  def funcs(file):return {n.name:ast.dump(n) for n in ast.parse(file.read_text()).body if isinstance(n,ast.FunctionDef)}
  a,b=funcs(D.parent.parent/'regression_hosts/phone_v141/phone_trend_slot.py'),funcs(HOST/'phone_trend_slot.py')
  for name in a:
   if name not in ('scan','snapshot_ranks','slot_counts','require_slot','install'):self.assertEqual(a[name],b[name],name)
if __name__=='__main__':unittest.main(verbosity=2)
