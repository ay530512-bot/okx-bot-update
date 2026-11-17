"""Real pure workers and public quote reader; order checks are spies, no exchange writes."""
import copy,json,os,queue,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
D=Path(__file__).resolve().parents[1];W=D.parent.parent
sys.path[:0]=[str(D/'phone_v171'),str(W/'core121')]
import okx_channel701 as ch
import okx_pattern15 as pattern
import phone_trend_slot as trend
from okx_stream import MarketStream
from okx_core import BotError
from phone_performance import Timing
from phone_signal_cache import install
from phone_parallel import set_preference,preference,key,connection_token
from phone_mobile_compute import Manager
from phone_quote_registry import attach as attach_quotes
from phone_frozen_bars import FrozenBars

class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.original_candidate=ch.candidate
  cls.original_packet=ch.packet
  cls.timer=Timing('/tmp');cls.timer.local.group='optimized'
  cls.pins=json.loads((D/'phone_v171/phone_sources.json').read_text());install(cls.timer,cls.pins)
  cls.fixture=json.loads((D/'phone_v118/test_signal_fixture.json').read_text())
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.now=int(self.fixture['now']);self.rows=[]
  for i in range(4):
   r=copy.deepcopy(self.fixture['row']);r['symbol']=f'X{i:03}-USDT-SWAP'
   r['instrument']=dict(instId=r['symbol'],state='live',settleCcy='USDT',ctType='linear',ctValCcy=f'X{i:03}',instCategory='1',lever='100')
   for b in r['live_frames'].values():
    for x in b:x[0]=int(x[0])
   self.rows.append(r)
  self.cfg=dict(indicators=dict(bb_period=20,bb_multiplier=2,ma_periods=[15,20,50,100,120,200]),selection={},liquidity=dict(ws_max_age_seconds=15))
  set_preference(self.root,0)
  self.manager=Manager(self.root,self.pins,str(W/'core121'),self.timer);self.timer.parallel=self.manager
  stream=MarketStream();stream.connected=True;stream.generation=1
  self.e=NS(root=self.root/'runtime',api=NS(now_ms=lambda:self.now),can_open_position=lambda:True,
    universe=NS(read=lambda:({'rows':self.rows},None)),records=lambda:[],blocked_manual_symbols=lambda:set(),
    cfg=self.cfg,journal=NS(data={},save=lambda:None),stream=stream,account_stream=NS(generation=1,fresh=lambda:True),
    chat=NS(watch=lambda:[]),pipeline=lambda *a,**k:None,events=queue.Queue())
  self.patch=patch.object(trend,'scan',return_value=None);self.patch.start()
  attach_quotes(self.e)
 def tearDown(self):
  self.patch.stop();self.manager.close();self.manager.executor.shutdown(wait=True,cancel_futures=True);self.tmp.cleanup()
 def ready(self,offset=0,generation=1):
  s=self.e.stream;s.symbols={r['symbol'] for r in self.rows}
  for r in self.rows:
   for c in s.CHANNELS:s.data[(r['symbol'],c)]=({'ts':str(self.now+offset),'last':'100'},time.monotonic(),generation)
 def wait_batch(self):
  self.manager.prepare(self.e)
  f=self.manager.future
  if f:f.result(timeout=15)
  self.manager.prepare(self.e)
 def signals(self):
  self.wait_batch()
  with patch.object(ch,'check_entry',return_value={}) as final:
   s=ch.candidate(self.e)
  return s,final.call_count
 def test_same_candidate_and_priority_as_original(self):
  self.ready();self.wait_batch()
  old=copy.copy(self.e);old.journal=NS(data={});old.channel_pending={}
  with patch.object(ch,'check_entry',return_value={}):
   expected=type(self).original_candidate(old);got=ch.candidate(self.e)
  # The original signal/priority remains exact; only immutable comparison
  # evidence is added for a future confirmed automatic position.
  clean=lambda s:{k:v for k,v in s.items() if k!='similarity_reference169'}
  self.assertEqual(clean(got),expected)
  self.assertEqual({k:clean(v) for k,v in self.e.channel_pending.items()},old.channel_pending)
 def test_exact_inputs_not_recomputed_on_every_tick(self):
  self.wait_batch();count=self.manager.completed
  for _ in range(10):self.manager.prepare(self.e)
  self.assertIsNone(self.manager.future);self.assertEqual(self.manager.completed,count)
 def test_invalid_preference_recovers_to_single_computation(self):
  (self.root/'phone_calculation.json').write_text('{broken')
  self.assertFalse(self.manager.prepare(self.e));self.assertEqual(preference(self.root)['workers'],0)
  self.wait_batch();self.assertIsNotNone(self.manager.lookup(self.rows[0],self.cfg,self.now))
 def test_changed_old_hourly_bar_recomputes(self):
  self.wait_batch();self.rows[0]['live_frames']['1H'][-2][5]+=1
  self.assertIsNone(self.manager.lookup(self.rows[0],self.cfg,self.now))
  self.wait_batch();self.assertIsNotNone(self.manager.lookup(self.rows[0],self.cfg,self.now))
 def test_changed_cfg_and_cutoff_not_reused(self):
  self.wait_batch();cfg=copy.deepcopy(self.cfg);cfg['indicators']['bb_multiplier']=3
  self.assertIsNone(self.manager.lookup(self.rows[0],cfg,self.now))
  self.assertIsNone(self.manager.lookup(self.rows[0],self.cfg,self.now+900000))
 def test_existing_candidate_survives_blocked_new_batch(self):
  self.signals();self.assertEqual(len(self.e.channel_pending),4)
  entered=threading.Event();release=threading.Event();original=self.manager.work
  def blocked(job):entered.set();release.wait(5);return original(job)
  self.rows[0]['live_frames']['1H'][-2][5]+=1
  try:
   with patch.object(self.manager,'work',side_effect=blocked):
    self.manager.prepare(self.e);self.assertTrue(entered.wait(1));self.ready()
    t=time.perf_counter()
    with patch.object(ch,'check_entry',return_value={}) as final:s=ch.candidate(self.e)
    elapsed=time.perf_counter()-t
    self.assertLess(elapsed,.5);self.assertIsNotNone(s);self.assertEqual(final.call_count,1)
    self.assertFalse(self.manager.future.done())
  finally:release.set()
 def test_cold_start_candidate_does_not_wait_for_workers(self):
  entered=threading.Event();release=threading.Event()
  def blocked(job):entered.set();release.wait(5);return dict(packets={},seconds=1)
  try:
   with patch.object(self.manager,'work',side_effect=blocked):
    t=time.perf_counter();self.assertIsNone(ch.candidate(self.e));elapsed=time.perf_counter()-t
    self.assertLess(elapsed,.5);self.assertTrue(entered.wait(1));self.assertFalse(self.manager.future.done())
  finally:release.set()
 def test_only_one_batch_bounded_while_work_is_pending(self):
  release=threading.Event();original=self.manager.work
  def blocked(job):release.wait(5);return original(job)
  try:
   with patch.object(self.manager,'work',side_effect=blocked) as work:
    self.manager.prepare(self.e);future=self.manager.future
    for i in range(20):
     self.rows[0]['live_frames']['1H'][-2][5]+=1;self.manager.prepare(self.e)
     self.assertIs(self.manager.future,future)
    self.assertEqual(work.call_count,1)
  finally:release.set()
 def test_generation_change_discards_finished_batch(self):
  self.manager.prepare(self.e);self.manager.future.result(timeout=10);self.e.stream.generation+=1
  self.manager.prepare(self.e);self.assertEqual(self.manager.packets,{});self.assertEqual(self.manager.discarded,1)
 def test_account_generation_change_discards(self):
  self.manager.prepare(self.e);self.manager.future.result(timeout=10);self.e.account_stream.generation+=1
  self.manager.prepare(self.e);self.assertEqual(self.manager.packets,{})
 def test_disconnect_invalidates_publication(self):
  self.wait_batch();self.e.stream.connected=False;self.manager.prepare(self.e)
  self.assertIsNone(self.manager.lookup(self.rows[0],self.cfg,self.now))
 def test_preference_change_discards_finished_batch(self):
  self.manager.prepare(self.e);self.manager.future.result(timeout=10);set_preference(self.root,4)
  self.manager.prepare(self.e);self.assertEqual(self.manager.packets,{})
 def test_expiry_after_work_never_reaches_final_check(self):
  self.manager.prepare(self.e);self.manager.future.result(timeout=10);self.now+=90001;self.ready()
  self.manager.prepare(self.e)
  with patch.object(ch,'check_entry') as final:self.assertIsNone(ch.candidate(self.e));final.assert_not_called()
  self.assertFalse(self.e.channel_pending)
 def test_expiry_while_existing_candidate_waits(self):
  self.signals();self.now+=90001;self.ready()
  with patch.object(ch,'check_entry') as final:self.assertIsNone(ch.candidate(self.e));final.assert_not_called()
  self.assertFalse(self.e.channel_pending)
 def test_current_quote_reader_stale_future_generation(self):
  self.wait_batch()
  for offset,generation,expected in [(-60000,1,0),(501,1,0),(0,0,0),(0,1,1)]:
   self.ready(offset,generation)
   with patch.object(ch,'check_entry',return_value={}) as final:ch.candidate(self.e)
   self.assertEqual(final.call_count,expected)
 def test_ui_watch_change_does_not_remove_candidates(self):
  self.signals();self.ready();saved=dict(self.e.stream.data)
  for _ in range(5):self.e.stream.watch(['UI-USDT-SWAP']);self.e.stream.watch(['OTHER-USDT-SWAP'])
  for r in self.rows:
   self.assertIn(r['symbol'],self.e.stream.symbols)
   for c in self.e.stream.CHANNELS:self.assertEqual(self.e.stream.data[(r['symbol'],c)],saved[(r['symbol'],c)])
 def test_invalid_and_corrected_inputs_fail_closed(self):
  self.wait_batch();old=copy.deepcopy(self.rows[0])
  for field,value in [(4,float('nan')),(5,-1),(3,1000000),(0,self.rows[0]['live_frames']['15m'][-1][0]+1)]:
   self.rows[0]=copy.deepcopy(old);self.rows[0]['live_frames']['15m'][-1][field]=value
   self.wait_batch()
   with self.assertRaises(BotError):self.manager.lookup(self.rows[0],self.cfg,self.now)
 def test_workers_never_receive_engine_or_secrets(self):
  self.manager.prepare(self.e);job=self.manager.request
  self.assertEqual(set(job['cfg']),{'indicators'})
  self.assertEqual(set(job['rows'][0]),{'symbol','instrument','live_frames'})
  self.assertIsInstance(job['rows'][0]['live_frames']['15m'],FrozenBars)
  old=job['rows'][0]['live_frames']['15m'][-1][4];self.rows[0]['live_frames']['15m'][-1][4]+=1
  self.assertEqual(job['rows'][0]['live_frames']['15m'][-1][4],old)
 def test_held_manual_seen_excluded(self):
  self.signals();s=self.e.channel_pending[self.rows[2]['symbol']]
  self.e.records=lambda:[{'symbol':self.rows[0]['symbol'],'direction':'long'}]
  self.e.blocked_manual_symbols=lambda:{self.rows[1]['symbol']}
  self.e.journal.data={'seen_signals':{s['symbol']+':'+s['signal_id']:True}}
  ch.candidate(self.e);self.assertEqual(set(self.e.channel_pending),{self.rows[3]['symbol']})
 def test_conflict_removes_pending(self):
  self.signals();self.assertTrue(self.e.channel_pending)
  with patch.object(self.manager,'lookup',return_value={'entry_setups':[],'or_status':'conflict'}):ch.candidate(self.e)
  self.assertFalse(self.e.channel_pending)
 def test_final_rest_rejection_never_returns_candidate(self):
  self.ready();self.wait_batch()
  with patch.object(ch,'check_entry',side_effect=BotError('통로 원래 완료봉 신호 변경')) as final:
   self.assertIsNone(ch.candidate(self.e));self.assertEqual(final.call_count,4)
 def test_trend_count_and_priority(self):
  self.ready();self.wait_batch();row=self.rows[0];s={'symbol':row['symbol'],'signal_id':'trend','trend130':True,'valid_from_ms':self.now,'expires_ms':self.now+90000,'reason':'trend','action':'LONG'}
  with patch.object(trend,'scan',return_value=s),patch.object(trend,'in_window',return_value=True),patch.object(ch,'check_entry',return_value={}):got=ch.candidate(self.e)
  self.assertEqual(got,s);self.assertEqual(self.e.phone_entry_totals['candidate_returns'],1)
 def test_common_three_slot_limit(self):
  self.ready();self.wait_batch()
  with patch.object(trend,'slot_counts',return_value=(3,0,3)),patch.object(ch,'check_entry') as final:
   self.assertIsNone(ch.candidate(self.e));final.assert_not_called()
 def test_worker_failure_falls_back_without_losing_valid_pending(self):
  self.signals();set_preference(self.root,4)
  with patch.object(self.manager,'work',side_effect=TimeoutError('offline simulated stall')):
   self.manager.prepare(self.e)
   with self.assertRaises(TimeoutError):self.manager.future.result(timeout=2)
   self.manager.prepare(self.e)
  self.assertEqual(preference(self.root)['workers'],0)
  self.ready()
  with patch.object(ch,'check_entry',return_value={}):self.assertIsNotNone(ch.candidate(self.e))
 def test_real_four_spawn_workers_match_serial_then_restore(self):
  self.wait_batch();a={r['symbol']:self.manager.lookup(r,self.cfg,self.now) for r in self.rows}
  set_preference(self.root,4);self.wait_batch();b={r['symbol']:self.manager.lookup(r,self.cfg,self.now) for r in self.rows}
  self.assertEqual(a,b);self.assertEqual(self.manager.report()['workers_alive'],4)
  procs=list(self.manager.pool.procs)
  set_preference(self.root,0);self.wait_batch();self.assertFalse(any(p.is_alive() for p in procs))
 def test_real_dead_worker_falls_back(self):
  set_preference(self.root,4);self.wait_batch();p=self.manager.pool.procs[0];p.terminate();p.join()
  self.rows[0]['live_frames']['1H'][-2][5]+=1;self.manager.prepare(self.e)
  with self.assertRaises(Exception):self.manager.future.result(timeout=12)
  self.manager.prepare(self.e);self.assertEqual(preference(self.root)['workers'],0)
  self.wait_batch();self.assertIsNotNone(self.manager.lookup(self.rows[0],self.cfg,self.now))

if __name__=='__main__':unittest.main(verbosity=2)
