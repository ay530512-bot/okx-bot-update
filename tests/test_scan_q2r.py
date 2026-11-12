import sys,time,threading,types,unittest
sys.path.insert(0,'chart_update')
import okx_band_flow as b,okx_core,okx_oct23
from unittest.mock import patch
class Test(unittest.TestCase):
 def test_cache(self):
  self.assertTrue(b.completed_cache((0,[[0]]),'15m',900001))
  self.assertFalse(b.completed_cache((0,[[0]]),'15m',1800000))
 def test_parallel_cache_publish(self):
  now=144000000;calls=[];active=[0,0];guard=threading.Lock();publishes=[]
  class API:
   def __init__(self,*a):self.session=types.SimpleNamespace(close=lambda:None)
   def now_ms(self):return now
   def public(self,path,**kw):
    with guard:active[0]+=1;active[1]=max(active);calls.append(kw)
    time.sleep(.015)
    step=b.STEPS[kw['bar']]
    data=[[str(now-j*step),'1','2','.5','1.5','10','10','10','1' if j else '0'] for j in range(30)]
    with guard:active[0]-=1
    return data
  class Owner:
   settings={};cfg={'execution':{'rule_channel701':True}};search_generation=0
   stop_event=threading.Event();search_paused=threading.Event();lock=threading.RLock()
   def throttle(self):pass # latency/concurrency simulation, not a live exchange test
   @property
   def result(self):return self._result
   @result.setter
   def result(self,v):self._result=v;publishes.append(len(v['rows']))
  owner=Owner();instruments={str(n):{'instId':str(n)} for n in range(24)}
  market=types.SimpleNamespace(owner=owner,market=lambda:{'instruments':instruments,'quotes':{}})
  with patch.object(okx_core,'OKX',API),patch.object(okx_oct23,'enabled',lambda c:False):
   r=b.scan(market);self.assertEqual(len(r['rows']),24);self.assertGreater(active[1],6);self.assertLessEqual(active[1],12)
   self.assertLess(publishes[0],24);self.assertEqual(len(calls),72)
   self.assertTrue(all(x[-1][0]<now for x in [v[1] for v in market.band_cache.values()]))
   b.scan(market);self.assertEqual(len(calls),72) # same closed bars: zero repeat calls
   now+=900000;b.scan(market);self.assertEqual(len(calls),96) # only 15m invalidated
   owner.search_paused.set();self.assertIsNone(b.scan(market));self.assertEqual(len(calls),96)
  print('PASS 24 symbols: 12 concurrent; initial 72 requests; repeat 0; next15m 24; early publish; pause')
unittest.main()
