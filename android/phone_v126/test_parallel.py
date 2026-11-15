"""Real spawn workers, real candidate; no exchange client and no orders."""
import copy,json,os,queue,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path[:0]=[os.environ['OKX_TEST_HOST'],os.environ['OKX_TEST_CORE']]
import okx_channel701 as ch
from phone_signal_cache import install
from phone_performance import Timing
from phone_parallel import Manager,Pool,preference,set_preference

class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.timer=Timing('/tmp');cls.timer.local.group='optimized'
  cls.pins=json.loads((Path(os.environ['OKX_TEST_HOST'])/'phone_sources.json').read_text());install(cls.timer,cls.pins)
  cls.fixture=json.loads((Path(__file__).parents[1]/'phone_v118/test_signal_fixture.json').read_text())
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.manager=Manager(self.root,self.pins,os.environ['OKX_TEST_CORE']);self.timer.parallel=self.manager
  self.clock=int(self.fixture['now']);self.cfg={'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]},'selection':{}}
  self.rows=[]
  for i in range(12):
   r=copy.deepcopy(self.fixture['row']);r['symbol']=f'X{i:03}-USDT-SWAP'
   r['instrument']=dict(instId=r['symbol'],state='live',settleCcy='USDT',ctType='linear',ctValCcy=r['symbol'].split('-')[0],instCategory='1',lever='100')
   for bars in r['live_frames'].values():
    for b in bars:b[0]=int(b[0])
   self.rows.append(r)
 def tearDown(self):self.manager.close();self.temp.cleanup();self.timer.parallel=None
 def engine(self):
  return NS(api=NS(now_ms=lambda:self.clock),can_open_position=lambda:True,universe=NS(read=lambda:({'rows':self.rows},None)),records=lambda:[],blocked_manual_symbols=lambda:set(),cfg=self.cfg,journal=NS(data={}),stream=NS(watch=lambda x:None,ready=lambda *a:False),chat=NS(watch=lambda:[]),pipeline=lambda *a,**k:None,events=queue.Queue())
 def compare(self):
  self.timer.parallel=None;a=self.engine();ch.candidate(a)
  self.timer.parallel=self.manager;b=self.engine();ch.candidate(b)
  self.assertEqual(a.channel_pending,b.channel_pending)
  return b
 def test_same_signals_priority_changes_and_expiry(self):
  b=self.compare();self.assertEqual(len(b.channel_pending),12);self.assertEqual(self.manager.effective,4)
  for i in range(3):
   self.rows[i]['live_frames']['1H'][-2][5]+=3;self.compare()
  self.clock+=90001;self.assertFalse(self.compare().channel_pending)
 def test_restore_closes_workers_and_persists(self):
  self.compare();ps=list(self.manager.pool.procs)
  set_preference(self.root,0);self.compare()
  self.assertFalse(any(p.is_alive() for p in ps));self.assertEqual(self.manager.effective,0)
  fresh=Manager(self.root,self.pins,os.environ['OKX_TEST_CORE']);self.assertTrue(fresh.prepare(self.engine()));self.assertIsNone(fresh.pool);fresh.close()
  set_preference(self.root,4);self.compare();self.assertEqual(self.manager.effective,4)
 def test_dead_worker_falls_back_and_skips_failed_tick(self):
  self.compare();self.manager.pool.procs[0].terminate();self.manager.pool.procs[0].join()
  e=self.engine();self.assertIsNone(ch.candidate(e));self.assertEqual(preference(self.root)['workers'],0)
  self.assertEqual(len(self.compare().channel_pending),12)
 def test_timeout_falls_back_and_cleans_children(self):
  self.compare();ps=list(self.manager.pool.procs)
  with patch.object(self.manager.pool,'run',side_effect=TimeoutError('test')):self.assertFalse(self.manager.prepare(self.engine()))
  self.assertFalse(any(p.is_alive() for p in ps));self.assertEqual(preference(self.root)['workers'],0)
 def test_bad_response_revision_rejected(self):
  self.compare()
  with patch.object(self.manager.pool,'run',return_value=[(-1,{})]*4):self.assertFalse(self.manager.prepare(self.engine()))
  self.assertEqual(preference(self.root)['workers'],0)
 def test_switch_during_worker_result_discards_batch(self):
  self.compare();run=self.manager.pool.run
  def switched(tasks):
   result=run(tasks);set_preference(self.root,0);return result
  with patch.object(self.manager.pool,'run',side_effect=switched):self.assertFalse(self.manager.prepare(self.engine()))
  self.assertIsNone(self.manager.pool)
 def test_correction_and_config_never_reuse_old_packet(self):
  self.assertTrue(self.manager.prepare(self.engine()))
  row=self.rows[0];self.assertIsNotNone(self.manager.lookup(row,self.cfg,self.clock))
  changed=copy.deepcopy(row);changed['live_frames']['1H'][-2][5]+=1
  self.assertIsNone(self.manager.lookup(changed,self.cfg,self.clock))
  cfg=copy.deepcopy(self.cfg);cfg['indicators']['bb_multiplier']=3
  self.assertIsNone(self.manager.lookup(row,cfg,self.clock))
  self.assertIsNone(self.manager.lookup(row,self.cfg,self.clock+900000))
 def test_expiry_while_workers_run_no_final_entry(self):
  self.compare();run=self.manager.pool.run
  def delayed(tasks):
   result=run(tasks);self.clock+=90001;return result
  e=self.engine();e.stream.ready=lambda *a:True
  with patch.object(self.manager.pool,'run',side_effect=delayed),patch.object(ch,'check_entry') as final:
   self.assertIsNone(ch.candidate(e));self.assertFalse(e.channel_pending);final.assert_not_called()
 def test_final_check_runs_only_in_parent_once(self):
  e=self.engine();e.stream.ready=lambda *a:True;e.stream.read=lambda *a:{'last':'100'}
  with patch.object(ch,'check_entry',return_value={}) as final:
   s=ch.candidate(e);self.assertIsNotNone(s);self.assertEqual(final.call_count,1)
 def test_held_seen_and_manual_excluded_by_parent(self):
  b=self.compare();e=self.engine();e.records=lambda:[{'symbol':self.rows[0]['symbol']}]
  e.blocked_manual_symbols=lambda:{self.rows[1]['symbol']}
  s=b.channel_pending[self.rows[2]['symbol']];e.journal.data={'seen_signals':{s['symbol']+':'+s['signal_id']:True}}
  ch.candidate(e);self.assertEqual(len(e.channel_pending),9)
 def test_real_quote_reader_rejects_stale_future_prior_generation(self):
  import time
  from okx_stream import MarketStream
  self.cfg['liquidity']={'ws_max_age_seconds':15}
  for offset,generation,expected in [(-60000,2,0),(501,2,0),(0,1,0),(0,2,1)]:
   e=self.engine();stream=MarketStream();stream.connected=True;stream.generation=2;stream.symbols={r['symbol'] for r in self.rows}
   for row in self.rows:
    for channel in stream.CHANNELS:stream.data[(row['symbol'],channel)]=({'ts':str(self.clock+offset),'last':'100'},time.monotonic(),generation)
   e.stream=stream
   with patch.object(ch,'check_entry',return_value={}) as final:
    ch.candidate(e);self.assertEqual(final.call_count,expected)
 def test_changed_input_after_prepare_uses_current_data(self):
  e=self.engine();calls=[0]
  def read():
   calls[0]+=1
   if calls[0]==2:
    for row in self.rows:row['live_frames']['15m'][-1][4]=float('nan')
   return {'rows':self.rows},None
  e.universe.read=read
  with patch.object(ch,'check_entry') as final:
   self.assertIsNone(ch.candidate(e));self.assertFalse(e.channel_pending);final.assert_not_called()
 def test_connection_change_during_work_discards_batch(self):
  self.compare();run=self.manager.pool.run;e=self.engine();e.stream.generation=1;e.stream.connected=True
  e.account_stream=NS(generation=1,fresh=lambda:True)
  def reconnect(tasks):
   answer=run(tasks);e.stream.generation=2;return answer
  with patch.object(self.manager.pool,'run',side_effect=reconnect),patch.object(ch,'check_entry') as final:
   self.assertIsNone(ch.candidate(e));final.assert_not_called()
  self.assertEqual(preference(self.root)['workers'],4)
  self.assertEqual(self.manager.packets,{})
 def test_invalid_preferences_fail_to_serial(self):
  (self.root/'phone_calculation.json').write_text('{broken')
  self.assertFalse(self.manager.prepare(self.engine()));self.assertEqual(preference(self.root)['workers'],0)
 def test_resource_summary_counts_workers(self):
  self.compare();r=self.manager.report();self.assertEqual(r['workers_alive'],4);self.assertGreater(r['aggregate_rss_mib'],0)

if __name__=='__main__':unittest.main(verbosity=2)
