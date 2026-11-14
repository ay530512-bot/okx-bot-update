"""Offline repeatability/memory observation, not an Android latency benchmark."""
import copy,json,time,threading,sys,os
from pathlib import Path
sys.path.insert(0,os.environ['OKX_TEST_CORE'])
import phone_performance as perf
from phone_signal_cache import install
import okx_channel701 as channel
fixture=json.loads(Path(__file__).with_name('test_signal_fixture.json').read_text())
rows=[]
for i in range(289):
 r=copy.deepcopy(fixture['row']);r['symbol']=f'SOAK{i}-USDT-SWAP'
 for bars in r['live_frames'].values():
  for bar in bars:
   for j in range(1,5):bar[j]*=1+i*.003
 rows.append(r)
cfg={'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]}}
t=perf.Timing('/tmp');t.local.group='optimized';c=install(t,json.loads(Path(__file__).with_name('phone_sources.json').read_text()))
stop=threading.Event();observations=[];observer_errors=[]
def observer():
 while not stop.wait(.02):
  try:t.report()
  except BaseException as e:observer_errors.append(type(e).__name__);return
thread=threading.Thread(target=observer,daemon=True);thread.start()
start=time.monotonic()
try:
 for n in range(201):
  for row in rows:channel.packet(row,cfg,fixture['now']+n)
  if n in (0,10,50,100,200):observations.append(dict(round=n,cache=c.report(),resources=t.sample_resources()))
finally:stop.set();thread.join(2)
assert not thread.is_alive()
assert not observer_errors,observer_errors
assert observations[-1]['cache']['misses']==observations[0]['cache']['misses']
assert observations[-1]['cache']['evictions']==0
assert observations[-1]['cache']['key_bytes']==observations[0]['cache']['key_bytes']
print(json.dumps(dict(distinct_symbols=289,rounds=201,packets=289*201,elapsed_s=time.monotonic()-start,observations=observations,limitations='Accelerated offline repeat test; no Fold3, thermal, real WS or order execution tested.'),indent=2))
