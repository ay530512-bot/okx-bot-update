"""Actual 1.2.6 candidate integration, serial versus four workers, offline only."""
import copy,hashlib,json,os,queue,statistics,subprocess,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as NS
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1];WORK=REPO.parent
sys.path[:0]=[str(WORK/'fixture121/host-v24'),str(WORK/'core121'),str(REPO/'android/multicore_research_20261115')]
from bench import dataset

def case(mode,kind):
 from phone_performance import Timing
 from phone_signal_cache import install
 from phone_parallel import Manager,set_preference
 from phone_frozen_bars import freeze
 import okx_channel701 as ch
 with tempfile.TemporaryDirectory() as root:
  timer=Timing(root);timer.local.group='optimized';pins=json.loads((WORK/'fixture121/host-v24/phone_sources.json').read_text());install(timer,pins)
  manager=Manager(root,pins,str(WORK/'core121'));timer.parallel=manager;set_preference(root,mode)
  rows,now=dataset(kind)
  for row in rows:row['live_frames']={f:freeze(b) for f,b in row['live_frames'].items()}
  e=NS(api=NS(now_ms=lambda:now),can_open_position=lambda:True,universe=NS(read=lambda:({'rows':rows},None)),records=lambda:[],blocked_manual_symbols=lambda:set(),cfg={'selection':{},'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]}},journal=NS(data={}),stream=NS(watch=lambda x:None,ready=lambda *a:False),chat=NS(watch=lambda:[]),pipeline=lambda *a,**kw:None,events=queue.Queue())
  records=[]
  try:
   for i in range(14):
    label='cold' if i==0 else 'warm' if i<11 else 'all_changed'
    if i>=11:
     for row in rows:
      frames=copy.deepcopy(row['live_frames'])
      for f in ('15m','1H'):frames[f][-2][5]+=i
      row['live_frames']={f:freeze(b) for f,b in frames.items()}
    start=time.perf_counter();ch.candidate(e);elapsed=time.perf_counter()-start
    if mode and manager.effective!=4:raise RuntimeError(manager.report())
    digest=hashlib.sha256(json.dumps(sorted(e.channel_pending.items(),key=ch.rank_item),sort_keys=True).encode()).hexdigest()
    records.append(dict(label=label,seconds=elapsed,signals=len(e.channel_pending),sha256=digest))
   return dict(mode=mode,kind=kind,records=records,resources=manager.report())
  finally:manager.close()

if __name__=='__main__':
 if len(sys.argv)>1:print(json.dumps(case(int(sys.argv[1]),sys.argv[2])));sys.exit()
 results=[]
 for rep in range(3):
  for kind in ('mostly_waiting','many_signals'):
   for mode in ((0,4) if rep%2==0 else (4,0)):
    r=subprocess.run([sys.executable,'-B',__file__,str(mode),kind],capture_output=True,text=True,timeout=90,check=True)
    d=json.loads(r.stdout);d['rep']=rep;results.append(d)
 for kind in ('mostly_waiting','many_signals'):
  rows=[r for r in results if r['kind']==kind];expected=[x['sha256'] for x in rows[0]['records']]
  assert all([x['sha256'] for x in r['records']]==expected for r in rows)
 summary=[]
 for kind in ('mostly_waiting','many_signals'):
  for mode in (0,4):
   rows=[r for r in results if r['kind']==kind and r['mode']==mode]
   summary.append(dict(kind=kind,mode=mode,**{label:statistics.median(x['seconds'] for r in rows for x in r['records'] if x['label']==label) for label in ('cold','warm','all_changed')}))
 out=dict(cases=12,scans=168,equivalence=True,summary=summary,raw=results,limits='x86 server, synthetic/retained fixture input, not Fold or exchange latency; cold includes spawn')
 (HERE/'benchmark.json').write_text(json.dumps(out,indent=2));print(json.dumps(summary,indent=2))
