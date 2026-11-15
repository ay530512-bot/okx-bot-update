"""Reproduce long-scan/future-quote rejection against the real stream reader.
No account calls and no orders; final check is a spy, not an exchange client.
"""
import copy,json,os,queue,sys,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path[:0]=[os.environ['OKX_TEST_CORE'],os.environ['OKX_TEST_HOST']]
import okx_channel701 as ch,okx_two_wick732 as pat,okx_band_flow as ind,okx_pattern15 as trend
from okx_stream import MarketStream
from phone_signal_cache import install
from phone_performance import Timing

class ClockTests(unittest.TestCase):
 def setUp(self):
  self.original=(ch.packet,ch.candidate,ch.closed,pat.select,ind.view,trend.summary)
  self.fixture=json.loads((Path(__file__).parents[1]/'phone_v118/test_signal_fixture.json').read_text())
  self.now=int(self.fixture['now']);self.row=copy.deepcopy(self.fixture['row'])
  self.row['instrument']['lever']='100'
  for bars in self.row['live_frames'].values():
   for r in bars:r[0]=int(r[0])
  self.timer=Timing('/tmp');self.timer.local.group='optimized'
  self.cache=install(self.timer,json.loads((Path(os.environ['OKX_TEST_HOST'])/'phone_sources.json').read_text()))
 def tearDown(self):ch.packet,ch.candidate,ch.closed,pat.select,ind.view,trend.summary=self.original
 def run_candidate(self,fn,delay=9000,quote_offset=0,generation=1):
  clock=[self.now];s=MarketStream();s.connected=True;s.generation=1;s.symbols={self.row['symbol']}
  cfg={'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]},'liquidity':{'ws_max_age_seconds':15}}
  e=NS(api=NS(now_ms=lambda:clock[0]),can_open_position=lambda:True,universe=NS(read=lambda:({'rows':[self.row]},None)),records=lambda:[],blocked_manual_symbols=lambda:set(),cfg=cfg,journal=NS(data={}),stream=s,chat=NS(watch=lambda:[]),pipeline=lambda *a,**k:None,events=queue.Queue())
  packet=ch.packet
  def delayed(*a,**kw):
   result=packet(*a,**kw)
   clock[0]=self.now+delay
   for channel in s.CHANNELS:s.data[(self.row['symbol'],channel)]=({'ts':str(clock[0]+quote_offset),'last':'100'},time.monotonic(),generation)
   return result
  with patch.object(ch,'packet',side_effect=delayed),patch.object(trend,'allowed',return_value=True),patch.object(ch,'check_entry',return_value={}) as final:
   result=fn(e)
   return result,e,final.call_count
 def test_prepatch_rejects_fresh_quotes_after_nine_second_scan(self):
  result,e,calls=self.run_candidate(self.original[1])
  self.assertIsNone(result);self.assertEqual(calls,0);self.assertTrue(e.channel_pending)
 def test_fix_passes_same_quote_to_final_check(self):
  result,e,calls=self.run_candidate(ch.candidate)
  self.assertIsNotNone(result);self.assertEqual(calls,1)
  self.assertEqual(e.phone_entry_diagnostic['result'],'주문 전 최종 검사로 전달')
 def test_stale_future_and_prior_generation_still_blocked(self):
  for offset,generation in [(-60000,1),(501,1),(0,0)]:
   with self.subTest(offset=offset,generation=generation):
    result,e,calls=self.run_candidate(ch.candidate,quote_offset=offset,generation=generation)
    self.assertIsNone(result);self.assertEqual(calls,0)
    self.assertEqual(e.phone_entry_diagnostic['reasons']['실시간 자료 대기'],1)
 def test_expiry_during_scan_drops_signal(self):
  result,e,calls=self.run_candidate(ch.candidate,delay=90001)
  self.assertIsNone(result);self.assertEqual(calls,0);self.assertFalse(e.channel_pending)
 def test_repeated_inputs_skip_validation_but_not_quote_checks(self):
  self.run_candidate(ch.candidate)
  before=self.timer.metrics[('optimized','signal.validated_selection.compute')]['calls']
  result,e,calls=self.run_candidate(ch.candidate,quote_offset=-60000)
  self.assertIsNone(result);self.assertEqual(calls,0)
  self.assertEqual(before,self.timer.metrics[('optimized','signal.validated_selection.compute')]['calls'])
 def test_bad_or_changed_candles_cannot_reuse_success(self):
  self.run_candidate(ch.candidate)
  for field,value in [(4,float('nan')),(5,-1),(3,1000000),(0,self.row['live_frames']['15m'][-1][0]+1)]:
   original=copy.deepcopy(self.row)
   self.row['live_frames']['15m'][-1][field]=value
   result,e,calls=self.run_candidate(ch.candidate)
   self.assertIsNone(result);self.assertEqual(calls,0)
   self.row=original
 def test_hourly_correction_invalidates_selection_cache(self):
  self.run_candidate(ch.candidate)
  before=self.cache.report()['misses']
  self.row['live_frames']['1H'][-2][5]+=1
  self.run_candidate(ch.candidate)
  self.assertGreater(self.cache.report()['misses'],before)

if __name__=='__main__':unittest.main()
