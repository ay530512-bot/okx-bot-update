import sys,time,threading,types,unittest
sys.path.insert(0,'chart_update')
import okx_band_flow as b,okx_core,okx_oct23
from okx_candle_gate732 import CandleReadGate
from unittest.mock import patch
class Tests(unittest.TestCase):
 def test_tail_equivalence_and_gap(self):
  step=900000;now=step*1000
  def bars(end,n):return [[t,1,2,.5,1.5,10] for t in range(end-(n-1)*step,end+1,step)]
  old=(0,bars(now-2*step,299));fresh=bars(now,4)
  self.assertEqual(b.candle_request_limit(old,'15m',now),4)
  merged=b.merge_completed(old,fresh,'15m',now,4)
  self.assertEqual(merged,bars(now-step,299))
  self.assertNotIn(now,[r[0] for r in merged])
  with self.assertRaises(okx_core.BotError):b.merge_completed(old,bars(now+step*4,1),'15m',now+step*5,4)
  self.assertEqual(b.candle_request_limit(old,'15m',now+1000*step),300)
 def test_confirmed_only(self):
  now=1800000
  raw=[['900000','1','2','.5','1.5','1','1','1','0'],['0','1','2','.5','1.5','1','1','1','1']]
  self.assertEqual([r[0] for r in b.rows(raw,'15m',now)],[0])
  self.assertFalse(b.completed_cache((0,b.rows(raw,'15m',now)),'15m',now))
 def test_gate_budget_backoff(self):
  clock=[100.]
  gate=CandleReadGate(lambda:clock[0],lambda delay:clock.__setitem__(0,clock[0]+max(delay,1e-10)))
  timestamps=[]
  for _ in range(100):gate.acquire();timestamps.append(clock[0])
  self.assertTrue(all(sum(t<=v<t+2 for v in timestamps)<=36 for t in timestamps))
  at=clock[0];gate.limited();gate.limited();self.assertEqual(gate.failures,1)
  gate.acquire();self.assertGreaterEqual(clock[0]-at,2)
  at=clock[0];gate.limited();gate.acquire();self.assertGreaterEqual(clock[0]-at,4)
 def test_parallel_cache_publish(self):
  now=144000000;calls=[];active=[0,0];guard=threading.Lock();published=[];rates=[]
  class API:
   def __init__(self,*a):self.session=types.SimpleNamespace(close=lambda:None)
   def now_ms(self):return now
   def public(self,path,**kw):
    with guard:active[0]+=1;active[1]=max(active);calls.append(kw)
    time.sleep(.02);step=b.STEPS[kw['bar']]
    data=[[str(now-j*step),'1','2','.5','1.5','10','10','10','1' if j else '0'] for j in range(int(kw['limit']))]
    with guard:active[0]-=1
    return data
  class Owner:
   settings={};cfg={'execution':{'rule_channel701':True}};search_generation=0
   stop_event=threading.Event();search_paused=threading.Event();lock=threading.RLock()
   def throttle(self,requests_per_second=None):rates.append(requests_per_second)
   @property
   def result(self):return self._result
   @result.setter
   def result(self,v):self._result=v;published.append(len(v['rows']))
  owner=Owner();instruments={str(n):{'instId':str(n)} for n in range(48)}
  market=types.SimpleNamespace(owner=owner,market=lambda:{'instruments':instruments,'quotes':{}})
  with patch.object(okx_core,'OKX',API),patch.object(okx_oct23,'enabled',lambda c:False):
   r=b.scan(market);self.assertEqual(len(r['rows']),48);self.assertGreater(active[1],12);self.assertLessEqual(active[1],24)
   self.assertLess(published[0],48);self.assertEqual(len(calls),144);self.assertEqual(set(rates),{14})
   b.scan(market);self.assertEqual(len(calls),144)
   now+=900000;b.scan(market);self.assertEqual(len(calls),192)
   self.assertTrue(all(c['limit']=='4' for c in calls[144:]))
   self.assertTrue(all(len(v[1])==299 for v in market.band_cache.values()))
   owner.search_paused.set();self.assertIsNone(b.scan(market));self.assertEqual(len(calls),192)
  print('48-symbol simulation: 24 workers; 144 cold calls; 0 repeats; 48 tail calls x 4 rows; 299-bar history retained')
unittest.main()
