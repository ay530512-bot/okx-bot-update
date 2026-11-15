"""Offline differential tests; no exchange access or order client."""
import copy,json,os,random,sys,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,os.environ['OKX_TEST_CORE'])
sys.path.insert(0,os.environ['OKX_TEST_HOST'])
import okx_channel701 as ch,okx_two_wick732 as patterns,okx_band_flow as ind,okx_pattern15 as trend
import phone_performance as perf
from phone_signal_cache import install

class Tests(unittest.TestCase):
 def test_differential_candidates(self):
  original=(ch.packet,ch.candidate,ch.closed,patterns.select,ind.view,trend.summary)
  cfg={'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]}}
  fixture=json.loads((Path(__file__).parents[1]/'phone_v118/test_signal_fixture.json').read_text())
  now=fixture['now'];rng=random.Random(121)
  rows=[copy.deepcopy(fixture['row'])];rows[0]['instrument']['lever']='100'
  for i in range(80):
   frames={}
   for f,step in trend.STEPS.items():
    end=now//step*step;price=100.;bars=[]
    for j in range(300):
     close=price*(1+rng.uniform(-.012,.013))
     bars.append([end-(300-j)*step,price,max(price,close)*1.005,min(price,close)*.995,close,rng.uniform(100,300)]);price=close
    frames[f]=bars
   rows.append(dict(symbol=f'X{i}-USDT-SWAP',instrument={'lever':'100','instCategory':'1'},live_frames=frames))
  def engine(data,at):
   return NS(api=NS(now_ms=lambda:at),can_open_position=lambda:True,universe=NS(read=lambda:({'rows':data},None)),records=lambda:[],blocked_manual_symbols=lambda:set(),cfg=cfg,journal=NS(data={}),stream=NS(watch=lambda x:None,ready=lambda *a:False),chat=NS(watch=lambda:[]),pipeline=lambda *a,**k:None)
  with patch.object(trend,'allowed',return_value=True):
   expected=[];start=time.perf_counter()
   for offset in (0,1000,89999,90001,900000,1000,1000,1000):
    e=engine(rows,now+offset);ch.candidate(e);expected.append(copy.deepcopy(e.channel_pending))
   self.assertTrue(expected[0], 'positive fixture must exercise signal construction')
   self.assertFalse(expected[3], 'expired signals must not survive')
   old_time=time.perf_counter()-start
   timer=perf.Timing('/tmp');timer.local.group='optimized'
   pins=json.loads((Path(os.environ['OKX_TEST_HOST'])/'phone_sources.json').read_text())
   cache=install(timer,pins)
   try:
    start=time.perf_counter()
    for i,offset in enumerate((0,1000,89999,90001,900000,1000,1000,1000)):
     e=engine(rows,now+offset);ch.candidate(e);self.assertEqual(e.channel_pending,expected[i])
    new_time=time.perf_counter()-start
    # Full packet API remains complete outside candidate context, including quote updates.
    for q in ({'last':'100'},{'last':'101'}):
     got=ch.packet(rows[0],cfg,now,q)
     self.assertTrue(got['frames']);self.assertEqual(got['price'],float(q['last']))
    # Final admission closed() is never memoized outside packet scopes.
    before=cache.report()['hits'];ch.closed(rows[0]['live_frames']['15m'],now)
    self.assertEqual(cache.report()['hits'],before)
    # Historical correction is observed on a subsequent scan.
    modified=copy.deepcopy(rows);modified[0]['live_frames']['15m'][-1][4]*=1.0001
    e=engine(modified,now);ch.candidate(e);got=copy.deepcopy(e.channel_pending)
    ch.packet,ch.candidate,ch.closed,patterns.select,ind.view,trend.summary=original
    control=engine(modified,now);ch.candidate(control);self.assertEqual(got,control.channel_pending)
    print(json.dumps({'test':'81 symbols, 8 scans including repeated inputs; synthetic workstation, not Fold latency','original_s':old_time,'optimized_s':new_time,'cache':cache.report()}))
   finally:ch.packet,ch.candidate,ch.closed,patterns.select,ind.view,trend.summary=original
if __name__=='__main__':unittest.main()
