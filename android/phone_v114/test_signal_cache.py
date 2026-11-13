import copy, json, os, random, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import phone_performance as perf
from phone_signal_cache import SignalCache,install

class CacheTests(unittest.TestCase):
 def test_full_inputs_invalidation_and_copy(self):
  t=perf.Timing('/tmp');t.local.group='optimized';c=SignalCache(t,2)
  fn=Mock(side_effect=lambda b,c: {'value':[sum(b),c['x']]});f=c.wrap(fn,'test')
  with c.packet_scope():
   a=f([1,2],{'x':3});a['value'][0]=99
   self.assertEqual(f([1,2],{'x':3}),{'value':[3,3]});self.assertEqual(fn.call_count,1)
   f([2,2],{'x':3});f([2,2],{'x':4});self.assertEqual(fn.call_count,3)
   self.assertEqual(c.report()['entries'],2)
  f([2,2],{'x':4});self.assertEqual(fn.call_count,4)
  with c.packet_scope():
   t.local.group='baseline';f([2,2],{'x':4});self.assertEqual(fn.call_count,5)
 def test_exception_not_cached(self):
  t=perf.Timing('/tmp');t.local.group='optimized';c=SignalCache(t)
  fn=Mock(side_effect=ValueError('fixture'));f=c.wrap(fn,'test')
  with c.packet_scope():
   for _ in range(2):
    with self.assertRaises(ValueError):f([1])
  self.assertEqual(fn.call_count,2);self.assertEqual(c.report()['entries'],0)
 def test_real_packets_and_current_quote_boundary(self):
  sys.path.insert(0,os.environ['OKX_TEST_CORE'])
  import okx_channel701 as channel,okx_two_wick732 as patterns,okx_band_flow as indicators,okx_pattern15 as analysis
  originals=(channel.packet,patterns.select,indicators.view,analysis.summary)
  pins=json.loads(Path(perf.__file__).with_name('phone_sources.json').read_text())
  t=perf.Timing('/tmp');t.local.group='optimized';c=install(t,pins)
  cfg={'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]}}
  now=1800000000000//14400000*14400000
  rng=random.Random(114)
  def bars(step,seed):
   out=[];price=seed
   for i in range(300):
    close=price*(1+rng.uniform(-.012,.013));lo=min(price,close)*.995;hi=max(price,close)*1.005
    out.append([now-(300-i)*step,price,hi,lo,close,rng.uniform(100,300)]);price=close
   return out
  def original_packet(row,cfg,now,quote=None):
   saved=(patterns.select,indicators.view,analysis.summary)
   patterns.select,indicators.view,analysis.summary=originals[1:]
   try:return originals[0](row,cfg,now,quote)
   finally:patterns.select,indicators.view,analysis.summary=saved
  try:
   fixture=json.loads(Path(__file__).with_name('test_signal_fixture.json').read_text())
   real=fixture['row'];at=fixture['now']
   expected=original_packet(real,cfg,at)
   self.assertTrue(expected['entry_setups'])
   for offset in (0,1000,89999,90001):
    actual=channel.packet(real,cfg,at+offset)
    control=original_packet(real,cfg,at+offset)
    self.assertEqual(actual,control)
    action=control['entry_setups'][0]['action']
    from okx_core import BotError
    if offset<=90000:
     self.assertEqual(channel.make_signal({'action':action},actual,cfg,at+offset),channel.make_signal({'action':action},control,cfg,at+offset))
    else:
     with self.assertRaises(BotError):channel.make_signal({'action':action},actual,cfg,at+offset)
   # Final check_entry/setup must execute select outside the cached packet scope.
   misses,hits=c.misses,c.hits
   channel.setup(real['live_frames']['15m'],real['live_frames']['1H'])
   self.assertEqual((c.misses,c.hits),(misses,hits))
   rows=[]
   for i in range(60):
    row={'symbol':'AAVE-USDT-SWAP','instrument':{'instCategory':'1'},'live_frames':{f:bars(step,100+i) for f,step in analysis.STEPS.items()}}
    rows.append(row)
    expected=original_packet(row,cfg,now)
    self.assertEqual(channel.packet(row,cfg,now),expected)
    self.assertEqual(channel.packet(copy.deepcopy(row),cfg,now+123),original_packet(row,cfg,now+123))
   row=rows[0]
   for quote in ({'last':'150'},{'last':'151'}):
    self.assertEqual(channel.packet(row,cfg,now,quote),original_packet(row,cfg,now,quote))
   changed=copy.deepcopy(row);changed['live_frames']['15m'][0][5]+=1
   misses=c.misses;self.assertEqual(channel.packet(changed,cfg,now),original_packet(changed,cfg,now));self.assertGreater(c.misses,misses)
   cfg2=copy.deepcopy(cfg);cfg2['indicators']['bb_multiplier']=2.5
   self.assertEqual(channel.packet(row,cfg2,now),original_packet(row,cfg2,now))
   from okx_core import BotError
   # Freshness validation still runs even if all old indicators are cached.
   with self.assertRaises(BotError):channel.packet(row,cfg,now+900000)
   fresh=copy.deepcopy(row);last=fresh['live_frames']['15m'][-1];fresh['live_frames']['15m'].append([now,last[4],last[4]*1.01,last[4]*.99,last[4],200])
   self.assertEqual(channel.packet(fresh,cfg,now+900000),original_packet(fresh,cfg,now+900000))
   # Caller mutation of nested returned structures cannot corrupt the cache.
   result=channel.packet(row,cfg,now);result['frames']['15m']['ma'].clear()
   self.assertEqual(channel.packet(row,cfg,now),original_packet(row,cfg,now))
   # Benchmark equal packet workloads; synthetic data, not Fold/order latency.
   sample=(rows*5)[:289]
   start=time.perf_counter()
   for r in sample:original_packet(r,cfg,now)
   baseline=time.perf_counter()-start
   start=time.perf_counter()
   for r in sample:channel.packet(r,cfg,now)
   warm=time.perf_counter()-start
   print(json.dumps({'benchmark':'synthetic_289_packets_warm','baseline_s':baseline,'cached_s':warm,'cache':c.report()}))
   self.assertGreater(c.hits,0)
  finally:channel.packet,patterns.select,indicators.view,analysis.summary=originals

if __name__=='__main__':unittest.main()
