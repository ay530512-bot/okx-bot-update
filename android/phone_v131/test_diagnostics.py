"""Real source/real archived OHLCV parity; never constructs an exchange client."""
import copy,json,pickle,sys,tempfile,unittest,hashlib,os,time
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'fixture121'/os.environ.get('OKX_AUDIT_HOST','host-v29')),str(ROOT/'fixture121/host-v29'),str(ROOT/'core121')]
import okx_channel701 as C
import okx_two_wick732 as W
from phone_entry_diagnostics import make_selector,accumulate,History
PINS=json.loads((ROOT/'fixture121/host-v29/phone_sources.json').read_text())
SELECT=make_selector(PINS)
FIX=json.loads((ROOT/'release_1110_repo/android/phone_v118/test_signal_fixture.json').read_text())
CFG={'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]}}
class DiagnosticTests(unittest.TestCase):
 def test_missing_hour_is_data_not_pattern(self):
  b=C.closed(FIX['row']['live_frames']['15m'],int(FIX['now']))
  p,status,d=SELECT(b,[])
  self.assertIsNone(p);self.assertEqual(d['data_issue'],'최신 완료1시간봉 대기')
  self.assertEqual(d['routes']['trend_pullback']['status'],'data_wait')
 def test_positive_and_inactive_counts(self):
  b=C.closed(FIX['row']['live_frames']['15m'],int(FIX['now']))
  p,status,d=SELECT(b,FIX['row']['live_frames']['1H'])
  self.assertEqual((p,status),W.select(b,FIX['row']['live_frames']['1H']))
  self.assertEqual(d['routes']['trend_pullback']['status'],'pass')
  self.assertEqual(d['routes']['confirmed_reversal']['status'],'inactive')
  out={};accumulate(out,{'entry_diagnostic':d},'X-USDT-SWAP')
  self.assertEqual(out['routes']['trend_pullback']['pass_count'],1)
  self.assertEqual(out['routes']['confirmed_reversal']['inactive_count'],1)
 def test_short_history_gap_and_bad_values(self):
  b=C.closed(FIX['row']['live_frames']['15m'],int(FIX['now']));h=FIX['row']['live_frames']['1H']
  for bars,hour in [(b[-60:],h),(b[:50]+b[51:],h),(b,h[:-2])]:
   self.assertEqual(SELECT(bars,hour)[:2],W.select(bars,hour))
   self.assertIsNotNone(SELECT(bars,hour)[2]['data_issue'])
 def test_history_survives_restart_and_rotates(self):
  with tempfile.TemporaryDirectory() as p:
   h=History(p);h.observe({'entry':{'reasons':{'data':1}}},{'metrics':[]})
   path=Path(p)/'phone_entry_history.jsonl';first=path.read_text();h.observe({},{});self.assertEqual(path.read_text(),first)
   second=History(p);second.observe({},{});self.assertEqual(len(path.read_text().splitlines()),2)
   path.write_text('x'*(2*1024*1024+1));second.last=0;second.observe({},{});
   self.assertTrue(path.with_name('phone_entry_history.previous.jsonl').exists());self.assertLess(path.stat().st_size,1024)
 def test_history_failure_cannot_interrupt_trading(self):
  with tempfile.TemporaryDirectory() as p:
   (Path(p)/'phone_entry_history.jsonl').symlink_to('/does/not/exist')
   h=History(p);h.observe({},{});self.assertEqual(h.errors,1)
 def test_runtime_writer_exports_history_and_totals(self):
  import phone_runtime_health as health
  with tempfile.TemporaryDirectory() as p:
   timer=NS(root=Path(p),report=lambda:{'elapsed_s':5,'metrics':[]},make_summary=lambda d:{})
   e=NS(phone_entry_diagnostic={'reasons':{'자료 대기':1}},phone_entry_totals={'scans':2},phone_trend_status='추세 대기')
   health.attach(e,timer)
   with patch.object(health,'snapshot',return_value={'public':{},'account':{},'engine':{}}):
    d=timer.report()
   self.assertEqual(d['runtime_health']['program_version'],'1.3.1')
   self.assertEqual(d['runtime_health']['history_write_errors'],0)
   self.assertEqual(d['runtime_health']['entry_observation_totals']['scans'],2)
   self.assertTrue((Path(p)/'phone_entry_history.jsonl').is_file())
 def test_core_rules_same_pc_and_phone(self):
  for name,expected in PINS['files'].items():
   self.assertEqual(hashlib.sha256((ROOT/'core121'/name).read_bytes()).hexdigest(),expected)
  self.assertEqual(PINS,json.loads((ROOT/'fixture121/host-v27/phone_sources.json').read_text()))

def cases():
 source=ROOT/'research_combo_20261115/reference/base/inputs'
 for symbol in ('ARB','OP','SEI','WLD','TIA'):
  x=pickle.loads((source/(symbol+'.pickle')).read_bytes());b,h,q=x['b'],x['h'],x['q']
  known={v['confirmation_ms'] for v in x['proofs']['mild726'].values()}
  old_wicks=json.loads((ROOT/'prior_wick/WICK_BODY_COMPARISON_20261115/signals.json').read_text())['old']
  known.update(v['confirmation_ms'] for v in old_wicks.get(symbol,{}).values())
  selected=[i for i,r in enumerate(b) if i>=299 and (r[0] in known or i%137==0)]
  for i in selected:
   now=int(b[i][0])+900000+1000
   def rows(seq,step,limit):
    return [[int(r[0])]+[float(v) for v in r[1:]] for r in seq if r[0]+step<=now][-limit:]
   row=dict(symbol=symbol+'-USDT-SWAP',instrument={'instCategory':'1'},live_frames={'15m':rows(b,900000,299),'1H':rows(h,3600000,100),'4H':rows(q,14400000,100)})
   yield row,now

def parity():
 from phone_performance import Timing
 from phone_signal_cache import install
 from phone_parallel import Pool
 original_packet=C.packet
 timer=Timing('/tmp');timer.local.group='optimized';cache=install(timer,PINS)
 count=positive=negative=0;routes={};pool=Pool(str(ROOT/'core121'),PINS)
 started=time.perf_counter()
 try:
  for row,now in cases():
   reference=original_packet(row,CFG,now)
   with cache.packet_scope(row['symbol']):serial=C._phone_worker_packet(row,CFG,now)
   count+=1
   tasks=[(count,now,CFG,[row['symbol']],[row])]+[(count,now,CFG,[],[]) for _ in range(3)]
   responses=pool.run(tasks);good,parallel=responses[0][1][row['symbol']]
   assert good
   for value in (serial,parallel):
    assert value['entry_setups']==reference['entry_setups'],(row['symbol'],now)
    assert value['or_status']==reference['or_status']
   assert serial==parallel
   if reference['entry_setups']:
    positive+=1;route=reference['entry_setups'][0]['route721'];routes[route]=routes.get(route,0)+1
   else:negative+=1
 finally:pool.close()
 return dict(comparisons=count,positive=positive,negative=negative,routes=routes,seconds=round(time.perf_counter()-started,2),basis='same archived Binance OHLCV, original PC packet vs phone serial vs four real spawn workers',period='2026-08~10, reused data',live_phone=False,missed_live_signals_proven=False)

if __name__=='__main__':
 if os.environ.get('OKX_AUDIT_HOST')=='host-v27':
  audit=parity();audit['host']='1.2.9';(Path(__file__).parent/'comparison_129.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2));print(json.dumps(audit,ensure_ascii=False,indent=2));sys.exit(0)
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DiagnosticTests))
 if not result.wasSuccessful():sys.exit(1)
 audit=parity();audit['diagnostic_tests']=result.testsRun
 (Path(__file__).parent/'comparison_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2));print(json.dumps(audit,ensure_ascii=False,indent=2))
