"""Deterministic local CPU benchmark, not a phone or profitability backtest."""
import copy,json,os,sys,time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path[:0]=[os.environ['OKX_TEST_CORE'],os.environ['OKX_TEST_HOST']]
import okx_channel701 as ch,okx_pattern15 as trend
from phone_performance import Timing
from phone_signal_cache import install
fixture=json.loads((Path(__file__).parents[1]/'phone_v118/test_signal_fixture.json').read_text())
now=int(fixture['now']);rows=[copy.deepcopy(fixture['row'])];rows[0]['instrument']['lever']='100'
for bars in rows[0]['live_frames'].values():
 for r in bars:r[0]=int(r[0])
for i in range(288):
 frames={f:[[now//step*step-(300-j)*step,100.,101.,99.,100.,100.] for j in range(300)] for f,step in trend.STEPS.items()}
 rows.append(dict(symbol=f'TEST{i}-USDT-SWAP',instrument={'lever':'100','instCategory':'1'},live_frames=frames))
cfg={'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]}}
e=NS(api=NS(now_ms=lambda:now),can_open_position=lambda:True,universe=NS(read=lambda:({'rows':rows},None)),records=lambda:[],blocked_manual_symbols=lambda:set(),cfg=cfg,journal=NS(data={}),stream=NS(watch=lambda x:None,ready=lambda *a:False),chat=NS(watch=lambda:[]),pipeline=lambda *a,**k:None)
t=Timing('/tmp');t.local.group='optimized';install(t,json.loads((Path(os.environ['OKX_TEST_HOST'])/'phone_sources.json').read_text()))
with patch.object(trend,'allowed',return_value=True):
 ch.candidate(e)
 before=t.metrics[('optimized','signal.closed_validation.compute')]['calls'];times=[]
 for _ in range(10):
  start=time.perf_counter();ch.candidate(e);times.append(time.perf_counter()-start)
after=t.metrics[('optimized','signal.closed_validation.compute')]['calls']
print(json.dumps(dict(host=Path(os.environ['OKX_TEST_HOST']).name,symbols=289,repeated_scans=10,mean_s=sum(times)/len(times),max_s=max(times),repeated_full_validations=after-before,pending=len(e.channel_pending),note='Synthetic local warm scans; no network, orders or phone speed claim.')))
